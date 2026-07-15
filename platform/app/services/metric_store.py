"""Deep persistence module for canonical UAV metric messages.

`MetricStore.persist` is the only Kafka-to-database write interface.  It hides
legacy-envelope adaptation, identity validation, inbox idempotency, fact
expansion and the single-transaction boundary required by ADR-019.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.metrics import (
    ConflictEvent,
    ConflictReview,
    SystemMetric,
    TelemetryMetric,
    TrackEvent,
    TrackPoint,
    TrafficMetric,
)
from app.models.mission import MessageDeadLetter, MessageInbox


SOURCE_SYSTEM = "uav_traffic_analyzer_ai"
CANONICAL_TYPES = {
    "uav_stats",
    "uav_track_complete",
    "uav_conflict",
    "uav_telemetry",
    "uav_system_metrics",
}
LEGACY_TYPES = {
    "stats": "uav_stats",
    "track_complete": "uav_track_complete",
    "conflict": "uav_conflict",
    "telemetry": "uav_telemetry",
    "system_metrics": "uav_system_metrics",
}


class MetricContractError(ValueError):
    """Message does not satisfy the frozen canonical/legacy adapter contract."""


class MessageIdentityConflict(MetricContractError):
    """A stable message ID was replayed with different content."""


@dataclass(frozen=True)
class MessageEnvelope:
    payload: dict[str, Any]
    topic: str
    partition: int
    offset: int


@dataclass(frozen=True)
class PersistResult:
    duplicate: bool
    message_id: str
    msg_type: str
    normalized_payload: dict[str, Any]
    fact_references: tuple[str, ...]


class MetricStorePort(Protocol):
    async def persist(self, envelope: MessageEnvelope) -> PersistResult: ...

    async def quarantine(self, envelope: MessageEnvelope, error: MetricContractError) -> str: ...


def _json_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _float(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)) and value >= 946684800:
        return datetime.fromtimestamp(float(value), UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


def _period_start(period: str) -> datetime:
    match = re.fullmatch(r"(\d+)([smhd])", period)
    if not match:
        raise MetricContractError("period must match <number><s|m|h|d>")
    value = int(match.group(1))
    unit = match.group(2)
    delta = {
        "s": timedelta(seconds=value),
        "m": timedelta(minutes=value),
        "h": timedelta(hours=value),
        "d": timedelta(days=value),
    }[unit]
    return datetime.now(UTC) - delta


class PostgresMetricStoreAdapter:
    """PostgreSQL/TimescaleDB adapter behind the MetricStore port."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._sessions = session_factory

    async def quarantine(self, envelope: MessageEnvelope, error: MetricContractError) -> str:
        """Persist a poison record idempotently before its offset is advanced."""
        payload_hash = _json_hash(envelope.payload)
        raw_message_id = envelope.payload.get("message_id")
        source_system = str(envelope.payload.get("source_system") or SOURCE_SYSTEM)
        dead_letter_id = hashlib.sha256(
            f"{envelope.topic}:{envelope.partition}:{envelope.offset}".encode("utf-8")
        ).hexdigest()[:40]
        now = datetime.now(UTC)
        statement = pg_insert(MessageDeadLetter).values(
            id=dead_letter_id,
            source_system=source_system,
            message_id=str(raw_message_id) if raw_message_id is not None else None,
            topic=envelope.topic,
            partition=envelope.partition,
            offset=envelope.offset,
            payload_hash=payload_hash,
            reason_code=type(error).__name__,
            reason_summary=str(error)[:2000],
            payload=_json_safe(envelope.payload),
            status="quarantined",
            occurrence_count=1,
            first_seen_at=now,
            last_seen_at=now,
        ).on_conflict_do_update(
            constraint="uq_uav_message_dlq_transport",
            set_={
                "payload_hash": payload_hash,
                "reason_code": type(error).__name__,
                "reason_summary": str(error)[:2000],
                "payload": _json_safe(envelope.payload),
                "last_seen_at": now,
                "occurrence_count": MessageDeadLetter.occurrence_count + 1,
            },
        )
        async with self._sessions() as session:
            async with session.begin():
                await session.execute(statement)
        return dead_letter_id

    async def persist(self, envelope: MessageEnvelope) -> PersistResult:
        normalized = self._normalize(envelope)
        payload_hash = _json_hash(envelope.payload)
        try:
            return await self._persist_once(envelope, normalized, payload_hash)
        except IntegrityError:
            # A second instance may win the unique-key race.  Re-read the inbox
            # and return its durable result only when identity and hash agree.
            async with self._sessions() as session:
                inbox = await self._find_inbox(session, normalized["source_system"], normalized["message_id"])
                if inbox and inbox.payload_hash == payload_hash:
                    return PersistResult(
                        True,
                        inbox.message_id,
                        normalized["msg_type"],
                        normalized,
                        tuple(inbox.fact_references or ()),
                    )
            raise

    async def _persist_once(
        self, envelope: MessageEnvelope, normalized: dict[str, Any], payload_hash: str
    ) -> PersistResult:
        async with self._sessions() as session:
            async with session.begin():
                inbox = await self._find_inbox(
                    session, normalized["source_system"], normalized["message_id"], for_update=True
                )
                if inbox:
                    if inbox.payload_hash != payload_hash:
                        raise MessageIdentityConflict(
                            f"message_id {normalized['message_id']} was replayed with a different payload"
                        )
                    return PersistResult(
                        True,
                        inbox.message_id,
                        normalized["msg_type"],
                        normalized,
                        tuple(inbox.fact_references or ()),
                    )

                inbox = MessageInbox(
                    id=normalized["message_id"][:80],
                    source_system=normalized["source_system"],
                    message_id=normalized["message_id"],
                    topic=envelope.topic,
                    partition=envelope.partition,
                    offset=envelope.offset,
                    payload_hash=payload_hash,
                    status="processing",
                    fact_references=[],
                )
                session.add(inbox)
                references = self._add_facts(session, envelope, normalized)
                inbox.status = "processed"
                inbox.fact_references = references
                inbox.processed_at = datetime.now(UTC)
            return PersistResult(
                False,
                normalized["message_id"],
                normalized["msg_type"],
                normalized,
                tuple(references),
            )

    @staticmethod
    async def _find_inbox(
        session: AsyncSession, source_system: str, message_id: str, for_update: bool = False
    ) -> MessageInbox | None:
        statement = select(MessageInbox).where(
            MessageInbox.source_system == source_system,
            MessageInbox.message_id == message_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return (await session.execute(statement)).scalar_one_or_none()

    def _normalize(self, envelope: MessageEnvelope) -> dict[str, Any]:
        raw = envelope.payload
        raw_type = str(raw.get("msg_type") or "stats")
        is_canonical = raw_type in CANONICAL_TYPES
        if is_canonical:
            source_system = raw.get("source_system")
            message_id = raw.get("message_id")
            schema_version = raw.get("schema_version")
            occurred_at = _parse_datetime(raw.get("occurred_at"))
            if source_system != SOURCE_SYSTEM:
                raise MetricContractError("canonical source_system is invalid")
            if not message_id or schema_version != f"{raw_type}/v1" or not occurred_at:
                raise MetricContractError("canonical message_id/schema_version/occurred_at is invalid")
            data = raw.get("data")
            if not isinstance(data, dict):
                raise MetricContractError("canonical data must be an object")
            produced_at = _parse_datetime(raw.get("produced_at"))
            if not produced_at:
                raise MetricContractError("canonical produced_at is invalid")
            time_quality = str(raw.get("time_quality") or "verified")
            source_time_semantics = str(raw.get("source_time_semantics") or "event_time")
        else:
            canonical_type = LEGACY_TYPES.get(raw_type)
            if not canonical_type:
                raise MetricContractError(f"unsupported msg_type: {raw_type}")
            raw_type = canonical_type
            source_system = SOURCE_SYSTEM
            transport_id = f"{envelope.topic}:{envelope.partition}:{envelope.offset}"
            message_id = str(raw.get("message_id") or f"legacy:{transport_id}:{_json_hash(raw)[:16]}")
            schema_version = f"{raw_type}/v1"
            data = dict(raw)
            source_value = raw.get("occurred_at", raw.get("timestamp", raw.get("timestamp_last")))
            occurred_at = _parse_datetime(source_value)
            if occurred_at:
                time_quality = "verified"
                source_time_semantics = "event_time"
            else:
                occurred_at = datetime.now(UTC)
                time_quality = "ingest_only"
                source_time_semantics = "consumer_time"
            produced_at = occurred_at

        normalized = {
            **raw,
            "message_id": str(message_id),
            "msg_type": raw_type,
            "schema_version": schema_version,
            "source_system": source_system,
            "occurred_at": occurred_at,
            "produced_at": produced_at,
            "data": data,
            "camera_id": raw.get("camera_id", data.get("camera_id")),
            "drone_id": raw.get("drone_id", data.get("drone_id")),
            "intersection_id": raw.get("intersection_id", data.get("intersection_id")),
            "inter_id": raw.get("inter_id", data.get("inter_id")),
            "road_data_version": raw.get("road_data_version", data.get("road_data_version")),
            "road_context_status": raw.get("road_context_status", data.get("road_context_status", "missing")),
            "source_time_raw": raw.get("source_time_raw") or ({"value": source_value} if not is_canonical else None),
            "source_time_semantics": source_time_semantics,
            "time_quality": time_quality,
            "quality_status": str(raw.get("quality_status", data.get("quality_status", "unverified"))),
        }
        normalized["intersection_id"] = normalized["intersection_id"] or normalized["inter_id"]
        return normalized

    def _common(self, envelope: MessageEnvelope, value: dict[str, Any]) -> dict[str, Any]:
        return {
            "source_system": value["source_system"],
            "source_message_id": value["message_id"],
            "msg_type": value["msg_type"],
            "schema_version": value["schema_version"],
            "produced_at": value["produced_at"],
            "topic": envelope.topic,
            "partition": envelope.partition,
            "offset": envelope.offset,
            "camera_id": str(value["camera_id"]) if value.get("camera_id") is not None else None,
            "drone_id": str(value["drone_id"]) if value.get("drone_id") is not None else None,
            "intersection_id": value.get("intersection_id"),
            "road_context_status": value["road_context_status"],
            "source_time_raw": value.get("source_time_raw"),
            "source_time_semantics": value["source_time_semantics"],
            "time_quality": value["time_quality"],
            "quality_status": value["quality_status"],
            "payload": _json_safe(value),
        }

    def _add_facts(
        self, session: AsyncSession, envelope: MessageEnvelope, value: dict[str, Any]
    ) -> list[str]:
        handlers = {
            "uav_stats": self._add_stats,
            "uav_track_complete": self._add_track,
            "uav_conflict": self._add_conflict,
            "uav_telemetry": self._add_telemetry,
            "uav_system_metrics": self._add_system_metrics,
        }
        return handlers[value["msg_type"]](session, envelope, value)

    def _add_stats(self, session: AsyncSession, envelope: MessageEnvelope, value: dict[str, Any]) -> list[str]:
        data = value["data"]
        common = self._common(envelope, value)
        observed_at = value["occurred_at"]
        inter_id = value.get("inter_id") or value.get("intersection_id") or "unmatched"
        rows: list[tuple[str, str, dict[str, Any]]] = [("intersection", str(inter_id), data)]
        roads = data.get("roads") if isinstance(data.get("roads"), list) else []
        lanes = data.get("lanes") if isinstance(data.get("lanes"), list) else []
        if not lanes and isinstance(data.get("lane_stats"), dict):
            lanes = [{"lane_id": key, **item} for key, item in data["lane_stats"].items()]
        rows.extend(("link", str(item.get("link_id", item.get("id", "unknown"))), item) for item in roads)
        rows.extend(("lane", str(item.get("lane_id", "unknown")), item) for item in lanes)
        references = []
        for index, (grain_type, grain_key, metrics) in enumerate(rows):
            fact_id = hashlib.sha256(f"{value['message_id']}:{grain_type}:{grain_key}".encode()).hexdigest()[:40]
            session.add(TrafficMetric(
                id=fact_id,
                observed_at=observed_at,
                ingested_at=datetime.now(UTC),
                inter_id=str(inter_id),
                road_data_version=value.get("road_data_version"),
                grain_type=grain_type,
                grain_key=grain_key,
                cars=_float(data.get("cars", data.get("total_vehicles"))),
                active_tracks=_int(data.get("active_tracks")),
                vehicle_count=_int(metrics.get("vehicle_count", metrics.get("count", data.get("total_vehicles")))),
                flow_veh_per_min=_float(metrics.get("flow_veh_per_min", metrics.get("activity"))),
                avg_speed_kmh=_float(metrics.get("avg_speed_kmh", data.get("avg_speed_kmh"))),
                congestion_index=_float(metrics.get("congestion_index", data.get("congestion_index"))),
                queue_length_m=_float(metrics.get("queue_length_m")),
                headway_sec=_float(metrics.get("headway_sec")),
                queue_count=_int(data.get("queue_count")),
                direction_flow=data.get("direction_flow"),
                roads=roads,
                link_id=str(metrics.get("link_id")) if metrics.get("link_id") is not None else None,
                lane_id=str(metrics.get("lane_id")) if metrics.get("lane_id") is not None else None,
                window_start=_parse_datetime(data.get("window_start")),
                window_end=_parse_datetime(data.get("window_end")),
                expected_samples=_int(data.get("expected_samples")),
                actual_samples=_int(data.get("actual_samples")),
                dropped_samples=_int(data.get("dropped_samples")),
                coverage_ratio=_float(data.get("coverage_ratio")),
                drop_reason=data.get("drop_reason"),
                **common,
            ))
            references.append(f"uav_traffic_metrics:{fact_id}:{observed_at.isoformat()}")
        return references

    def _add_track(self, session: AsyncSession, envelope: MessageEnvelope, value: dict[str, Any]) -> list[str]:
        data = value["data"]
        common = self._common(envelope, value)
        ended_at = value["occurred_at"]
        track_id = str(data.get("track_id", "unknown"))
        event_id = hashlib.sha256(f"track:{value['message_id']}".encode()).hexdigest()[:40]
        trajectory_world = data.get("trajectory_world_m") or data.get("positions_bev") or []
        trajectory_px = data.get("trajectory_px") or []
        session.add(TrackEvent(
            id=event_id,
            inter_id=str(value.get("inter_id") or value.get("intersection_id") or "unmatched"),
            road_data_version=value.get("road_data_version"),
            track_id=track_id,
            vehicle_class=data.get("vehicle_class", data.get("class_name")),
            turn_behavior=data.get("turn_behavior"),
            started_at=_parse_datetime(data.get("started_at", data.get("timestamp_first"))),
            ended_at=ended_at,
            duration_sec=_float(data.get("duration_sec")),
            avg_speed_kmh=_float(data.get("avg_speed_kmh")),
            max_speed_kmh=_float(data.get("max_speed_kmh")),
            trajectory_px=trajectory_px,
            trajectory_world_m=trajectory_world,
            entry_point_m=data.get("entry_point_m"),
            exit_point_m=data.get("exit_point_m"),
            start_link_id=data.get("start_link_id"),
            end_link_id=data.get("end_link_id"),
            start_lane_id=str(data["start_lane"]) if data.get("start_lane") is not None else data.get("start_lane_id"),
            end_lane_id=str(data["end_lane"]) if data.get("end_lane") is not None else data.get("end_lane_id"),
            world_anchor_lat_lon=data.get("world_anchor_lat_lon"),
            map_match_quality=data.get("map_match_quality"),
            **common,
        ))
        refs = [f"uav_track_events:{event_id}"]
        point_count = max(len(trajectory_world), len(trajectory_px))
        for index in range(point_count):
            world = trajectory_world[index] if index < len(trajectory_world) else None
            pixel = trajectory_px[index] if index < len(trajectory_px) else None
            point_time = _parse_datetime(world[2]) if isinstance(world, list) and len(world) > 2 else None
            point_time = point_time or ended_at
            point_id = hashlib.sha256(f"{event_id}:{index}".encode()).hexdigest()[:40]
            session.add(TrackPoint(
                id=point_id,
                observed_at=point_time,
                track_event_id=event_id,
                inter_id=str(value.get("inter_id") or value.get("intersection_id") or "unmatched"),
                track_id=track_id,
                point_seq=index,
                pixel_x=_float(pixel[0]) if isinstance(pixel, list) and len(pixel) > 1 else None,
                pixel_y=_float(pixel[1]) if isinstance(pixel, list) and len(pixel) > 1 else None,
                world_x_m=_float(world[0]) if isinstance(world, list) and len(world) > 1 else None,
                world_y_m=_float(world[1]) if isinstance(world, list) and len(world) > 1 else None,
                **common,
            ))
            refs.append(f"uav_track_points:{point_id}:{point_time.isoformat()}")
        return refs

    def _add_conflict(self, session: AsyncSession, envelope: MessageEnvelope, value: dict[str, Any]) -> list[str]:
        data = value["data"]
        common = self._common(envelope, value)
        occurred_at = value["occurred_at"]
        fact_id = hashlib.sha256(f"conflict:{value['message_id']}".encode()).hexdigest()[:40]
        session.add(ConflictEvent(
            id=fact_id,
            occurred_at=occurred_at,
            inter_id=str(value.get("inter_id") or value.get("intersection_id") or "unmatched"),
            road_data_version=value.get("road_data_version"),
            motor_id=str(data["motor_id"]) if data.get("motor_id") is not None else None,
            non_motor_id=str(data["non_motor_id"]) if data.get("non_motor_id") is not None else None,
            severity=data.get("severity"),
            ttc_sec=_float(data.get("ttc_sec")),
            pet_sec=_float(data.get("pet_sec")),
            distance_m=_float(data.get("distance_m")),
            conflict_scene=data.get("conflict_scene"),
            prediction_type=data.get("prediction_type"),
            conflict_angle_deg=_float(data.get("conflict_angle_deg")),
            risk_score=_float(data.get("risk_score")),
            evidence=data.get("evidence"),
            motor_position_m=data.get("motor_position_m"),
            non_motor_position_m=data.get("non_motor_position_m"),
            world_anchor_lat_lon=data.get("world_anchor_lat_lon"),
            **common,
        ))
        return [f"uav_conflict_events:{fact_id}:{occurred_at.isoformat()}"]

    def _add_telemetry(self, session: AsyncSession, envelope: MessageEnvelope, value: dict[str, Any]) -> list[str]:
        data = value["data"]
        common = self._common(envelope, value)
        observed_at = value["occurred_at"]
        fact_id = hashlib.sha256(f"telemetry:{value['message_id']}".encode()).hexdigest()[:40]
        session.add(TelemetryMetric(
            id=fact_id,
            observed_at=observed_at,
            mission_id=data.get("mission_id"),
            pipeline_id=data.get("pipeline_id"),
            latitude=_float(data.get("latitude", data.get("lat"))),
            longitude=_float(data.get("longitude", data.get("lon"))),
            altitude_m=_float(data.get("altitude_m", data.get("altitude"))),
            relative_altitude_m=_float(data.get("relative_altitude_m")),
            speed_ms=_float(data.get("speed_ms")),
            heading_deg=_float(data.get("heading_deg", data.get("heading"))),
            battery_pct=_float(data.get("battery_pct", data.get("battery"))),
            pitch_deg=_float(data.get("pitch_deg", data.get("pitch"))),
            roll_deg=_float(data.get("roll_deg", data.get("roll"))),
            gimbal_pitch_deg=_float(data.get("gimbal_pitch_deg")),
            gimbal_yaw_deg=_float(data.get("gimbal_yaw_deg")),
            is_hovering=data.get("is_hovering"),
            positioning_quality=data.get("positioning_quality"),
            **common,
        ))
        return [f"uav_telemetry_metrics:{fact_id}:{observed_at.isoformat()}"]

    def _add_system_metrics(
        self, session: AsyncSession, envelope: MessageEnvelope, value: dict[str, Any]
    ) -> list[str]:
        data = value["data"]
        common = self._common(envelope, value)
        observed_at = value["occurred_at"]
        instance_id = str(data.get("instance_id", value.get("camera_id") or "platform"))
        if isinstance(data.get("metrics"), list):
            metrics = data["metrics"]
        elif data.get("metric_name") is not None:
            metrics = [data]
        else:
            metrics = [
                {"metric_name": key, "metric_value": item}
                for key, item in data.items()
                if key not in {"timestamp", "msg_type"} and isinstance(item, (int, float))
            ]
        if not metrics:
            raise MetricContractError("uav_system_metrics contains no numeric metrics")
        references = []
        for item in metrics:
            name = str(item.get("metric_name"))
            number = _float(item.get("metric_value"))
            if not name or number is None:
                raise MetricContractError("system metric name/value is invalid")
            fact_id = hashlib.sha256(f"{value['message_id']}:{name}".encode()).hexdigest()[:40]
            session.add(SystemMetric(
                id=fact_id,
                observed_at=observed_at,
                instance_id=instance_id,
                metric_name=name,
                metric_value=number,
                unit=item.get("unit"),
                labels=item.get("labels") or {},
                **common,
            ))
            references.append(f"uav_system_metrics:{fact_id}:{observed_at.isoformat()}")
        return references

    async def capabilities(self) -> dict[str, Any]:
        async with self._sessions() as session:
            extension = bool((await session.execute(
                text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='timescaledb')")
            )).scalar())
            hypertables: list[str] = []
            if extension:
                rows = await session.execute(text(
                    "SELECT hypertable_name FROM timescaledb_information.hypertables "
                    "WHERE hypertable_schema='public' AND hypertable_name LIKE 'uav_%'"
                ))
                hypertables = sorted(row[0] for row in rows)
            return {"timescaledb": extension, "hypertables": hypertables}

    async def query_traffic(self, inter_id: str, period: str, grain_type: str | None = None) -> list[dict]:
        statement = select(TrafficMetric).where(
            TrafficMetric.inter_id == inter_id,
            TrafficMetric.observed_at >= _period_start(period),
        )
        if grain_type:
            statement = statement.where(TrafficMetric.grain_type == grain_type)
        rows = (await self._execute(statement.order_by(TrafficMetric.observed_at))).scalars().all()
        return [self._traffic_dict(row) for row in rows]

    async def query_tracks(
        self, inter_id: str, period: str, limit: int, class_name: str | None = None,
        turn_behavior: str | None = None,
    ) -> list[dict]:
        statement = select(TrackEvent).where(
            TrackEvent.inter_id == inter_id,
            TrackEvent.ended_at >= _period_start(period),
        )
        if class_name:
            statement = statement.where(TrackEvent.vehicle_class == class_name)
        if turn_behavior:
            statement = statement.where(TrackEvent.turn_behavior == turn_behavior)
        rows = (await self._execute(statement.order_by(TrackEvent.ended_at.desc()).limit(limit))).scalars().all()
        return [dict(row.payload.get("data", row.payload), id=row.id) for row in rows]

    async def query_conflicts(self, inter_id: str, period: str, limit: int) -> list[dict]:
        statement = select(ConflictEvent).where(
            ConflictEvent.inter_id == inter_id,
            ConflictEvent.occurred_at >= _period_start(period),
        ).order_by(ConflictEvent.occurred_at.desc()).limit(limit)
        rows = (await self._execute(statement)).scalars().all()
        reviews: dict[str, ConflictReview] = {}
        if rows:
            review_rows = (await self._execute(
                select(ConflictReview).where(ConflictReview.event_id.in_([row.id for row in rows]))
            )).scalars().all()
            reviews = {row.event_id: row for row in review_rows}
        return [self._conflict_dict(row, reviews.get(row.id)) for row in rows]

    async def review_conflict(
        self,
        inter_id: str,
        event_id: str,
        review_status: str,
        expected_revision: int,
        reviewed_by: int | None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        if review_status not in {"confirmed", "rejected"}:
            raise MetricContractError("review_status must be confirmed or rejected")
        async with self._sessions() as session:
            async with session.begin():
                row = (await session.execute(
                    select(ConflictEvent).where(
                        ConflictEvent.id == event_id,
                        ConflictEvent.inter_id == inter_id,
                    ).with_for_update()
                )).scalar_one_or_none()
                if row is None:
                    raise LookupError("conflict event not found")
                review = (await session.execute(
                    select(ConflictReview).where(ConflictReview.event_id == event_id).with_for_update()
                )).scalar_one_or_none()
                current_revision = review.revision if review else 1
                if current_revision != expected_revision:
                    raise MessageIdentityConflict("conflict review revision mismatch")
                if review is None:
                    review = ConflictReview(
                        event_id=row.id,
                        event_occurred_at=row.occurred_at,
                        inter_id=row.inter_id,
                        review_status=review_status,
                        revision=2,
                        reviewed_by=reviewed_by,
                        reviewed_at=datetime.now(UTC),
                        review_reason=reason,
                    )
                    session.add(review)
                else:
                    review.review_status = review_status
                    review.revision += 1
                    review.reviewed_by = reviewed_by
                    review.reviewed_at = datetime.now(UTC)
                    review.review_reason = reason
            return self._conflict_dict(row, review)

    async def query_system_metrics(self, period: str, metric_names: list[str] | None = None) -> list[dict]:
        statement = select(SystemMetric).where(SystemMetric.observed_at >= _period_start(period))
        if metric_names:
            statement = statement.where(SystemMetric.metric_name.in_(metric_names))
        rows = (await self._execute(statement.order_by(SystemMetric.observed_at))).scalars().all()
        grouped: dict[datetime, dict[str, Any]] = {}
        for row in rows:
            bucket = grouped.setdefault(row.observed_at, {"time": row.observed_at.isoformat()})
            bucket[row.metric_name] = row.metric_value
        return list(grouped.values())

    async def _execute(self, statement):
        async with self._sessions() as session:
            return await session.execute(statement)

    @staticmethod
    def _traffic_dict(row: TrafficMetric) -> dict[str, Any]:
        return {
            "time": row.observed_at.isoformat(),
            "intersection_id": row.intersection_id,
            "inter_id": row.inter_id,
            "grain_type": row.grain_type,
            "grain_key": row.grain_key,
            "cars": row.cars,
            "total_vehicles": row.vehicle_count,
            "flow_veh_per_min": row.flow_veh_per_min,
            "avg_speed_kmh": row.avg_speed_kmh,
            "congestion_index": row.congestion_index,
            "queue_length_m": row.queue_length_m,
            "headway_sec": row.headway_sec,
            "quality_status": row.quality_status,
            "time_quality": row.time_quality,
        }

    @staticmethod
    def _conflict_dict(row: ConflictEvent, review: ConflictReview | None = None) -> dict[str, Any]:
        return dict(
            row.payload.get("data", row.payload),
            id=row.id,
            occurred_at=row.occurred_at.isoformat(),
            inter_id=row.inter_id,
            road_data_version=row.road_data_version,
            quality_status=row.quality_status,
            time_quality=row.time_quality,
            review_status=review.review_status if review else "pending",
            review_revision=review.revision if review else 1,
            reviewed_at=review.reviewed_at.isoformat() if review else None,
            review_reason=review.review_reason if review else None,
        )


class InMemoryMetricStoreAdapter:
    """Test/fixture adapter that exercises the same consumer seam without I/O."""

    def __init__(self):
        self.messages: dict[tuple[str, str], PersistResult] = {}
        self.payload_hashes: dict[tuple[str, str], str] = {}
        self.dead_letters: dict[tuple[str, int, int], dict[str, Any]] = {}

    async def persist(self, envelope: MessageEnvelope) -> PersistResult:
        normalized = PostgresMetricStoreAdapter(None)._normalize(envelope)
        msg_type = normalized["msg_type"]
        message_id = normalized["message_id"]
        key = (normalized["source_system"], message_id)
        payload_hash = _json_hash(envelope.payload)
        existing = self.messages.get(key)
        if existing:
            if self.payload_hashes[key] != payload_hash:
                raise MessageIdentityConflict(
                    f"message_id {message_id} was replayed with a different payload"
                )
            return PersistResult(True, message_id, msg_type, existing.normalized_payload, existing.fact_references)
        result = PersistResult(False, message_id, msg_type, normalized, (f"memory:{message_id}",))
        self.messages[key] = result
        self.payload_hashes[key] = payload_hash
        return result

    async def quarantine(self, envelope: MessageEnvelope, error: MetricContractError) -> str:
        key = (envelope.topic, envelope.partition, envelope.offset)
        existing = self.dead_letters.get(key)
        count = int(existing["occurrence_count"]) + 1 if existing else 1
        dead_letter_id = hashlib.sha256(
            f"{envelope.topic}:{envelope.partition}:{envelope.offset}".encode("utf-8")
        ).hexdigest()[:40]
        self.dead_letters[key] = {
            "id": dead_letter_id,
            "reason_code": type(error).__name__,
            "reason_summary": str(error),
            "payload": _json_safe(envelope.payload),
            "occurrence_count": count,
        }
        return dead_letter_id
