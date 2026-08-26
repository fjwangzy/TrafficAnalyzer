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

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.alert import AlertRecord
from app.models.metrics import ConflictEvent, ConflictReview, TelemetryMetric, TrackEvent
from app.models.replay_v2 import (
    ReplayV2ConflictEvent,
    ReplayV2MessageInbox,
    ReplayV2Mission,
)
from app.models.survey import (
    AiEvent,
    EvidenceItem,
    EvidencePackage,
    SurveyCaptureBatch,
    SurveyReport,
    SurveyTask,
)


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
        materialize_on_list: bool = False,
    ) -> None:
        self._sessions = session_factory
        self._quality_gap_threshold_sec = quality_gap_threshold_sec
        # Event listing is a read path.  Quality-gap materialization scans source
        # telemetry and writes AiEvent rows, so callers that need that maintenance
        # work must invoke ``materialize_quality_events`` outside an HTTP list
        # request.  Keeping the opt-in switch preserves the explicit maintenance
        # hook for batch jobs without making the UI latency data-volume dependent.
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
            ai_rows = []
            if event_type != "conflict":
                ai_statement = select(AiEvent)
                if event_type:
                    ai_statement = ai_statement.where(AiEvent.event_type == event_type)
                if inter_id:
                    ai_statement = ai_statement.where(AiEvent.inter_id == inter_id)
                if review_status:
                    ai_statement = ai_statement.where(AiEvent.review_status == review_status)
                ai_rows = (
                    await session.execute(
                        ai_statement.order_by(AiEvent.occurred_at.desc()).limit(limit * 2)
                    )
                ).scalars().all()
            conflict_rows = []
            if event_type in {None, "conflict"}:
                conflict_statement = select(ConflictEvent)
                if inter_id:
                    conflict_statement = conflict_statement.where(ConflictEvent.inter_id == inter_id)
                if source_profile_id:
                    conflict_statement = conflict_statement.where(
                        ConflictEvent.source_profile_id == source_profile_id
                    )
                if mission_id:
                    conflict_statement = conflict_statement.where(ConflictEvent.mission_id == mission_id)
                conflict_rows = (
                    await session.execute(
                        conflict_statement.order_by(ConflictEvent.occurred_at.desc()).limit(limit * 2)
                    )
                ).scalars().all()
            replay_rows = []
            if event_type in {None, "conflict"}:
                replay_statement = (
                    select(ReplayV2ConflictEvent, ReplayV2Mission)
                    .join(
                        ReplayV2Mission,
                        ReplayV2Mission.id == ReplayV2ConflictEvent.mission_id,
                    )
                )
                if inter_id:
                    replay_statement = replay_statement.where(
                        ReplayV2ConflictEvent.inter_id == inter_id
                    )
                if source_profile_id:
                    replay_statement = replay_statement.where(
                        ReplayV2Mission.source_profile_id == source_profile_id
                    )
                if mission_id:
                    replay_statement = replay_statement.where(
                        ReplayV2ConflictEvent.mission_id == mission_id
                    )
                replay_rows = (
                    await session.execute(
                        replay_statement.order_by(
                            ReplayV2Mission.created_at.desc(),
                            ReplayV2ConflictEvent.offset_ms.desc(),
                        ).limit(limit * 2)
                    )
                ).all()
            replay_evidence = await self._replay_conflict_evidence_refs(
                session,
                [conflict.id for conflict, _mission in replay_rows],
            )
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
            events = []
            for row in ai_rows:
                evidence_refs, related_event_ids = await self._ai_event_evidence(
                    session, row
                )
                events.append(
                    self._ai_dict(row, evidence_refs, related_event_ids)
                )
            events.extend(self._conflict_dict(row, reviews.get(row.id)) for row in conflict_rows)
            events.extend(
                self._replay_conflict_dict(
                    conflict,
                    mission,
                    replay_evidence.get(conflict.id, []),
                )
                for conflict, mission in replay_rows
            )
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
        deduplicated = []
        seen_ids: set[str] = set()
        for item in events:
            event_id = str(item.get("id") or "")
            if not event_id or event_id in seen_ids:
                continue
            seen_ids.add(event_id)
            deduplicated.append(item)
        return deduplicated[:limit]

    async def get_event(self, event_id: str) -> dict:
        async with self._sessions() as session:
            ai = await session.get(AiEvent, event_id)
            if ai is not None:
                evidence_refs, related_event_ids = await self._ai_event_evidence(
                    session, ai
                )
                result = self._ai_dict(ai, evidence_refs, related_event_ids)
            else:
                conflict = (
                    await session.execute(
                        select(ConflictEvent)
                        .where(or_(
                            ConflictEvent.id == event_id,
                            ConflictEvent.source_message_id == event_id,
                        ))
                        .order_by(ConflictEvent.occurred_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if conflict is None:
                    replay_pair = (
                        await session.execute(
                            select(ReplayV2ConflictEvent, ReplayV2Mission)
                            .join(
                                ReplayV2Mission,
                                ReplayV2Mission.id == ReplayV2ConflictEvent.mission_id,
                            )
                            .where(ReplayV2ConflictEvent.id == event_id)
                            .limit(1)
                        )
                    ).one_or_none()
                    if replay_pair is None:
                        raise LookupError("event not found")
                    replay_evidence = await self._replay_conflict_evidence_refs(
                        session, [event_id]
                    )
                    result = self._replay_conflict_dict(
                        *replay_pair,
                        replay_evidence.get(event_id, []),
                    )
                else:
                    review = (
                        await session.execute(
                            select(ConflictReview).where(ConflictReview.event_id == conflict.id)
                        )
                    ).scalar_one_or_none()
                    result = self._conflict_dict(conflict, review)
            if result.get("source_kind") == "replay_v2_conflict":
                result["related_tracks"] = []
                result["context_tracks"] = []
            else:
                related_tracks, context_tracks = await self._related_tracks(
                    session, result
                )
                result["related_tracks"] = related_tracks
                result["context_tracks"] = context_tracks
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

    async def _related_tracks(
        self, session: AsyncSession, event: dict
    ) -> tuple[list[dict], list[dict]]:
        occurred_at = _as_utc(event.get("occurred_at"))
        base_statement = select(TrackEvent)
        if event.get("mission_id"):
            base_statement = base_statement.where(
                TrackEvent.mission_id == event["mission_id"]
            )
        else:
            base_statement = base_statement.where(
                TrackEvent.inter_id == event.get("inter_id"),
                TrackEvent.ended_at >= occurred_at - timedelta(seconds=60),
                TrackEvent.ended_at <= occurred_at + timedelta(seconds=60),
            )

        payload = event.get("payload") or {}
        participant_ids = [
            str(track_id)
            for track_id in (payload.get("motor_id"), payload.get("non_motor_id"))
            if track_id is not None
        ]

        def serialize(row) -> dict:
            data = dict(row.payload.get("data", row.payload))
            data.setdefault("track_id", row.track_id)
            return dict(
                data,
                id=row.id,
                mission_id=row.mission_id,
                pipeline_id=row.pipeline_id,
                source_profile_id=row.source_profile_id,
                ended_at=row.ended_at.isoformat(),
            )

        if not participant_ids:
            rows = (
                await session.execute(
                    base_statement.order_by(TrackEvent.ended_at.desc()).limit(50)
                )
            ).scalars().all()
            return [serialize(row) for row in rows], []

        participant_rows = (
            await session.execute(
                base_statement.where(TrackEvent.track_id.in_(participant_ids)).order_by(
                    TrackEvent.ended_at.desc()
                )
            )
        ).scalars().all()
        participant_order = {track_id: index for index, track_id in enumerate(participant_ids)}
        participant_rows = sorted(
            participant_rows,
            key=lambda row: participant_order.get(str(row.track_id), len(participant_order)),
        )
        context_rows = (
            await session.execute(
                base_statement.where(TrackEvent.track_id.not_in(participant_ids))
                .order_by(TrackEvent.ended_at.desc())
                .limit(50)
            )
        ).scalars().all()
        return (
            [serialize(row) for row in participant_rows],
            [serialize(row) for row in context_rows],
        )

    async def _ai_event_evidence(
        self,
        session: AsyncSession,
        row: AiEvent,
    ) -> tuple[list[dict] | None, list[str]]:
        """Resolve evidence that belongs to an aggregate alert's exact window.

        The alert row predates explicit child-event IDs.  The durable Replay V2
        inbox still records the fact IDs and receipt times used by the one-minute
        alert rule, so use that relation instead of guessing from image names.
        """
        if row.event_type != "multiple_conflicts":
            return None, []
        occurred_at = _as_utc(row.occurred_at)
        window_start = occurred_at - timedelta(seconds=60)
        inbox_rows = (
            await session.execute(
                select(ReplayV2MessageInbox)
                .where(
                    ReplayV2MessageInbox.msg_type == "uav_conflict",
                    ReplayV2MessageInbox.received_at >= window_start,
                    ReplayV2MessageInbox.received_at <= occurred_at,
                )
                .order_by(ReplayV2MessageInbox.received_at)
            )
        ).scalars().all()
        prefix = "uav_replay_v2_conflict_events:"
        ordered_ids: list[str] = []
        for inbox in inbox_rows:
            received_at = _as_utc(inbox.received_at)
            if received_at < window_start or received_at > occurred_at:
                continue
            for reference in inbox.fact_refs or []:
                if not isinstance(reference, str) or not reference.startswith(prefix):
                    continue
                event_id = reference.removeprefix(prefix)
                if event_id and event_id not in ordered_ids:
                    ordered_ids.append(event_id)
        if not ordered_ids:
            return [], []
        conflict_rows = (
            await session.execute(
                select(ReplayV2ConflictEvent).where(
                    ReplayV2ConflictEvent.id.in_(ordered_ids),
                    ReplayV2ConflictEvent.inter_id == row.inter_id,
                )
            )
        ).scalars().all()
        matching_ids = {str(conflict.id) for conflict in conflict_rows}
        related_event_ids = [event_id for event_id in ordered_ids if event_id in matching_ids]
        evidence_by_event = await self._replay_conflict_evidence_refs(
            session, related_event_ids
        )
        references = []
        for event_id in related_event_ids:
            references.extend(
                {**reference, "related_event_id": event_id}
                for reference in evidence_by_event.get(event_id, [])
            )
        return references, related_event_ids

    @staticmethod
    def _ai_dict(
        row: AiEvent,
        evidence_refs: list[dict] | None = None,
        related_event_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        payload = dict(row.payload or {})
        if evidence_refs is not None:
            payload["evidence_refs"] = evidence_refs
        if related_event_ids:
            payload["related_event_ids"] = related_event_ids
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
            "related_event_ids": payload.get("related_event_ids") or [],
            "payload": payload,
        }

    @staticmethod
    def _conflict_dict(row: ConflictEvent, review: ConflictReview | None) -> dict[str, Any]:
        payload = row.payload.get("data", row.payload) if row.payload else {}
        review_status = review.review_status if review else "pending"
        title = {
            "confirmed": "已确认机非冲突",
            "rejected": "已驳回冲突候选",
        }.get(review_status, "待复核冲突候选")
        return {
            "id": row.id,
            "source_kind": "conflict",
            "event_type": "conflict",
            # Algorithm output is a review candidate.  Only an explicit human
            # confirmation may promote the user-facing title to a confirmed fact.
            "title": title,
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
            "review_status": review_status,
            "review_revision": review.revision if review else 1,
            "review_reason": review.review_reason if review else None,
            "reviewed_at": review.reviewed_at.isoformat() if review else None,
            "evidence_refs": payload.get("evidence_refs") or [],
            "payload": payload,
        }

    @staticmethod
    async def _replay_conflict_evidence_refs(
        session: AsyncSession,
        event_ids: list[str],
    ) -> dict[str, list[dict]]:
        if not event_ids:
            return {}
        rows = (
            await session.execute(
                select(EvidenceItem, EvidencePackage.owner_id)
                .join(
                    EvidencePackage,
                    EvidencePackage.id == EvidenceItem.package_id,
                )
                .where(
                    EvidencePackage.owner_type == "replay_v2_conflict",
                    EvidencePackage.owner_id.in_(event_ids),
                )
            )
        ).all()
        result: dict[str, list[dict]] = {}
        kind_order = {
            "conflict_original_frame": 0,
            "conflict_detector_frame": 1,
        }
        for item, owner_id in rows:
            result.setdefault(str(owner_id), []).append({
                "id": item.id,
                "kind": item.kind,
                "url": f"/api/v1/survey-evidence/{item.id}/content",
                "sha256": item.sha256,
            })
        for references in result.values():
            references.sort(key=lambda item: kind_order.get(item["kind"], 99))
        return result

    @staticmethod
    def _replay_conflict_dict(
        row: ReplayV2ConflictEvent,
        mission: ReplayV2Mission,
        evidence_refs: list[dict] | None = None,
    ) -> dict[str, Any]:
        anchor = mission.started_at or mission.created_at
        occurred_at = _as_utc(anchor) + timedelta(milliseconds=row.offset_ms)
        motor_id = str(row.motor_track_id) if row.motor_track_id is not None else None
        non_motor_id = (
            str(row.non_motor_track_id) if row.non_motor_track_id is not None else None
        )
        pair_label = (
            f" · 轨迹 {motor_id} 与 {non_motor_id}"
            if motor_id is not None and non_motor_id is not None
            else ""
        )
        algorithm_versions = dict(getattr(mission, "algorithm_versions", None) or {})
        historical_replay = row.prediction_type == "historical_detector_output"
        time_quality = (
            "reconstructed"
            if algorithm_versions.get("source_time_semantics") == "reconstructed"
            else "verified"
        )
        payload = {
            "offset_ms": row.offset_ms,
            "prediction_type": row.prediction_type,
            "motor_id": motor_id,
            "non_motor_id": non_motor_id,
            "distance_m": row.distance_m,
            "conflict_scene": row.conflict_scene,
            "ttc_sec": row.ttc_sec,
            "pet_sec": row.pet_sec,
            "evidence": row.evidence or [],
            "evidence_status": "complete" if evidence_refs else "incomplete",
            "time_quality": time_quality,
            "historical_replay": historical_replay,
            "algorithm_versions": algorithm_versions,
        }
        if (
            not evidence_refs
            and row.offset_ms == 0
            and motor_id is None
            and non_motor_id is None
        ):
            payload["evidence_error"] = "historical_managed_evidence_unavailable"
        return {
            "id": row.id,
            "source_kind": "replay_v2_conflict",
            "fact_table": "uav_replay_v2_conflict_events",
            "event_type": "conflict",
            "title": (
                f"历史检测口径复现 · 冲突候选{pair_label}"
                if historical_replay
                else f"只读冲突候选{pair_label}"
            ),
            "description": (
                "同一源帧经历史检测器版本重新运行并复现；不代表当前生产口径检出"
                if historical_replay
                else row.conflict_scene
            ),
            "severity": row.severity or "warning",
            "status": "open",
            "occurred_at": occurred_at.isoformat(),
            "inter_id": row.inter_id,
            "road_data_version": None,
            "quality_status": (
                "historical_reconstructed" if historical_replay else "estimated"
            ),
            "mission_id": row.mission_id,
            "pipeline_id": mission.pipeline_id,
            "source_profile_id": mission.source_profile_id,
            "review_status": "pending",
            "review_revision": 1,
            "review_reason": None,
            "reviewed_at": None,
            "review_supported": False,
            "delivery_status": "not_queued",
            "evidence_refs": evidence_refs or [],
            "payload": payload,
        }
