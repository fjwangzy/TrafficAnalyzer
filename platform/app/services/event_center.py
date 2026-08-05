"""Unified event facts behind one query/review interface.

The module normalizes replayable AI events and actual conflict facts without
flattening their type-specific evidence or review semantics.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.alert import AlertRecord
from app.models.metrics import ConflictEvent, ConflictReview, TelemetryMetric, TrackEvent
from app.models.survey import AiEvent, EvidenceItem, SurveyCaptureBatch, SurveyReport, SurveyTask


def _event_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]
    return f"{prefix}-{digest}"


def _as_utc(value: datetime | str | None) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return datetime.now(UTC)


class EventCenter:
    """Own event materialization, aggregation, detail and technical review."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        quality_gap_threshold_sec: float = 5.0,
        materialize_on_list: bool = True,
    ) -> None:
        self._sessions = session_factory
        self._quality_gap_threshold_sec = quality_gap_threshold_sec
        self._materialize_on_list = materialize_on_list

    async def sync_alerts(self) -> int:
        """Materialize persisted current alerts as replayable event facts."""
        async with self._sessions() as session:
            alerts = (await session.execute(select(AlertRecord))).scalars().all()
            created = 0
            for alert in alerts:
                payload = {
                    "id": alert.id,
                    "intersection_id": alert.intersection_id,
                    "alert_type": alert.alert_type,
                    "severity": alert.severity,
                    "title": alert.title,
                    "description": alert.description,
                    "status": alert.status,
                    "timestamp": alert.timestamp,
                    "track_ids": alert.track_ids or [],
                    "snapshot_url": alert.snapshot_url,
                    "video_clip_url": alert.video_clip_url,
                }
                created += await self._add_alert(session, payload, {})
            await session.commit()
            return created

    async def sync_survey_reports(self) -> int:
        """Materialize already-generated real survey reports as event facts.

        Older reports remain immutable; this only adds the same idempotent event
        projection now created inline for newly generated reports.
        """
        async with self._sessions() as session:
            reports = (
                await session.execute(select(SurveyReport).order_by(SurveyReport.created_at))
            ).scalars().all()
            created = 0
            for report in reports:
                exists = (
                    await session.execute(
                        select(AiEvent.id).where(
                            AiEvent.source_system == "uav_traffic_analyzer_ai",
                            AiEvent.source_event_id == report.id,
                        )
                    )
                ).scalar_one_or_none()
                if exists:
                    continue
                task = await session.get(SurveyTask, report.task_id)
                if task is None:
                    continue
                batch = (
                    await session.get(SurveyCaptureBatch, task.selected_batch_id)
                    if task.selected_batch_id
                    else None
                )
                evidence = (
                    await session.execute(
                        select(EvidenceItem).where(
                            EvidenceItem.task_id == task.id,
                            EvidenceItem.kind.in_([
                                "survey_report_pdf",
                                "survey_report_json",
                                "survey_report_geojson",
                            ]),
                        )
                    )
                ).scalars().all()
                evidence = [
                    item
                    for item in evidence
                    if int((item.item_metadata or {}).get("version", 0)) == report.version
                ]
                payload = {
                    **(report.payload or {}),
                    "title": f"事故测绘成果 · {task.scene_location}",
                    "description": "真实视频与遥测生成的技术测绘成果",
                    "severity": "P3",
                    "status": report.status,
                    "report_id": report.id,
                    "source_profile_id": batch.source_profile_id if batch else None,
                    "evidence_refs": [
                        {
                            "id": item.id,
                            "kind": item.kind,
                            "url": f"/api/v1/survey-evidence/{item.id}/content",
                            "sha256": item.sha256,
                        }
                        for item in evidence
                    ],
                    "delivery_blocked_reason": "survey quality thresholds are not approved",
                }
                session.add(AiEvent(
                    id=_event_id("EVT", f"survey:{report.id}"),
                    source_event_id=report.id,
                    idempotency_key=f"survey-report:{report.id}",
                    event_type="survey_result",
                    task_id=task.id,
                    review_status="technical_reviewed",
                    occurred_at=report.created_at,
                    inter_id=task.inter_id,
                    road_data_version=task.road_data_version,
                    quality_status=task.quality_status,
                    payload_hash=report.content_hash,
                    delivery_status="blocked",
                    payload=payload,
                ))
                created += 1
            await session.commit()
            return created

    async def record_alert(self, alert: dict, context: dict | None = None) -> dict:
        async with self._sessions() as session:
            await self._add_alert(session, alert, context or {})
            await session.commit()
            row = (
                await session.execute(
                    select(AiEvent).where(
                        AiEvent.source_system == "uav_traffic_analyzer_ai",
                        AiEvent.source_event_id == alert["id"],
                    )
                )
            ).scalar_one()
            return self._ai_dict(row)

    async def _add_alert(self, session: AsyncSession, alert: dict, context: dict) -> int:
        exists = (
            await session.execute(
                select(AiEvent.id).where(
                    AiEvent.source_system == "uav_traffic_analyzer_ai",
                    AiEvent.source_event_id == alert["id"],
                )
            )
        ).scalar_one_or_none()
        if exists:
            return 0
        occurred_at = _as_utc(alert.get("timestamp"))
        event_type = str(alert.get("alert_type") or "alert")
        payload = {
            **alert,
            "event_type": event_type,
            "mission_id": context.get("mission_id"),
            "pipeline_id": context.get("pipeline_id") or context.get("run_id"),
            "source_profile_id": context.get("source_profile_id"),
            "road_context_status": context.get("road_context_status", "missing"),
            "time_quality": context.get("time_quality", "ingest_only"),
            "metrics": {
                key: context.get(key)
                for key in (
                    "congestion_index", "queue_length_m", "avg_speed_kmh",
                    "expected_samples", "actual_samples", "dropped_samples",
                    "coverage_ratio", "drop_reason", "event_rule",
                )
                if context.get(key) is not None
            },
            "evidence_refs": context.get("evidence_refs") or [],
        }
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()
        source_id = str(alert["id"])
        session.add(AiEvent(
            id=_event_id("EVT", f"alert:{source_id}"),
            source_event_id=source_id,
            idempotency_key=f"alert:{source_id}",
            event_type=event_type,
            review_status="pending",
            occurred_at=occurred_at,
            inter_id=context.get("inter_id") or alert.get("intersection_id"),
            road_data_version=context.get("road_data_version"),
            quality_status=context.get("quality_status", "unverified"),
            payload_hash=hashlib.sha256(canonical).hexdigest(),
            delivery_status="not_queued",
            payload=payload,
        ))
        return 1

    async def materialize_quality_events(self) -> int:
        """Create real quality-gap events from measured telemetry time gaps."""
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(TelemetryMetric)
                    .where(TelemetryMetric.source_profile_id.is_not(None))
                    .order_by(
                        TelemetryMetric.source_profile_id,
                        TelemetryMetric.mission_id,
                        TelemetryMetric.observed_at,
                    )
                )
            ).scalars().all()
            groups: dict[tuple[str, str | None], list[TelemetryMetric]] = defaultdict(list)
            for row in rows:
                groups[(str(row.source_profile_id), row.mission_id)].append(row)
            created = 0
            for (source_profile_id, mission_id), samples in groups.items():
                largest: tuple[float, TelemetryMetric, TelemetryMetric] | None = None
                for previous, current in zip(samples, samples[1:]):
                    gap = (current.observed_at - previous.observed_at).total_seconds()
                    if largest is None or gap > largest[0]:
                        largest = (gap, previous, current)
                if largest is None or largest[0] < self._quality_gap_threshold_sec:
                    continue
                gap, previous, current = largest
                source_event_id = hashlib.sha256(
                    f"quality-gap:{source_profile_id}:{mission_id}:{previous.observed_at.isoformat()}:{current.observed_at.isoformat()}".encode()
                ).hexdigest()[:40]
                exists = (
                    await session.execute(
                        select(AiEvent.id).where(AiEvent.source_event_id == source_event_id)
                    )
                ).scalar_one_or_none()
                if exists:
                    continue
                raw = current.payload.get("data", current.payload) if current.payload else {}
                payload = {
                    "event_type": "quality_degradation",
                    "title": f"遥测连续性下降（缺口 {gap:.1f}s）",
                    "description": "基于相邻源时间样本实测，不是模拟告警",
                    "severity": "P3",
                    "status": "open",
                    "mission_id": mission_id,
                    "pipeline_id": current.pipeline_id,
                    "source_profile_id": source_profile_id,
                    "gap_start": previous.observed_at.isoformat(),
                    "gap_end": current.observed_at.isoformat(),
                    "gap_sec": round(gap, 3),
                    "sample_count": len(samples),
                    "rule": {
                        "rule_id": "telemetry.continuity.v1",
                        "threshold_sec": self._quality_gap_threshold_sec,
                    },
                    "time_quality": current.time_quality,
                    "road_context_status": current.road_context_status,
                    "evidence_refs": raw.get("evidence_refs") or [],
                }
                canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
                session.add(AiEvent(
                    id=_event_id("EVT", source_event_id),
                    source_event_id=source_event_id,
                    idempotency_key=f"quality:{source_event_id}",
                    event_type="quality_degradation",
                    review_status="pending",
                    occurred_at=current.observed_at,
                    inter_id=current.intersection_id,
                    road_data_version=raw.get("road_data_version"),
                    quality_status="unverified",
                    payload_hash=hashlib.sha256(canonical).hexdigest(),
                    delivery_status="not_queued",
                    payload=payload,
                ))
                created += 1
            await session.commit()
            return created

    async def list_events(
        self,
        *,
        event_type: str | None = None,
        inter_id: str | None = None,
        source_profile_id: str | None = None,
        mission_id: str | None = None,
        review_status: str | None = None,
        limit: int = 150,
    ) -> list[dict]:
        if self._materialize_on_list:
            await self.materialize_quality_events()
        async with self._sessions() as session:
            ai_rows = (
                await session.execute(select(AiEvent).order_by(AiEvent.occurred_at.desc()).limit(limit * 2))
            ).scalars().all()
            conflict_rows = (
                await session.execute(
                    select(ConflictEvent).order_by(ConflictEvent.occurred_at.desc()).limit(limit * 2)
                )
            ).scalars().all()
            reviews: dict[str, ConflictReview] = {}
            if conflict_rows:
                review_rows = (
                    await session.execute(
                        select(ConflictReview).where(
                            ConflictReview.event_id.in_([row.id for row in conflict_rows])
                        )
                    )
                ).scalars().all()
                reviews = {row.event_id: row for row in review_rows}
            events = [self._ai_dict(row) for row in ai_rows]
            events.extend(self._conflict_dict(row, reviews.get(row.id)) for row in conflict_rows)
        if event_type:
            events = [item for item in events if item["event_type"] == event_type]
        if inter_id:
            events = [item for item in events if item.get("inter_id") == inter_id]
        if source_profile_id:
            events = [item for item in events if item.get("source_profile_id") == source_profile_id]
        if mission_id:
            events = [item for item in events if item.get("mission_id") == mission_id]
        if review_status:
            events = [item for item in events if item.get("review_status") == review_status]
        events.sort(key=lambda item: item.get("occurred_at") or "", reverse=True)
        return events[:limit]

    async def get_event(self, event_id: str) -> dict:
        async with self._sessions() as session:
            ai = await session.get(AiEvent, event_id)
            if ai is not None:
                result = self._ai_dict(ai)
            else:
                conflict = (
                    await session.execute(
                        select(ConflictEvent)
                        .where(ConflictEvent.id == event_id)
                        .order_by(ConflictEvent.occurred_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if conflict is None:
                    raise LookupError("event not found")
                review = (
                    await session.execute(
                        select(ConflictReview).where(ConflictReview.event_id == event_id)
                    )
                ).scalar_one_or_none()
                result = self._conflict_dict(conflict, review)
            result["related_tracks"] = await self._related_tracks(session, result)
            return result

    async def review_ai_event(
        self,
        event_id: str,
        review_status: str,
        expected_revision: int,
        reviewed_by: int | None,
        reason: str | None,
    ) -> dict:
        if review_status not in {"confirmed", "rejected"}:
            raise ValueError("review_status must be confirmed or rejected")
        async with self._sessions() as session:
            async with session.begin():
                row = await session.get(AiEvent, event_id, with_for_update=True)
                if row is None:
                    raise LookupError("AI event not found")
                if row.review_revision != expected_revision:
                    raise RuntimeError("event review revision mismatch")
                row.review_status = review_status
                row.review_revision += 1
                row.reviewed_by = reviewed_by
                row.reviewed_at = datetime.now(UTC)
                row.review_reason = reason
            return self._ai_dict(row)

    async def _related_tracks(self, session: AsyncSession, event: dict) -> list[dict]:
        occurred_at = _as_utc(event.get("occurred_at"))
        statement = select(TrackEvent)
        if event.get("mission_id"):
            statement = statement.where(TrackEvent.mission_id == event["mission_id"])
        else:
            statement = statement.where(
                TrackEvent.inter_id == event.get("inter_id"),
                TrackEvent.ended_at >= occurred_at - timedelta(seconds=60),
                TrackEvent.ended_at <= occurred_at + timedelta(seconds=60),
            )
        rows = (
            await session.execute(statement.order_by(TrackEvent.ended_at.desc()).limit(50))
        ).scalars().all()
        return [
            dict(
                row.payload.get("data", row.payload),
                id=row.id,
                mission_id=row.mission_id,
                pipeline_id=row.pipeline_id,
                source_profile_id=row.source_profile_id,
                ended_at=row.ended_at.isoformat(),
            )
            for row in rows
        ]

    @staticmethod
    def _ai_dict(row: AiEvent) -> dict[str, Any]:
        payload = row.payload or {}
        return {
            "id": row.id,
            "source_kind": "ai_event",
            "event_type": row.event_type,
            "title": payload.get("title") or row.event_type,
            "description": payload.get("description"),
            "severity": payload.get("severity", "P3"),
            "status": payload.get("status", row.delivery_status),
            "occurred_at": row.occurred_at.isoformat() if row.occurred_at else row.created_at.isoformat(),
            "inter_id": row.inter_id,
            "road_data_version": row.road_data_version,
            "quality_status": row.quality_status,
            "mission_id": payload.get("mission_id") or (payload.get("task") or {}).get("mission_id"),
            "pipeline_id": payload.get("pipeline_id"),
            "source_profile_id": payload.get("source_profile_id"),
            "review_status": row.review_status,
            "review_revision": row.review_revision,
            "review_reason": row.review_reason,
            "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
            "delivery_status": row.delivery_status,
            "evidence_refs": payload.get("evidence_refs") or [],
            "payload": payload,
        }

    @staticmethod
    def _conflict_dict(row: ConflictEvent, review: ConflictReview | None) -> dict[str, Any]:
        payload = row.payload.get("data", row.payload) if row.payload else {}
        return {
            "id": row.id,
            "source_kind": "conflict",
            "event_type": "conflict",
            "title": "真实机非冲突",
            "description": payload.get("conflict_scene"),
            "severity": row.severity or "P2",
            "status": "open",
            "occurred_at": row.occurred_at.isoformat(),
            "inter_id": row.inter_id,
            "road_data_version": row.road_data_version,
            "quality_status": row.quality_status,
            "mission_id": row.mission_id,
            "pipeline_id": row.pipeline_id,
            "source_profile_id": row.source_profile_id,
            "review_status": review.review_status if review else "pending",
            "review_revision": review.revision if review else 1,
            "review_reason": review.review_reason if review else None,
            "reviewed_at": review.reviewed_at.isoformat() if review else None,
            "evidence_refs": payload.get("evidence_refs") or [],
            "payload": payload,
        }
