"""Transactional Kafka ingestion for isolated replay-v2 facts."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, insert, select, text, update
from utils_local.track_message_codec import unpack_track_message
from utils_local.trajectory_sampling import VERSION as SAMPLING_V2
from utils_local.trajectory_sampling import validate_summary

from app.core.config import settings
from app.models.replay_v2 import (
    ReplayV2ConflictEvent,
    ReplayV2Episode,
    ReplayV2InterEvaluation5MinMM,
    ReplayV2IntersectionMetric5Min,
    ReplayV2LaneMetric5Min,
    ReplayV2LinkMetric5Min,
    ReplayV2Maneuver,
    ReplayV2MessageDeadLetter,
    ReplayV2MessageInbox,
    ReplayV2Mission,
    ReplayV2TelemetryMetric,
    ReplayV2TrackEvent,
    ReplayV2TrackPoint,
    ReplayV2TrafficMetricSample,
    ReplayV2TurnMetric5Min,
)
from app.services.metric_store import (
    MessageEnvelope,
    MessageIdentityConflict,
    MetricContractError,
    PersistResult,
    PostgresMetricStoreAdapter,
    _granularity_seconds,
    _period_start,
)
from app.services.replay_v2_aggregates import build_mission_aggregates
from app.services.replay_v2_conflict_evidence import (
    register_replay_v2_conflict_evidence,
)

from utils_local.replay_topics import FIXED_TOPICS
from app.models.replay_v2 import ReplayV2IngestReceipt, ReplayV2TrackRelation
EXPECTED_TYPES = {topic: kind for kind, topic in FIXED_TOPICS.items()}


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise MetricContractError("replay message timestamp is invalid") from exc


def _hash(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _fact_id(*parts: Any) -> str:
    return hashlib.sha256(":".join(str(part) for part in parts).encode()).hexdigest()[:40]


def _required_offset_ms(data: dict) -> int:
    raw_offset = data.get("offset_ms")
    if raw_offset is None or isinstance(raw_offset, bool):
        raise MetricContractError("replay timed fact requires offset_ms")
    try:
        offset_ms = int(raw_offset)
    except (TypeError, ValueError) as exc:
        raise MetricContractError("replay timed fact offset_ms is invalid") from exc
    if offset_ms < 0 or (isinstance(raw_offset, float) and not raw_offset.is_integer()):
        raise MetricContractError("replay timed fact offset_ms is invalid")
    return offset_ms


class ReplayV2MetricStoreAdapter:
    async def _add_ingest_receipt(self, session, envelope, normalized):
        from app.services.metric_store import record_ingest_receipt

        await record_ingest_receipt(session, envelope, normalized)

    """Replay-v2 MetricStore adapter; it never writes canonical fact tables."""

    def __init__(self, session_maker, *, evidence_storage_root: str | None = None) -> None:
        self._session_maker = session_maker
        self._evidence_storage_root = evidence_storage_root or settings.survey_storage_dir

    def _normalize(self, envelope: MessageEnvelope) -> dict:
        from utils_local.message_identity import validate_payload
        try:
            validate_payload(envelope.payload)
        except ValueError as error:
            raise MetricContractError(str(error)) from error
        match = envelope.topic in EXPECTED_TYPES
        if not match:
            raise MetricContractError("unsupported replay-v2 Topic")
        try:
            payload = (
                unpack_track_message(envelope.payload)
                if isinstance(envelope.payload, dict)
                else envelope.payload
            )
        except (ValueError, OSError, KeyError, TypeError) as error:
            raise MetricContractError("invalid packed replay track geometry") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
            raise MetricContractError("replay-v2 message requires an object data field")
        message_id = str(payload.get("message_id") or "")
        if not message_id:
            raise MetricContractError("replay-v2 message_id is required")
        msg_type = str(payload.get("msg_type") or "")
        if msg_type != EXPECTED_TYPES[envelope.topic] and not (envelope.topic == "uav_track_complete" and msg_type == "uav_track_chunk"):
            raise MetricContractError("replay-v2 Topic and msg_type do not match")
        if payload.get("source_system") != "uav_traffic_analyzer_ai":
            raise MetricContractError("replay-v2 source_system is unsupported")
        produced_at = _parse_datetime(payload.get("produced_at"))
        occurred_at = _parse_datetime(payload.get("occurred_at") or produced_at)
        return {
            **payload,
            "message_id": message_id,
            "msg_type": msg_type,
            "produced_at": produced_at,
            "occurred_at": occurred_at,
            "source_key": str(payload["data"].get("source_profile_id") or ""),
        }

    async def persist(self, envelope: MessageEnvelope) -> PersistResult:
        value = self._normalize(envelope)
        payload_hash = _hash(envelope.payload)
        duplicate = False
        dispatch_status = "pending"
        async with self._session_maker() as session:
            async with session.begin():
                existing = await session.scalar(
                    select(ReplayV2MessageInbox).where(
                        ReplayV2MessageInbox.message_id == value["message_id"]
                    )
                )
                if existing is not None:
                    if existing.message_hash != payload_hash:
                        raise MessageIdentityConflict(
                            f"message_id {value['message_id']} was replayed with a different payload"
                        )
                    duplicate = True
                    references = list(existing.fact_refs or [])
                    dispatch_status = existing.status
                else:
                    references = await self._add_facts(session, envelope, value)
                    session.add(
                        ReplayV2MessageInbox(
                            id=_fact_id("inbox", value["message_id"]),
                            message_id=value["message_id"],
                            message_hash=payload_hash,
                            msg_type=value["msg_type"],
                            topic=envelope.topic,
                            partition=envelope.partition,
                            offset=envelope.offset,
                            status="pending",
                            fact_refs=references,
                            audit_payload=(
                                envelope.payload
                                if value["msg_type"] == "uav_replay_mission"
                                else None
                            ),
                            received_at=datetime.now(UTC),
                        )
                    )
                if value['msg_type'] in {'uav_track_complete', 'uav_track_chunk', 'uav_replay_mission', 'uav_track_relation'}:
                    receipt = await session.get(ReplayV2IngestReceipt, value['message_id'])
                    if receipt is None:
                        session.add(ReplayV2IngestReceipt(message_id=value['message_id'],
                            message_hash=payload_hash, deployment_id=str(value.get('deployment_id') or 'local'),
                            status='pending', committed_at=datetime.now(UTC)))
                    else:
                        receipt.status = 'pending'
        mission_id = str(value["data"].get("mission_id") or "")
        if mission_id and value["msg_type"] in {
            "uav_stats",
            "uav_track_complete",
            "uav_replay_mission",
        }:
            # Topic ordering is independent.  Rebuild only after the sealed
            # Mission's declared journey count has converged; a duplicate retry
            # also repairs an aggregate transaction that previously failed.
            await self._refresh_aggregates_if_complete(mission_id)
        return PersistResult(
            duplicate,
            value["message_id"],
            value["msg_type"],
            value,
            tuple(references),
            dispatch_status,
        )

    async def _add_facts(self, session, envelope: MessageEnvelope, value: dict) -> list[str]:
        data = value["data"]
        if value['msg_type'] == 'uav_track_chunk':
            return await self._add_chunk(session, envelope, value, data)
        if value["msg_type"] == "uav_replay_mission":
            return await self._add_mission(session, value, data)
        if value["msg_type"] == "uav_track_complete":
            await self._ensure_track_mission(session, value, data)
            references = await self._add_track(session, value, data)
            if data.get('archive_schema_version') == 'incremental/v1':
                from app.services.incremental_replay_jobs import register_track
                mission = await session.scalar(select(ReplayV2Mission).where(ReplayV2Mission.id == data['mission_id']).with_for_update())
                await register_track(session, mission, data)
            return references
        if value["msg_type"] == "uav_track_relation":
            evidence = data.get('evidence') or {}
            if (not data.get('mission_id') or not data.get('predecessor_id') or not data.get('successor_id')
                or str(data['predecessor_id']) == str(data['successor_id'])
                or not 0 < float(evidence.get('temporal_gap_sec', 0)) <= 2
                or float(evidence.get('appearance_cosine', 0)) < 0.9
                or evidence.get('motion_space') not in {'enu_m', 'pixel'}
                or not 0 <= float(evidence.get('motion_distance', -1)) <= (5 if evidence.get('motion_space') == 'enu_m' else 50)):
                raise MetricContractError('invalid trajectory relation evidence')
            session.add(ReplayV2TrackRelation(id=value['message_id'], mission_id=data['mission_id'],
                predecessor_id=str(data['predecessor_id']), successor_id=str(data['successor_id']), evidence=data['evidence']))
            return [f"uav_replay_v2_track_relations:{value['message_id']}"]
        if value["msg_type"] == "uav_stats":
            return self._add_stats(session, value, data)
        if value["msg_type"] == "uav_conflict":
            return self._add_conflict(session, value, data)
        if value["msg_type"] == "uav_telemetry":
            return self._add_telemetry(session, value, data)
        raise MetricContractError("unsupported replay-v2 msg_type")

    async def _add_chunk(self, session, envelope, value, data):
        import base64, gzip, io
        from app.models.replay_v2 import ReplayV2TrackChunk
        from utils_local.track_message_codec import MAX_INFLATED
        logical=str(data.get('logical_message_id') or '')
        count, seq, size=data.get('chunk_count'),data.get('chunk_seq'),data.get('decoded_bytes')
        if (not logical or type(count) is not int or not 1<=count<=256 or type(seq) is not int
            or not 0<=seq<count or type(size) is not int or not 0<size<=MAX_INFLATED
            or not isinstance(data.get('base64'),str) or len(data['base64'])>550000):
            raise MetricContractError('invalid trajectory chunk bounds')
        base64.b64decode(data['base64'],validate=True)
        old=await session.get(ReplayV2TrackChunk,(logical,seq))
        if old and old.payload!=data: raise MessageIdentityConflict('trajectory chunk identity conflict')
        if not old: session.add(ReplayV2TrackChunk(logical_message_id=logical,chunk_seq=seq,payload=data))
        await session.flush()
        rows=(await session.execute(select(ReplayV2TrackChunk).where(ReplayV2TrackChunk.logical_message_id==logical).order_by(ReplayV2TrackChunk.chunk_seq))).scalars().all()
        if len(rows)<count: return [f'uav_replay_v2_track_chunks:{logical}:{seq}']
        if len(rows)!=count or any(row.chunk_seq!=i or any(row.payload.get(k)!=data.get(k) for k in ('chunk_count','logical_sha256','decoded_bytes','mission_id','source_profile_id')) for i,row in enumerate(rows)):
            raise MetricContractError('trajectory chunk manifest conflict')
        compressed=b''.join(base64.b64decode(row.payload['base64'],validate=True) for row in rows)
        with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream: raw=stream.read(size+1)
        if len(raw)!=size or hashlib.sha256(raw).hexdigest()!=data['logical_sha256']:
            raise MetricContractError('trajectory logical checksum mismatch')
        payload=json.loads(raw)
        if payload.get('message_id')!=logical or payload.get('msg_type')!='uav_track_complete' or payload.get('deployment_id')!=value.get('deployment_id'):
            raise MetricContractError('trajectory chunk lineage conflict')
        logical_envelope=MessageEnvelope(payload,envelope.topic,envelope.partition,envelope.offset)
        normalized=self._normalize(logical_envelope)
        existing=await session.scalar(select(ReplayV2MessageInbox).where(ReplayV2MessageInbox.message_id==logical))
        if existing:
            if existing.message_hash!=_hash(payload): raise MessageIdentityConflict('logical trajectory identity conflict')
            return list(existing.fact_refs)
        references=await self._add_facts(session,logical_envelope,normalized)
        session.add(ReplayV2MessageInbox(id=_fact_id('inbox',logical),message_id=logical,message_hash=_hash(payload),
            msg_type='uav_track_complete',topic=envelope.topic,partition=envelope.partition,offset=envelope.offset,
            status='pending',fact_refs=references,received_at=datetime.now(UTC)))
        return references

    async def _ensure_track_mission(self, session, value, data):
        mission = await session.scalar(select(ReplayV2Mission).where(ReplayV2Mission.id == data['mission_id']).with_for_update())
        if mission is None:
            await self._add_mission(session, value, {
                **data, 'status': 'running', 'journey_count': 0,
                'duration_sec': max((p['offset_ms'] for p in data.get('points', [])), default=0)/1000,
                'source_point_count':0, 'retained_point_count':0, 'behavior_count':0,
            })
            await session.flush()
            mission = await session.scalar(select(ReplayV2Mission).where(ReplayV2Mission.id == data['mission_id']).with_for_update())
        if mission.inter_id != str(value.get('inter_id') or value.get('intersection_id') or '') or mission.source_profile_id != value['source_key']:
            raise MetricContractError('trajectory Mission lineage conflict')
        mission.duration_ms = max(mission.duration_ms or 0, max(p['offset_ms'] for p in data['points']))
        if mission.status not in {'sealed','finalizing'}:
            mission.journey_count = (mission.journey_count or 0) + 1

    async def _add_mission(self, session, value: dict, data: dict) -> list[str]:
        mission_id = str(data.get("mission_id") or "")
        inter_id = str(value.get("inter_id") or value.get("intersection_id") or "")
        source_profile_id = str(data.get("source_profile_id") or value["source_key"])
        if not mission_id or not inter_id:
            raise MetricContractError("replay Mission lineage is incomplete")
        duration_ms = round(float(data.get("duration_sec") or 0) * 1000)
        ended_at = value["occurred_at"]
        started_at = ended_at - timedelta(milliseconds=duration_ms)
        row = {
            "id": mission_id,
            "inter_id": inter_id,
            "source_profile_id": source_profile_id,
            "pipeline_id": data.get("pipeline_id"),
            "run_id": data.get("run_id"),
            "status": "finalizing" if data.get("status") == "sealed" else str(data.get("status") or "incomplete"),
            "started_at": started_at,
            "ended_at": ended_at,
            "duration_ms": duration_ms,
            "coordinate_coverage_ratio": float(data.get("coordinate_coverage_ratio") or 0.0),
            "journey_count": int(data.get("journey_count") or 0),
            "behavior_count": int(data.get("behavior_count") or 0),
            "source_point_count": int(data.get("source_point_count") or 0),
            "retained_point_count": int(data.get("retained_point_count") or 0),
            "algorithm_versions": data.get("algorithm_versions") or {},
            "accuracy": data.get("accuracy") or {},
            "failure_reason": data.get("failure_reason"),
            "sealed_at": value["produced_at"] if data.get("status") == "sealed" else None,
            "segment_manifest_hash": data.get("segment_manifest_hash"),
            "expected_relation_count": data.get("expected_relation_count"),
            "created_at": value["produced_at"],
            "updated_at": value["produced_at"],
        }
        existing = await session.scalar(select(ReplayV2Mission).where(ReplayV2Mission.id==mission_id).with_for_update())
        if existing is not None and (existing.inter_id != inter_id or existing.source_profile_id != source_profile_id):
            raise MetricContractError('Mission lifecycle lineage conflict')
        if existing is not None and row['status']=='running':
            row['algorithm_versions']={**(existing.algorithm_versions or {}),**row['algorithm_versions']}
        if existing is None:
            session.add(ReplayV2Mission(**row))
        elif (existing.status != "sealed" or row["status"] == "sealed") and not (row["status"] == "running" and existing.status != "running"):
            # A durable incomplete diagnostic is a recoverable state.  A later
            # natural-EOF seal upgrades the same Mission fact in place; a late
            # incomplete event can never downgrade an already sealed Mission.
            for key, item in row.items():
                if key not in {"id", "created_at"} and not (row["status"] == "running" and key in {"duration_ms", "journey_count", "started_at", "source_point_count", "retained_point_count", "behavior_count", "coordinate_coverage_ratio"}):
                    setattr(existing, key, item)
        return [f"uav_replay_v2_missions:{mission_id}"]

    async def _add_track(self, session, value: dict, data: dict) -> list[str]:
        mission_id = str(data.get("mission_id") or "")
        track_id = str(data.get("track_id") or "")
        inter_id = str(value.get("inter_id") or value.get("intersection_id") or "")
        points = data.get("points") or []
        if not mission_id or not track_id or not points:
            raise MetricContractError("sealed replay track requires mission, track and points")
        if data.get('segment_digest') is not None and re.fullmatch(r'[0-9a-f]{64}',str(data['segment_digest'])) is None:
            raise MetricContractError('invalid source segment digest')
        version = (data.get("sampling") or {}).get("algorithm_version")
        if version not in {None, "event-faithful/v1", SAMPLING_V2}:
            raise MetricContractError("unsupported replay history sampling version")
        if (data.get("sampling") or {}).get("algorithm_version") == SAMPLING_V2:
            try:
                validate_summary(data["sampling"], source_count=data.get("source_point_count"))
                if (
                    type(data.get("source_point_count")) is not int
                    or len(points) != data.get("retained_point_count")
                    or not 0 < len(points) <= data["source_point_count"]
                ):
                    raise ValueError("v2 geometry count mismatch")
            except (ValueError, KeyError, TypeError) as error:
                raise MetricContractError("invalid full-sequence sampling summary") from error
        event_id = _fact_id(mission_id, track_id)
        session.add(
            ReplayV2TrackEvent(
                id=event_id,
                mission_id=mission_id,
                inter_id=inter_id,
                source_profile_id=str(data.get("source_profile_id") or value["source_key"]),
                track_id=track_id,
                segment_digest=data.get("segment_digest"),
                source_runtime_track_ids=[
                    str(item) for item in data.get("source_runtime_track_ids") or []
                ],
                vehicle_class=data.get("vehicle_class"),
                yolo_class_id=data.get("yolo_class_id"),
                yolo_class_name=data.get("yolo_class_name"),
                turn_behavior=data.get("turn_behavior"),
                movement_key=data.get("movement_key"),
                matched_lane_key=data.get("matched_lane_key"),
                matched_link_id=data.get("matched_link_id"),
                started_offset_ms=int(points[0]["offset_ms"]),
                ended_offset_ms=int(points[-1]["offset_ms"]),
                source_point_count=int(data.get("source_point_count") or len(points)),
                retained_point_count=int(data.get("retained_point_count") or len(points)),
                sampling=data.get("sampling") or {},
                termination_reason=data.get("termination_reason"),
                created_at=value["produced_at"],
            )
        )
        references = [f"uav_replay_v2_track_events:{event_id}"]
        point_rows = []
        for index, point in enumerate(points):
            enu = point.get("enu_m")
            gcj02 = point.get("gcj02")
            speed = point.get("speed") or {}
            vector = speed.get("enu_vector_mps")
            point_id = _fact_id(mission_id, track_id, index)
            point_rows.append(
                dict(
                    id=point_id,
                    mission_id=mission_id,
                    track_id=track_id,
                    point_seq=index,
                    offset_ms=int(point["offset_ms"]),
                    source_timestamp_sec=float(point.get("source_timestamp_sec") or 0.0),
                    frame_num=int(point["frame_num"]),
                    pixel_x=float(point["pixel"][0]),
                    pixel_y=float(point["pixel"][1]),
                    enu_x_m=float(enu[0]) if enu is not None else None,
                    enu_y_m=float(enu[1]) if enu is not None else None,
                    longitude_gcj02=float(gcj02[0]) if gcj02 is not None else None,
                    latitude_gcj02=float(gcj02[1]) if gcj02 is not None else None,
                    instant_speed_kmh=speed.get("instant_kmh"),
                    ema_speed_kmh=speed.get("ema_kmh"),
                    velocity_east_mps=vector[0] if vector else None,
                    velocity_north_mps=vector[1] if vector else None,
                    speed_quality=speed.get("quality"),
                    point_quality=point.get("quality") or {},
                    sampling_boundary=point.get("sampling_boundary") or [],
                )
            )
            if len(point_rows) >= 1000:
                await session.execute(insert(ReplayV2TrackPoint), point_rows)
                point_rows.clear()
        if point_rows:
            await session.execute(insert(ReplayV2TrackPoint), point_rows)
        for kind, model in (("episodes", ReplayV2Episode), ("maneuvers", ReplayV2Maneuver)):
            for index, behavior in enumerate(data.get(kind) or []):
                behavior_id = _fact_id(mission_id, track_id, kind, index)
                session.add(
                    model(
                        id=behavior_id,
                        mission_id=mission_id,
                        track_id=track_id,
                        kind=str(behavior["kind"]),
                        start_offset_ms=int(behavior["start_offset_ms"]),
                        end_offset_ms=int(behavior["end_offset_ms"]),
                        confidence=behavior.get("confidence"),
                        quality_status=str(behavior.get("quality_status") or "estimated"),
                        reason=behavior.get("reason"),
                        evidence=behavior.get("evidence") or {},
                        algorithm_version=str(
                            behavior.get("algorithm_version") or "trajectory-behavior/v1"
                        ),
                    )
                )
                references.append(f"{model.__tablename__}:{behavior_id}")
        return references

    def _add_stats(self, session, value: dict, data: dict) -> list[str]:
        mission_id = str(data.get("mission_id") or "")
        sample_id = _fact_id("sample", value["message_id"])
        session.add(
            ReplayV2TrafficMetricSample(
                id=sample_id,
                mission_id=mission_id,
                inter_id=str(value.get("inter_id") or value.get("intersection_id") or ""),
                source_profile_id=str(data.get("source_profile_id") or value["source_key"]),
                sampled_at=value["occurred_at"],
                vehicle_count=data.get("cars", data.get("total_vehicles")),
                active_tracks=data.get("active_tracks"),
                avg_speed_kmh=data.get("avg_speed_kmh"),
                queue_count=data.get("queue_count"),
                coverage_ratio=data.get("coverage_ratio"),
            )
        )
        return [f"uav_replay_v2_traffic_metric_samples:{sample_id}"]

    async def query_traffic(
        self,
        inter_id: str,
        period: str,
        grain_type: str | None = None,
        source_profile_id: str | None = None,
        pipeline_id: str | None = None,
        granularity: str | None = None,
    ) -> list[dict]:
        """Read live Replay V2 samples without persisting transient trajectory tails."""
        if grain_type not in {None, "intersection"}:
            return []
        statement = (
            select(ReplayV2TrafficMetricSample, ReplayV2Mission.pipeline_id)
            .outerjoin(
                ReplayV2Mission,
                ReplayV2Mission.id == ReplayV2TrafficMetricSample.mission_id,
            )
            .where(
                ReplayV2TrafficMetricSample.inter_id == inter_id,
                ReplayV2TrafficMetricSample.sampled_at >= _period_start(period),
            )
        )
        if source_profile_id:
            statement = statement.where(
                ReplayV2TrafficMetricSample.source_profile_id == source_profile_id
            )
        if pipeline_id:
            statement = statement.where(ReplayV2Mission.pipeline_id == pipeline_id)
        async with self._session_maker() as session:
            rows = (
                await session.execute(statement.order_by(ReplayV2TrafficMetricSample.sampled_at))
            ).all()
        summaries = [
            {
                "_observed_at": sample.sampled_at,
                "time": sample.sampled_at.isoformat(),
                "intersection_id": sample.inter_id,
                "inter_id": sample.inter_id,
                "grain_type": "intersection",
                "grain_key": sample.inter_id,
                "cars": sample.vehicle_count,
                "total_vehicles": sample.vehicle_count,
                "active_tracks": sample.active_tracks,
                "flow_veh_per_min": None,
                "avg_speed_kmh": sample.avg_speed_kmh,
                "congestion_index": None,
                "queue_length_m": None,
                "queue_count": sample.queue_count,
                "headway_sec": None,
                "direction_flow": None,
                "coverage_ratio": sample.coverage_ratio,
                "quality_status": "estimated",
                "time_quality": "verified",
                "source_profile_id": sample.source_profile_id,
                "pipeline_id": pipeline_id,
                "tcc_diagnostics": None,
            }
            for sample, pipeline_id in rows
        ]
        if granularity:
            summaries = PostgresMetricStoreAdapter._downsample_traffic(
                summaries,
                _granularity_seconds(granularity),
            )
        for item in summaries:
            item.pop("_observed_at", None)
        return summaries

    async def query_conflicts(
        self,
        inter_id: str,
        period: str,
        limit: int,
        source_profile_id: str | None = None,
        pipeline_id: str | None = None,
        prediction_type: str | None = None,
    ) -> list[dict]:
        """Expose Replay V2 conflict facts through the monitoring read contract."""
        statement = (
            select(ReplayV2ConflictEvent, ReplayV2Mission)
            .join(ReplayV2Mission, ReplayV2Mission.id == ReplayV2ConflictEvent.mission_id)
            .where(ReplayV2ConflictEvent.inter_id == inter_id)
        )
        if source_profile_id:
            statement = statement.where(ReplayV2Mission.source_profile_id == source_profile_id)
        if pipeline_id:
            statement = statement.where(ReplayV2Mission.pipeline_id == pipeline_id)
        if prediction_type:
            statement = statement.where(ReplayV2ConflictEvent.prediction_type == prediction_type)
        period_start = _period_start(period)
        async with self._session_maker() as session:
            rows = (
                await session.execute(
                    statement.order_by(
                        ReplayV2Mission.created_at.desc(),
                        ReplayV2ConflictEvent.offset_ms.desc(),
                    ).limit(max(limit * 4, limit))
                )
            ).all()
        result = []
        for conflict, mission in rows:
            occurred_at = mission.started_at + timedelta(milliseconds=conflict.offset_ms)
            if occurred_at < period_start:
                continue
            result.append(
                {
                    "id": conflict.id,
                    "message_id": conflict.id,
                    "mission_id": conflict.mission_id,
                    "pipeline_id": mission.pipeline_id,
                    "source_profile_id": mission.source_profile_id,
                    "occurred_at": occurred_at.isoformat(),
                    "inter_id": conflict.inter_id,
                    "offset_ms": conflict.offset_ms,
                    "severity": conflict.severity,
                    "prediction_type": conflict.prediction_type,
                    "motor_id": conflict.motor_track_id,
                    "non_motor_id": conflict.non_motor_track_id,
                    "distance_m": conflict.distance_m,
                    "conflict_scene": conflict.conflict_scene,
                    "ttc_sec": conflict.ttc_sec,
                    "pet_sec": conflict.pet_sec,
                    "evidence": conflict.evidence,
                    "quality_status": "estimated",
                    "time_quality": "verified",
                    "review_status": "pending",
                    "review_revision": 1,
                    "reviewed_at": None,
                    "review_reason": None,
                }
            )
            if len(result) >= limit:
                break
        return result

    def _add_conflict(self, session, value: dict, data: dict) -> list[str]:
        fact_id = _fact_id("conflict", value["message_id"])
        evidence_files = data.pop("evidence_files", None)
        evidence_fact_refs: list[str] = []
        if evidence_files:
            try:
                evidence_refs, evidence_fact_refs = register_replay_v2_conflict_evidence(
                    session,
                    fact_id=fact_id,
                    source_message_id=value["message_id"],
                    evidence_files=evidence_files,
                    storage_root=self._evidence_storage_root,
                    source_time_raw={
                        **(value.get("source_time_raw") or {}),
                        "mission_offset_ms": data.get("offset_ms"),
                    },
                )
                data["evidence_refs"] = evidence_refs
                data["evidence_status"] = "complete"
                data.pop("evidence_error", None)
            except (OSError, TypeError, ValueError) as exc:
                data["evidence_refs"] = []
                data["evidence_status"] = "incomplete"
                data["evidence_error"] = str(exc)
        else:
            data["evidence_refs"] = []
            data["evidence_status"] = "incomplete"
            data.setdefault("evidence_error", "evidence_files_missing")
        session.add(
            ReplayV2ConflictEvent(
                id=fact_id,
                mission_id=str(data.get("mission_id") or ""),
                inter_id=str(value.get("inter_id") or value.get("intersection_id") or ""),
                offset_ms=_required_offset_ms(data),
                severity=data.get("severity"),
                prediction_type=data.get("prediction_type"),
                motor_track_id=(
                    str(data["motor_id"]) if data.get("motor_id") is not None else None
                ),
                non_motor_track_id=(
                    str(data["non_motor_id"]) if data.get("non_motor_id") is not None else None
                ),
                distance_m=data.get("distance_m"),
                conflict_scene=data.get("conflict_scene"),
                ttc_sec=data.get("ttc_sec"),
                pet_sec=data.get("pet_sec"),
                evidence=data.get("evidence"),
            )
        )
        return [
            f"uav_replay_v2_conflict_events:{fact_id}",
            *evidence_fact_refs,
        ]

    def _add_telemetry(self, session, value: dict, data: dict) -> list[str]:
        fact_id = _fact_id("telemetry", value["message_id"])
        position = data.get("position_gcj02") or {}
        session.add(
            ReplayV2TelemetryMetric(
                id=fact_id,
                mission_id=str(data.get("mission_id") or ""),
                offset_ms=_required_offset_ms(data),
                drone_id=value.get("drone_id"),
                longitude_gcj02=position.get("longitude"),
                latitude_gcj02=position.get("latitude"),
                altitude_m=data.get("altitude_m"),
                speed_mps=data.get("speed_ms"),
                heading_deg=data.get("heading_deg"),
                quality_status=str(value.get("quality_status") or "unverified"),
            )
        )
        return [f"uav_replay_v2_telemetry_metrics:{fact_id}"]

    async def _refresh_aggregates_if_complete(self, mission_id: str) -> None:
        """Converge all narrow DWS facts once a sealed Mission is complete.

        Kafka ordering is per Topic, so the Mission record can arrive before a
        final journey from another Topic.  The declared journey count is the
        convergence barrier; rebuilding is idempotent and stays entirely in
        the Replay V2 namespace.
        """

        async with self._session_maker() as session:
            async with session.begin():
                mission = await session.get(ReplayV2Mission, mission_id)
                if mission is None or mission.status not in {"sealed", "finalizing"}:
                    return
                if (mission.algorithm_versions or {}).get('archive') == 'incremental/v1':
                    from app.services.incremental_replay_jobs import IncrementalReplayJobs
                    await IncrementalReplayJobs.finalize(session, mission)
                    return
                event_count = int(
                    await session.scalar(
                        select(func.count())
                        .select_from(ReplayV2TrackEvent)
                        .where(ReplayV2TrackEvent.mission_id == mission_id)
                    )
                    or 0
                )
                if event_count != mission.journey_count:
                    return
                mission.status = "sealed"

                events = (
                    (
                        await session.execute(
                            select(ReplayV2TrackEvent)
                            .where(ReplayV2TrackEvent.mission_id == mission_id)
                            .order_by(ReplayV2TrackEvent.track_id)
                        )
                    )
                    .scalars()
                    .all()
                )
                points = (
                    (
                        await session.execute(
                            select(ReplayV2TrackPoint)
                            .where(ReplayV2TrackPoint.mission_id == mission_id)
                            .order_by(ReplayV2TrackPoint.track_id, ReplayV2TrackPoint.point_seq)
                        )
                    )
                    .scalars()
                    .all()
                )
                episodes = (
                    (
                        await session.execute(
                            select(ReplayV2Episode).where(ReplayV2Episode.mission_id == mission_id)
                        )
                    )
                    .scalars()
                    .all()
                )
                maneuvers = (
                    (
                        await session.execute(
                            select(ReplayV2Maneuver).where(
                                ReplayV2Maneuver.mission_id == mission_id
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                samples = (
                    (
                        await session.execute(
                            select(ReplayV2TrafficMetricSample).where(
                                ReplayV2TrafficMetricSample.mission_id == mission_id
                            )
                        )
                    )
                    .scalars()
                    .all()
                )

                points_by_track: dict[str, list[dict]] = {}
                for point in points:
                    points_by_track.setdefault(point.track_id, []).append(
                        {
                            "offset_ms": point.offset_ms,
                            "speed": {"ema_kmh": point.ema_speed_kmh},
                        }
                    )

                def behavior(row) -> dict:
                    return {
                        "kind": row.kind,
                        "start_offset_ms": row.start_offset_ms,
                        "end_offset_ms": row.end_offset_ms,
                    }

                journeys = [
                    {
                        "track_id": event.track_id,
                        "sampling": event.sampling,
                        "source_point_count": event.source_point_count,
                        "started_offset_ms": event.started_offset_ms,
                        "matched_link_id": event.matched_link_id,
                        "matched_lane_key": event.matched_lane_key,
                        "movement_key": event.movement_key,
                        "turn_behavior": event.turn_behavior,
                        "points": points_by_track.get(event.track_id, []),
                        "episodes": [
                            behavior(row) for row in episodes if row.track_id == event.track_id
                        ],
                        "maneuvers": [
                            behavior(row) for row in maneuvers if row.track_id == event.track_id
                        ],
                    }
                    for event in events
                ]
                sample_documents = [
                    {
                        "sampled_at": row.sampled_at,
                        "coverage_ratio": row.coverage_ratio,
                    }
                    for row in samples
                ]
                versions = mission.algorithm_versions or {}
                calc_version = str(versions.get("aggregate") or "replay-v2-aggregate/v1")
                profile_version = str(versions.get("typical") or "replay-v2-typical/v1")
                facts = build_mission_aggregates(
                    mission={
                        "id": mission.id,
                        "inter_id": mission.inter_id,
                        "source_profile_id": mission.source_profile_id,
                        "started_at": mission.started_at,
                    },
                    journeys=journeys,
                    samples=sample_documents,
                    calc_version=calc_version,
                    profile_version=profile_version,
                )

                model_by_grain = {
                    "intersection": ReplayV2IntersectionMetric5Min,
                    "link": ReplayV2LinkMetric5Min,
                    "lane": ReplayV2LaneMetric5Min,
                    "turn": ReplayV2TurnMetric5Min,
                }
                for model in model_by_grain.values():
                    await session.execute(delete(model).where(model.mission_id == mission_id))
                await session.flush()
                for grain, model in model_by_grain.items():
                    for row in facts[grain]:
                        dimension = (
                            row.get("link_id")
                            or row.get("lane_id")
                            or row.get("movement_key")
                            or "intersection"
                        )
                        session.add(
                            model(
                                id=_fact_id(
                                    "aggregate",
                                    grain,
                                    mission_id,
                                    row["window_start"],
                                    dimension,
                                    calc_version,
                                ),
                                **row,
                            )
                        )
                await session.flush()
                await self._rebuild_typical_matrix(
                    session,
                    source_profile_id=mission.source_profile_id,
                    calc_version=calc_version,
                    profile_version=profile_version,
                )

    async def _rebuild_typical_matrix(
        self,
        session,
        *,
        source_profile_id: str,
        calc_version: str,
        profile_version: str,
    ) -> None:
        """Recompute one source's typical matrix from actual five-minute facts."""

        actual = (
            (
                await session.execute(
                    select(ReplayV2IntersectionMetric5Min).where(
                        ReplayV2IntersectionMetric5Min.source_profile_id == source_profile_id,
                        ReplayV2IntersectionMetric5Min.calc_version == calc_version,
                    )
                )
            )
            .scalars()
            .all()
        )
        grouped: dict[tuple[str, int, int], list] = {}
        for row in actual:
            key = (
                row.inter_id,
                row.window_start.weekday(),
                row.window_start.hour * 12 + row.window_start.minute // 5,
            )
            grouped.setdefault(key, []).append(row)

        await session.execute(
            delete(ReplayV2InterEvaluation5MinMM).where(
                ReplayV2InterEvaluation5MinMM.source_profile_id == source_profile_id,
                ReplayV2InterEvaluation5MinMM.profile_version == profile_version,
            )
        )
        for (inter_id, day_of_week, step_index), rows in grouped.items():
            vehicle_values = [
                float(row.vehicle_count) for row in rows if row.vehicle_count is not None
            ]
            speed_values = [
                float(row.avg_speed_kmh) for row in rows if row.avg_speed_kmh is not None
            ]
            session.add(
                ReplayV2InterEvaluation5MinMM(
                    id=_fact_id(
                        "typical",
                        source_profile_id,
                        inter_id,
                        day_of_week,
                        step_index,
                        profile_version,
                    ),
                    inter_id=inter_id,
                    source_profile_id=source_profile_id,
                    day_of_week=day_of_week,
                    step_index=step_index,
                    profile_version=profile_version,
                    sample_days=len({row.window_start.date() for row in rows}),
                    vehicle_count=(sum(vehicle_values) / len(vehicle_values))
                    if vehicle_values
                    else None,
                    avg_speed_kmh=(sum(speed_values) / len(speed_values)) if speed_values else None,
                    saturation=None,
                    saturation_reason="lane_capacity_unavailable",
                    quality_status="estimated",
                )
            )

    async def mark_dispatched(self, source_system: str, message_id: str) -> None:
        async with self._session_maker() as session:
            await session.execute(
                update(ReplayV2MessageInbox)
                .where(ReplayV2MessageInbox.message_id == message_id)
                .values(status="dispatched")
            )
            await session.commit()

    async def mark_dispatch_failed(
        self, source_system: str, message_id: str, error: Exception
    ) -> None:
        async with self._session_maker() as session:
            await session.execute(
                update(ReplayV2MessageInbox)
                .where(ReplayV2MessageInbox.message_id == message_id)
                .values(status="dispatch_failed")
            )
            await session.commit()

    async def quarantine(self, envelope: MessageEnvelope, error: MetricContractError) -> str:
        dead_letter_id = _fact_id("dead", envelope.topic, envelope.partition, envelope.offset)
        async with self._session_maker() as session:
            session.add(
                ReplayV2MessageDeadLetter(
                    id=dead_letter_id,
                    topic=envelope.topic,
                    partition=envelope.partition,
                    offset=envelope.offset,
                    reason_code=type(error).__name__,
                    reason_detail=str(error),
                    payload=envelope.payload,
                    quarantined_at=datetime.now(UTC),
                )
            )
            payload = envelope.payload
            if payload.get('transport_version') == 'uav-fixed/v2' and payload.get('message_id'):
                receipt = await session.get(ReplayV2IngestReceipt, payload['message_id'])
                if receipt is None:
                    session.add(ReplayV2IngestReceipt(message_id=payload['message_id'], message_hash=_hash(payload),
                        deployment_id=str(payload.get('deployment_id') or 'local'), status='quarantined', committed_at=datetime.now(UTC)))
            await session.commit()
        return dead_letter_id

    async def capabilities(self) -> dict[str, bool]:
        async with self._session_maker() as session:
            enabled = await session.scalar(
                text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='timescaledb')")
            )
        return {"postgresql": True, "timescaledb": bool(enabled)}
