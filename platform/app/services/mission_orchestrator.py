"""Persistent FlightPlan/Mission orchestration behind one small interface."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.models.mission import (
    DroneRecord,
    FlightPlanRecord,
    MissionRecord,
    PipelineRecord,
    RoadContextSnapshot,
    TelemetrySourceRecord,
    VideoSourceRecord,
)
from app.schemas.mission import (
    DroneCreate,
    DroneUpdate,
    FlightPlanCreate,
    FlightPlanUpdate,
    MissionCreate,
    SourcePairCreate,
    SourcePairUpdate,
)
from app.services.pipeline_manager import detector_video_stream_url
from app.services.road_context import RoadContext

logger = logging.getLogger(__name__)


class MissionError(RuntimeError):
    def __init__(self, detail: str, status_code: int = 422, code: str = "mission_invalid"):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.code = code


class PipelineRuntimeAdapter(Protocol):
    async def start(self, **kwargs) -> dict: ...
    async def stop(self, pipeline_id: str) -> dict | None: ...
    def get(self, pipeline_id: str) -> dict | None: ...


class PipelineManagerAdapter:
    def __init__(self, manager):
        self._manager = manager

    async def start(self, **kwargs) -> dict:
        pipeline = await self._manager.start_pipeline(**kwargs)
        return pipeline.to_dict()

    async def stop(self, pipeline_id: str) -> dict | None:
        pipeline = await self._manager.stop_pipeline(pipeline_id)
        return pipeline.to_dict() if pipeline else None

    def get(self, pipeline_id: str) -> dict | None:
        pipeline = self._manager.get_pipeline(pipeline_id)
        return pipeline.to_dict() if pipeline else None


@dataclass(frozen=True)
class Occurrence:
    start_at: datetime
    end_at: datetime


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _now() -> datetime:
    return datetime.now(UTC)


def _runtime_missing_grace_expired(
    mission: MissionRecord,
    now: datetime,
    grace_sec: float | None = None,
) -> bool:
    started_at = _utc(mission.actual_start_at or mission.scheduled_start_at)
    missing_age = max(timedelta(0), _utc(now) - started_at)
    grace = (
        settings.mission_pipeline_missing_grace_sec
        if grace_sec is None
        else max(float(grace_sec), 0.0)
    )
    return missing_age >= timedelta(seconds=grace)


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


def _tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise MissionError(f"unknown timezone: {name}", code="timezone_invalid") from exc


def schedule_occurrences(
    schedule: dict,
    timezone: str,
    start: datetime,
    end: datetime,
    limit: int = 100,
) -> list[Occurrence]:
    """Expand once/weekly schedules into UTC windows, including cross-midnight."""
    start, end = _utc(start), _utc(end)
    if schedule["type"] == "once":
        occurrence = Occurrence(_utc(datetime.fromisoformat(schedule["start_at"])), _utc(datetime.fromisoformat(schedule["end_at"])))
        return [occurrence] if occurrence.end_at >= start and occurrence.start_at <= end else []

    zone = _tz(timezone)
    local_cursor = start.astimezone(zone).date() - timedelta(days=1)
    local_end = end.astimezone(zone).date() + timedelta(days=1)
    effective_from = date.fromisoformat(schedule["effective_from"])
    effective_to = date.fromisoformat(schedule["effective_to"]) if schedule.get("effective_to") else None
    exceptions = {date.fromisoformat(value) for value in schedule.get("exceptions", [])}
    weekdays = set(schedule["weekdays"])
    local_start = time.fromisoformat(schedule["local_start"])
    local_finish = time.fromisoformat(schedule["local_end"])
    result: list[Occurrence] = []
    while local_cursor <= local_end and len(result) < limit:
        valid = (
            local_cursor >= effective_from
            and (effective_to is None or local_cursor <= effective_to)
            and local_cursor.weekday() in weekdays
            and local_cursor not in exceptions
        )
        if valid:
            begins = datetime.combine(local_cursor, local_start, zone)
            finish_date = local_cursor + timedelta(days=1) if local_finish <= local_start else local_cursor
            finishes = datetime.combine(finish_date, local_finish, zone)
            occurrence = Occurrence(begins.astimezone(UTC), finishes.astimezone(UTC))
            if occurrence.end_at >= start and occurrence.start_at <= end:
                result.append(occurrence)
        local_cursor += timedelta(days=1)
    return result


def _schedule_payload(schedule) -> dict:
    return schedule.model_dump(mode="json")


def _masked_location(location: str) -> str:
    parsed = urlsplit(location)
    if parsed.scheme and parsed.netloc:
        host = parsed.hostname or "hidden"
        port = f":{parsed.port}" if parsed.port else ""
        return f"{parsed.scheme}://{host}{port}/***"
    return Path(location).name or "***"


class SourceValidator:
    def __init__(self, roots: list[str] | None = None):
        project_root = Path(
            os.environ.get("PIPELINE_PROJECT_ROOT", Path(__file__).resolve().parents[3])
        ).resolve()
        self._project_root = project_root
        configured = roots if roots is not None else settings.uav_local_asset_roots
        self._roots = tuple(
            (project_root / root).resolve() if not Path(root).is_absolute() else Path(root).resolve()
            for root in configured
        )

    def resolve_local(self, location: str, suffix: str | tuple[str, ...]) -> Path:
        candidate = Path(location)
        resolved = (
            (self._project_root / candidate).resolve()
            if not candidate.is_absolute()
            else candidate.resolve()
        )
        suffixes = (suffix,) if isinstance(suffix, str) else suffix
        if resolved.suffix.lower() not in suffixes:
            raise MissionError(f"expected {'/'.join(suffixes)} source", code="source_type_mismatch")
        if not any(root == resolved or root in resolved.parents for root in self._roots):
            raise MissionError("source path is outside UAV_LOCAL_ASSET_ROOTS", code="source_outside_allowlist")
        if not resolved.is_file() or not os.access(resolved, os.R_OK):
            raise MissionError("source file is missing or unreadable", code="source_unreadable")
        return resolved

    @staticmethod
    def validate_dji_json(path: Path) -> None:
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise MissionError("DJI telemetry JSON cannot be parsed", code="telemetry_json_invalid") from exc
        records = payload.get("data") if isinstance(payload, dict) else payload
        if not isinstance(records, list) or not records:
            raise MissionError("DJI telemetry JSON has no records", code="telemetry_json_empty")
        sample = records[0]
        if not isinstance(sample, dict) or not (
            {"time", "value"}.issubset(sample) or "timestamp" in sample
        ):
            raise MissionError("DJI telemetry JSON schema is unsupported", code="telemetry_json_schema_invalid")

    def validate(self, video: VideoSourceRecord, telemetry: TelemetrySourceRecord) -> tuple[str, str | None]:
        try:
            if video.mode != telemetry.mode:
                raise MissionError("video and telemetry modes differ", code="source_mode_mismatch")
            if video.mode == "local":
                self.resolve_local(video.location, ".mp4")
                if telemetry.source_type == "srt":
                    self.resolve_local(telemetry.location, ".srt")
                elif telemetry.source_type == "file":
                    path = self.resolve_local(telemetry.location, (".json", ".txt"))
                    self.validate_dji_json(path)
                else:
                    raise MissionError("local telemetry must use srt or file", code="source_type_mismatch")
                return "valid", None
            if urlsplit(video.location).scheme.lower() != "rtsp":
                raise MissionError("realtime video must use rtsp", code="video_scheme_invalid")
            if urlsplit(telemetry.location).scheme.lower() not in {"mqtt", "mqtts"}:
                raise MissionError("realtime telemetry must use mqtt", code="telemetry_scheme_invalid")
            return "degraded", "realtime_reachability_unverified"
        except MissionError as exc:
            return "invalid", exc.code


class MissionOrchestrator:
    """Own persistence, scheduling, recovery, and PipelineManager coordination."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        pipeline: PipelineRuntimeAdapter,
        road_context: RoadContext,
        poll_sec: float = 5.0,
        source_validator: SourceValidator | None = None,
    ):
        self._sessions = session_factory
        self._pipeline = pipeline
        self._road_context = road_context
        self._poll_sec = poll_sec
        self._validator = source_validator or SourceValidator()
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        await self.recover()
        self._task = asyncio.create_task(self._loop(), name="uav-mission-scheduler")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def _loop(self) -> None:
        while self._running:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("mission scheduler iteration failed")
            await asyncio.sleep(self._poll_sec)

    # -- Read interface -------------------------------------------------

    async def list_drones(self) -> list[dict]:
        async with self._sessions() as session:
            rows = (await session.execute(select(DroneRecord).order_by(DroneRecord.id))).scalars().all()
            result = []
            for row in rows:
                payload = self._drone_dict(row)
                if row.default_inter_id:
                    context = (
                        await session.execute(
                            select(RoadContextSnapshot)
                            .where(RoadContextSnapshot.inter_id == row.default_inter_id)
                            .order_by(RoadContextSnapshot.created_at.desc())
                            .limit(1)
                        )
                    ).scalar_one_or_none()
                    if context:
                        payload["default_road_data_version"] = context.road_data_version
                        payload["intersection_name"] = (
                            (context.payload or {}).get("intersection") or {}
                        ).get("name") or row.default_inter_id
                        payload["road_context_quality"] = context.quality_status
                result.append(payload)
            return result

    async def get_drone(self, drone_id: str) -> dict:
        async with self._sessions() as session:
            row = await session.get(DroneRecord, drone_id)
            if row is None:
                raise MissionError("drone not found", 404, "drone_not_found")
            return self._drone_dict(row)

    async def list_sources(self, drone_id: str | None = None) -> list[dict]:
        async with self._sessions() as session:
            stmt = select(VideoSourceRecord).order_by(VideoSourceRecord.created_at.desc())
            if drone_id:
                stmt = stmt.where(VideoSourceRecord.drone_id == drone_id)
            videos = (await session.execute(stmt)).scalars().all()
            result = []
            for video in videos:
                telemetry = (
                    await session.execute(
                        select(TelemetrySourceRecord).where(TelemetrySourceRecord.profile_id == video.profile_id)
                    )
                ).scalar_one_or_none()
                if telemetry:
                    result.append(self._source_dict(video, telemetry))
            return result

    async def list_plans(self) -> list[dict]:
        async with self._sessions() as session:
            rows = (await session.execute(select(FlightPlanRecord).order_by(FlightPlanRecord.created_at.desc()))).scalars().all()
            return [self._plan_dict(row) for row in rows]

    async def get_plan(self, plan_id: str) -> dict:
        async with self._sessions() as session:
            plan = await session.get(FlightPlanRecord, plan_id)
            if plan is None:
                raise MissionError("flight plan not found", 404, "flight_plan_not_found")
            return self._plan_dict(plan)

    async def list_missions(self, status: str | None = None) -> list[dict]:
        async with self._sessions() as session:
            stmt = select(MissionRecord).order_by(MissionRecord.created_at.desc())
            if status:
                stmt = stmt.where(MissionRecord.status == status)
            rows = (await session.execute(stmt)).scalars().all()
            return [await self._mission_dict(session, row) for row in rows]

    async def get_mission(self, mission_id: str) -> dict:
        async with self._sessions() as session:
            mission = await session.get(MissionRecord, mission_id)
            if mission is None:
                raise MissionError("mission not found", 404, "mission_not_found")
            return await self._mission_dict(session, mission)

    async def preview(self, plan_id: str, count: int = 10, from_at: datetime | None = None) -> list[dict]:
        async with self._sessions() as session:
            plan = await session.get(FlightPlanRecord, plan_id)
            if plan is None:
                raise MissionError("flight plan not found", 404, "flight_plan_not_found")
            start = _utc(from_at or _now())
            occurrences = schedule_occurrences(plan.schedule, plan.timezone, start, start + timedelta(days=90), count)
            return [{"start_at": item.start_at.isoformat(), "end_at": item.end_at.isoformat()} for item in occurrences[:count]]

    # -- Mutation interface ---------------------------------------------

    async def create_drone(self, body: DroneCreate) -> dict:
        async with self._sessions() as session:
            if await session.get(DroneRecord, body.id):
                raise MissionError("drone already exists", 409, "drone_exists")
            row = DroneRecord(**body.model_dump())
            session.add(row)
            await session.commit()
            return self._drone_dict(row)

    async def update_drone(self, drone_id: str, body: DroneUpdate) -> dict:
        async with self._sessions() as session:
            row = await session.get(DroneRecord, drone_id)
            if row is None:
                raise MissionError("drone not found", 404, "drone_not_found")
            self._check_revision(row.revision, body.revision)
            for key, value in body.model_dump(exclude={"revision"}, exclude_unset=True).items():
                setattr(row, key, value)
            row.revision += 1
            await session.commit()
            return self._drone_dict(row)

    async def create_source_pair(self, drone_id: str, body: SourcePairCreate) -> dict:
        async with self._sessions() as session:
            drone = await session.get(DroneRecord, drone_id)
            if drone is None:
                raise MissionError("drone not found", 404, "drone_not_found")
            profile_id = body.profile_id or _id("SRC")
            if await self._pair(session, profile_id):
                raise MissionError("source profile already exists", 409, "source_profile_exists")
            video = VideoSourceRecord(
                id=_id("VID"), profile_id=profile_id, drone_id=drone_id, mode=body.mode,
                source_type=body.video.source_type, location=body.video.location,
                credential_ref=body.video.credential_ref, enabled=body.enabled,
            )
            telemetry = TelemetrySourceRecord(
                id=_id("TEL"), profile_id=profile_id, drone_id=drone_id, mode=body.mode,
                source_type=body.telemetry.source_type, location=body.telemetry.location,
                credential_ref=body.telemetry.credential_ref,
                config=self._telemetry_config(body.telemetry), enabled=body.enabled,
            )
            session.add_all([video, telemetry])
            await session.flush()
            self._apply_validation(video, telemetry)
            if body.set_default:
                drone.default_video_source_id = video.id
                drone.default_telemetry_source_id = telemetry.id
                drone.revision += 1
            await session.commit()
            return self._source_dict(video, telemetry)

    async def update_source_pair(self, drone_id: str, profile_id: str, body: SourcePairUpdate) -> dict:
        async with self._sessions() as session:
            pair = await self._pair(session, profile_id)
            if pair is None or pair[0].drone_id != drone_id:
                raise MissionError("source profile not found", 404, "source_profile_not_found")
            video, telemetry = pair
            self._check_revision(max(video.revision, telemetry.revision), body.revision)
            if body.video:
                video.source_type, video.location, video.credential_ref = (
                    body.video.source_type, body.video.location, body.video.credential_ref
                )
            if body.telemetry:
                telemetry.source_type, telemetry.location, telemetry.credential_ref = (
                    body.telemetry.source_type, body.telemetry.location, body.telemetry.credential_ref
                )
                telemetry.config = self._telemetry_config(body.telemetry)
            if body.enabled is not None:
                video.enabled = telemetry.enabled = body.enabled
            video.revision += 1
            telemetry.revision += 1
            self._apply_validation(video, telemetry)
            if body.set_default:
                drone = await session.get(DroneRecord, drone_id)
                drone.default_video_source_id = video.id
                drone.default_telemetry_source_id = telemetry.id
                drone.revision += 1
            await session.commit()
            return self._source_dict(video, telemetry)

    async def validate_source_pair(self, drone_id: str, profile_id: str) -> dict:
        async with self._sessions() as session:
            pair = await self._pair(session, profile_id)
            if pair is None or pair[0].drone_id != drone_id:
                raise MissionError("source profile not found", 404, "source_profile_not_found")
            self._apply_validation(*pair)
            await session.commit()
            return self._source_dict(*pair)

    async def create_plan(self, body: FlightPlanCreate, actor_id: int | None = None) -> dict:
        async with self._sessions() as session:
            drone = await session.get(DroneRecord, body.drone_id)
            if drone is None:
                raise MissionError("drone not found", 404, "drone_not_found")
            pair = await self._pair(session, body.source_profile_id)
            if pair is None or pair[0].drone_id != body.drone_id:
                raise MissionError("source profile not found for drone", 422, "source_profile_invalid")
            _tz(body.timezone)
            row = FlightPlanRecord(
                id=_id("PLAN"), name=body.name, drone_id=body.drone_id,
                video_source_id=pair[0].id, telemetry_source_id=pair[1].id,
                inter_id=body.inter_id, road_data_version=body.road_data_version,
                ai_mode=body.ai_mode, schedule_type=body.schedule.type,
                schedule=_schedule_payload(body.schedule), timezone=body.timezone,
                state="draft", created_by=actor_id,
            )
            session.add(row)
            await session.commit()
            return self._plan_dict(row)

    async def update_plan(self, plan_id: str, body: FlightPlanUpdate) -> dict:
        async with self._sessions() as session:
            plan = await session.get(FlightPlanRecord, plan_id)
            if plan is None:
                raise MissionError("flight plan not found", 404, "flight_plan_not_found")
            if plan.state not in {"draft", "paused", "enabled"}:
                raise MissionError("flight plan cannot be edited in current state", code="plan_state_invalid")
            self._check_revision(plan.revision, body.revision)
            values = body.model_dump(exclude={"revision", "schedule", "source_profile_id"}, exclude_unset=True)
            for key, value in values.items():
                setattr(plan, key, value)
            if body.schedule is not None:
                plan.schedule = _schedule_payload(body.schedule)
                plan.schedule_type = body.schedule.type
            if body.source_profile_id is not None:
                pair = await self._pair(session, body.source_profile_id)
                if pair is None or pair[0].drone_id != plan.drone_id:
                    raise MissionError("source profile not found for drone", code="source_profile_invalid")
                plan.video_source_id, plan.telemetry_source_id = pair[0].id, pair[1].id
            _tz(plan.timezone)
            plan.revision += 1
            await session.commit()
            return self._plan_dict(plan)

    async def change_plan_state(self, plan_id: str, revision: int, action: str) -> dict:
        transitions = {
            "enable": ({"draft", "paused"}, "enabled"),
            "pause": ({"enabled"}, "paused"),
            "retire": ({"draft", "enabled", "paused", "completed"}, "retired"),
        }
        if action not in transitions:
            raise MissionError("unsupported flight plan action")
        async with self._sessions() as session:
            plan = await session.get(FlightPlanRecord, plan_id)
            if plan is None:
                raise MissionError("flight plan not found", 404, "flight_plan_not_found")
            self._check_revision(plan.revision, revision)
            allowed, target = transitions[action]
            if plan.state not in allowed:
                raise MissionError("flight plan action is not allowed", code="plan_state_invalid")
            if action == "enable":
                await self._validate_plan(session, plan)
                await self._reject_overlap(session, plan)
            plan.state = target
            plan.revision += 1
            await session.commit()
            return self._plan_dict(plan)

    async def delete_plan(self, plan_id: str) -> None:
        async with self._sessions() as session:
            plan = await session.get(FlightPlanRecord, plan_id)
            if plan is None:
                raise MissionError("flight plan not found", 404, "flight_plan_not_found")
            if plan.state != "draft":
                raise MissionError("only draft flight plans can be deleted", code="plan_state_invalid")
            await session.delete(plan)
            await session.commit()

    async def create_manual_mission(self, body: MissionCreate, actor_id: int | None = None) -> dict:
        now = _now()
        end_at = _utc(body.scheduled_end_at) if body.scheduled_end_at else now + timedelta(hours=1)
        if end_at <= now:
            raise MissionError("scheduled_end_at must be in the future")
        async with self._sessions() as session:
            drone = await session.get(DroneRecord, body.drone_id)
            if drone is None:
                # Compatibility: persist previously implicit devices instead of recreating an in-memory truth.
                drone = DroneRecord(id=body.drone_id, name=body.drone_id, enabled=True)
                session.add(drone)
                await session.flush()
            if not drone.enabled:
                raise MissionError("drone is disabled", code="drone_disabled")
            active = (
                await session.execute(
                    select(MissionRecord).where(
                        MissionRecord.drone_id == body.drone_id,
                        MissionRecord.status.in_(("pending", "starting", "running")),
                    )
                )
            ).scalars().first()
            if active is not None:
                raise MissionError(
                    f"drone already has active mission {active.id}",
                    409,
                    "drone_mission_active",
                )
            snapshot: dict = {"quality_status": "unverified"}
            video_id = telemetry_id = None
            pair = await self._pair(session, body.source_profile_id)
            if pair is None or pair[0].drone_id != body.drone_id:
                raise MissionError("source profile not found for drone", code="source_profile_invalid")
            if pair[0].validation_status == "invalid" or pair[1].validation_status == "invalid":
                raise MissionError("source profile is invalid", code="source_profile_invalid")
            video_id, telemetry_id = pair[0].id, pair[1].id
            snapshot["source_profile_id"] = body.source_profile_id
            mission = MissionRecord(
                id=_id("MSN"), name=body.name or "手动 Mission", trigger_type="manual",
                drone_id=body.drone_id, video_source_id=video_id, telemetry_source_id=telemetry_id,
                inter_id=body.inter_id or "", road_data_version=body.road_data_version or "unverified",
                scheduled_start_at=now, scheduled_end_at=end_at, status="starting",
                context_snapshot=snapshot, created_by=actor_id,
            )
            session.add(mission)
            await session.flush()
            await self._start_mission(session, mission)
            await session.commit()
            return await self._mission_dict(session, mission)

    async def stop_mission(self, mission_id: str, reason: str) -> dict:
        async with self._sessions() as session:
            mission = await session.get(MissionRecord, mission_id)
            if mission is None:
                raise MissionError("mission not found", 404, "mission_not_found")
            if mission.status not in {"pending", "starting", "running"}:
                raise MissionError("mission cannot be stopped", code="mission_state_invalid")
            if mission.pipeline_id:
                await self._pipeline.stop(mission.pipeline_id)
            mission.status = "cancelled"
            mission.reason_code = "manual_stop"
            mission.error_message = reason
            mission.actual_end_at = _now()
            await self._sync_pipeline_stop(session, mission, "stopped")
            await session.commit()
            return await self._mission_dict(session, mission)

    async def retry_mission(self, mission_id: str, reason: str, actor_id: int | None = None) -> dict:
        async with self._sessions() as session:
            original = await session.get(MissionRecord, mission_id)
            if original is None:
                raise MissionError("mission not found", 404, "mission_not_found")
            if original.status != "failed":
                raise MissionError("only failed missions can be retried", code="mission_state_invalid")
            now = _now()
            duration = max(original.scheduled_end_at - original.scheduled_start_at, timedelta(minutes=1))
            retry = MissionRecord(
                id=_id("MSN"), name=f"{original.name} · retry {original.retry_index + 1}",
                parent_mission_id=original.id, retry_index=original.retry_index + 1,
                trigger_type="retry", drone_id=original.drone_id,
                video_source_id=original.video_source_id, telemetry_source_id=original.telemetry_source_id,
                inter_id=original.inter_id, road_data_version=original.road_data_version,
                scheduled_start_at=now, scheduled_end_at=now + duration, status="starting",
                context_snapshot={**original.context_snapshot, "retry_reason": reason}, created_by=actor_id,
            )
            session.add(retry)
            await session.flush()
            await self._start_mission(session, retry)
            await session.commit()
            return await self._mission_dict(session, retry)

    # -- Scheduler ------------------------------------------------------

    async def recover(self) -> None:
        await self.run_once(_now(), recovery=True)

    async def run_once(self, at: datetime | None = None, recovery: bool = False) -> int:
        now = _utc(at or _now())
        progressed = 0
        async with self._sessions() as session:
            due_to_stop = (
                await session.execute(
                    select(MissionRecord).where(
                        MissionRecord.status == "running", MissionRecord.scheduled_end_at <= now
                    )
                )
            ).scalars().all()
            for mission in due_to_stop:
                if mission.pipeline_id:
                    await self._pipeline.stop(mission.pipeline_id)
                mission.status = "completed"
                mission.reason_code = "window_ended"
                mission.actual_end_at = now
                await self._sync_pipeline_stop(session, mission, "stopped")
                progressed += 1

            if recovery:
                active = (
                    await session.execute(
                        select(MissionRecord).where(
                            MissionRecord.status.in_(["starting", "running"]),
                            MissionRecord.scheduled_start_at <= now,
                            MissionRecord.scheduled_end_at > now,
                        )
                    )
                ).scalars().all()
                for mission in active:
                    runtime = self._pipeline.get(mission.pipeline_id) if mission.pipeline_id else None
                    if not runtime or runtime.get("status") != "running":
                        await self._start_mission(session, mission)
                        progressed += 1
            else:
                active = (
                    await session.execute(
                        select(MissionRecord).where(
                            MissionRecord.status == "running",
                            MissionRecord.scheduled_end_at > now,
                        )
                    )
                ).scalars().all()
                for mission in active:
                    runtime = self._pipeline.get(mission.pipeline_id) if mission.pipeline_id else None
                    runtime_status = runtime.get("status") if runtime else None
                    if runtime_status == "stopped":
                        mission.status = "completed"
                        mission.reason_code = "source_eof"
                        mission.actual_end_at = now
                        await self._sync_pipeline_stop(session, mission, "stopped")
                        progressed += 1
                    elif runtime_status == "error":
                        mission.status = "failed"
                        mission.reason_code = "pipeline_error"
                        mission.error_message = str(runtime.get("error_message") or "pipeline exited unexpectedly")[:2000]
                        mission.actual_end_at = now
                        await self._sync_pipeline_stop(
                            session,
                            mission,
                            "error",
                            error_message=mission.error_message,
                        )
                        progressed += 1
                    elif runtime is None:
                        started_at = _utc(
                            mission.actual_start_at or mission.scheduled_start_at
                        )
                        missing_age = max(
                            timedelta(0),
                            now - started_at,
                        )
                        missing_is_terminal = _runtime_missing_grace_expired(
                            mission, now
                        )
                        logger.warning(
                            "Mission %s runtime %s unavailable %.1fs after startup "
                            "(grace=%.1fs, terminal=%s)",
                            mission.id,
                            mission.pipeline_id,
                            missing_age.total_seconds(),
                            settings.mission_pipeline_missing_grace_sec,
                            missing_is_terminal,
                        )
                        if not missing_is_terminal:
                            continue
                        mission.status = "failed"
                        mission.reason_code = "pipeline_runtime_missing"
                        mission.error_message = "pipeline runtime is missing before the scheduled window ended"
                        mission.actual_end_at = now
                        await self._sync_pipeline_stop(
                            session,
                            mission,
                            "error",
                            error_message=mission.error_message,
                        )
                        progressed += 1

            plans = (
                await session.execute(select(FlightPlanRecord).where(FlightPlanRecord.state == "enabled"))
            ).scalars().all()
            for plan in plans:
                occurrences = schedule_occurrences(
                    plan.schedule, plan.timezone, now - timedelta(days=1), now + timedelta(seconds=1), 16
                )
                for occurrence in occurrences:
                    if occurrence.start_at <= now < occurrence.end_at:
                        progressed += await self._materialize_occurrence(session, plan, occurrence, now)
                    elif recovery and occurrence.end_at <= now:
                        exists = await self._occurrence_mission(session, plan.id, occurrence.start_at)
                        if exists is None and plan.schedule_type == "once":
                            session.add(self._mission_from_plan(plan, occurrence, "skipped", "window_missed"))
                            progressed += 1
            await session.commit()
        return progressed

    async def _materialize_occurrence(
        self, session: AsyncSession, plan: FlightPlanRecord, occurrence: Occurrence, now: datetime
    ) -> int:
        key = f"{plan.id}:{occurrence.start_at.isoformat()}"
        lock = await session.scalar(text("SELECT pg_try_advisory_xact_lock(hashtext(:key))"), {"key": key})
        if not lock:
            return 0
        mission = await self._occurrence_mission(session, plan.id, occurrence.start_at)
        if mission is not None:
            return 0
        mission = self._mission_from_plan(plan, occurrence, "starting")
        session.add(mission)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            return 0
        await self._start_mission(session, mission)
        return 1

    # -- Internal implementation ---------------------------------------

    async def _start_mission(self, session: AsyncSession, mission: MissionRecord) -> None:
        try:
            active = (
                await session.execute(
                    select(MissionRecord).where(
                        MissionRecord.drone_id == mission.drone_id,
                        MissionRecord.id != mission.id,
                        MissionRecord.status.in_(("pending", "starting", "running")),
                    )
                )
            ).scalars().first()
            if active is not None:
                mission.status = "failed"
                mission.reason_code = "drone_mission_active"
                mission.error_message = f"drone already has active mission {active.id}"
                return
            params = await self._runtime_params(session, mission)
            runtime = await self._pipeline.start(**params)
            mission.pipeline_id = runtime["pipeline_id"]
            mission.actual_start_at = _now()
            if runtime.get("status") == "running":
                mission.status = "running"
                mission.error_message = None
            else:
                mission.status = "failed"
                mission.reason_code = "pipeline_start_failed"
                mission.error_message = runtime.get("error_message") or "pipeline did not enter running state"
            record = (
                await session.execute(
                    select(PipelineRecord).where(PipelineRecord.mission_id == mission.id)
                )
            ).scalar_one_or_none()
            if record is None:
                record = PipelineRecord(id=runtime["pipeline_id"], mission_id=mission.id)
                session.add(record)
            else:
                # A Mission remains one business Pipeline; after process recovery
                # its runtime identifier and observed details are replaced in place.
                record.id = runtime["pipeline_id"]
            record.desired_status = "running"
            record.observed_status = runtime.get("status", "unknown")
            record.topic_name = runtime.get("topic_name", "")
            record.camera_id = runtime.get("camera_id")
            record.video_port = runtime.get("video_port")
            record.started_at = mission.actual_start_at
            record.stopped_at = None
            record.error_message = runtime.get("error_message") or None
        except Exception as exc:
            mission.status = "failed"
            mission.reason_code = "pipeline_start_failed"
            mission.error_message = str(exc)[:1000]

    async def _runtime_params(self, session: AsyncSession, mission: MissionRecord) -> dict:
        legacy = mission.context_snapshot.get("legacy_source")
        if legacy:
            raise MissionError("legacy source missions are retired; bind a SourceProfile", code="legacy_source_retired")
        video = await session.get(VideoSourceRecord, mission.video_source_id)
        telemetry = await session.get(TelemetrySourceRecord, mission.telemetry_source_id)
        if video is None or telemetry is None:
            raise MissionError("mission source snapshot cannot be resolved", code="source_missing")
        context = None
        if mission.road_data_version and mission.road_data_version != "unverified":
            try:
                context = await self._road_context.get(
                    mission.inter_id, mission.road_data_version
                )
            except LookupError:
                context = None
        runtime_map_bundle = (
            context.runtime_map_bundle
            if context is not None
            and context.map_status == "lane_verified"
            and context.runtime_map_bundle
            else None
        )
        mission.context_snapshot = {
            **mission.context_snapshot,
            **(
                {
                    "road_context": {
                        "inter_id": context.inter_id,
                        "road_data_version": context.road_data_version,
                        "checksum": context.checksum,
                        "quality_status": context.quality_status,
                        "map_version_id": context.map_version_id,
                        "runtime_status": "complete" if runtime_map_bundle else "unverified",
                    }
                }
                if context is not None
                else {}
            ),
            "source_profile_id": video.profile_id,
        }
        return {
            "drone_id": mission.drone_id, "intersection_id": mission.inter_id,
            "video_src": video.location,
            "telemetry_source": telemetry.source_type,
            "telemetry_file_path": telemetry.location if telemetry.mode == "local" else None,
            "telemetry_time_offset_sec": (telemetry.config or {}).get("time_offset_sec", 0.0),
            "telemetry_sync_tolerance_sec": (telemetry.config or {}).get("sync_tolerance_sec", 0.5),
            "mission_id": mission.id,
            "source_profile_id": video.profile_id,
            "inter_id": mission.inter_id,
            "road_data_version": (
                context.road_data_version if runtime_map_bundle else mission.road_data_version
            ),
            "road_context_status": "complete" if runtime_map_bundle else "missing",
            "quality_status": context.quality_status if runtime_map_bundle else "unverified",
            "runtime_map_bundle": runtime_map_bundle,
        }

    async def _validate_plan(self, session: AsyncSession, plan: FlightPlanRecord) -> None:
        drone = await session.get(DroneRecord, plan.drone_id)
        video = await session.get(VideoSourceRecord, plan.video_source_id)
        telemetry = await session.get(TelemetrySourceRecord, plan.telemetry_source_id)
        if not drone or not drone.enabled:
            raise MissionError("drone is missing or disabled", code="drone_disabled")
        if not video or not telemetry or not video.enabled or not telemetry.enabled:
            raise MissionError("source profile is missing or disabled", code="source_profile_invalid")
        if video.validation_status not in {"valid", "degraded"} or telemetry.validation_status not in {"valid", "degraded"}:
            raise MissionError("source profile must be validated before enable", code="source_profile_unverified")
        try:
            context = await self._road_context.get(plan.inter_id, plan.road_data_version)
        except LookupError as exc:
            raise MissionError(str(exc), code="road_context_unavailable") from exc
        if context.map_status != "lane_verified" or not context.runtime_map_bundle:
            raise MissionError(
                "flight plan requires a lane_verified channelized map",
                code="channelized_map_not_verified",
            )

    async def _reject_overlap(self, session: AsyncSession, plan: FlightPlanRecord) -> None:
        start = _now() - timedelta(days=1)
        end = start + timedelta(days=91)
        own = schedule_occurrences(plan.schedule, plan.timezone, start, end, 500)
        peers = (
            await session.execute(
                select(FlightPlanRecord).where(
                    FlightPlanRecord.id != plan.id,
                    FlightPlanRecord.drone_id == plan.drone_id,
                    FlightPlanRecord.state == "enabled",
                )
            )
        ).scalars().all()
        for peer in peers:
            for left in own:
                for right in schedule_occurrences(peer.schedule, peer.timezone, start, end, 500):
                    if left.start_at < right.end_at and right.start_at < left.end_at:
                        raise MissionError(
                            f"flight plan overlaps {peer.id} at {left.start_at.isoformat()}",
                            409, "flight_plan_overlap",
                        )

    async def _pair(
        self, session: AsyncSession, profile_id: str
    ) -> tuple[VideoSourceRecord, TelemetrySourceRecord] | None:
        video = (
            await session.execute(select(VideoSourceRecord).where(VideoSourceRecord.profile_id == profile_id))
        ).scalar_one_or_none()
        telemetry = (
            await session.execute(select(TelemetrySourceRecord).where(TelemetrySourceRecord.profile_id == profile_id))
        ).scalar_one_or_none()
        return (video, telemetry) if video and telemetry else None

    def _apply_validation(self, video: VideoSourceRecord, telemetry: TelemetrySourceRecord) -> None:
        status, code = self._validator.validate(video, telemetry)
        checked = _now()
        video.validation_status = telemetry.validation_status = status
        video.validation_error_code = telemetry.validation_error_code = code
        video.validated_at = telemetry.validated_at = checked

    @staticmethod
    def _telemetry_config(source) -> dict:
        return {
            "time_offset_sec": source.time_offset_sec if source.time_offset_sec is not None else 0.0,
            "sync_tolerance_sec": source.sync_tolerance_sec if source.sync_tolerance_sec is not None else 0.5,
        }

    async def _occurrence_mission(
        self, session: AsyncSession, plan_id: str, start_at: datetime
    ) -> MissionRecord | None:
        return (
            await session.execute(
                select(MissionRecord).where(
                    MissionRecord.flight_plan_id == plan_id,
                    MissionRecord.scheduled_start_at == start_at,
                )
            )
        ).scalar_one_or_none()

    def _mission_from_plan(
        self, plan: FlightPlanRecord, occurrence: Occurrence, status: str, reason: str | None = None
    ) -> MissionRecord:
        return MissionRecord(
            id=_id("MSN"), name=plan.name, flight_plan_id=plan.id, trigger_type="scheduled",
            drone_id=plan.drone_id, video_source_id=plan.video_source_id,
            telemetry_source_id=plan.telemetry_source_id, inter_id=plan.inter_id,
            road_data_version=plan.road_data_version, scheduled_start_at=occurrence.start_at,
            scheduled_end_at=occurrence.end_at, status=status, reason_code=reason,
            context_snapshot={"flight_plan_revision": plan.revision, "ai_mode": plan.ai_mode},
        )

    async def _sync_pipeline_stop(
        self,
        session: AsyncSession,
        mission: MissionRecord,
        observed: str,
        *,
        error_message: str | None = None,
    ) -> None:
        if not mission.pipeline_id:
            return
        record = await session.get(PipelineRecord, mission.pipeline_id)
        if record:
            record.desired_status = "stopped"
            record.observed_status = observed
            record.stopped_at = mission.actual_end_at or _now()
            if error_message is not None:
                record.error_message = error_message

    @staticmethod
    def _check_revision(actual: int, expected: int) -> None:
        if actual != expected:
            raise MissionError("revision conflict", 409, "revision_conflict")

    @staticmethod
    def _drone_dict(row: DroneRecord) -> dict:
        return {
            "id": row.id, "name": row.name, "model": row.model,
            "serial_number_masked": f"***{row.serial_number[-4:]}" if row.serial_number else None,
            "enabled": row.enabled, "default_inter_id": row.default_inter_id,
            "default_video_source_id": row.default_video_source_id,
            "default_telemetry_source_id": row.default_telemetry_source_id,
            "revision": row.revision, "created_at": row.created_at, "updated_at": row.updated_at,
        }

    @staticmethod
    def _source_dict(video: VideoSourceRecord, telemetry: TelemetrySourceRecord) -> dict:
        status = "invalid" if "invalid" in {video.validation_status, telemetry.validation_status} else (
            "degraded" if "degraded" in {video.validation_status, telemetry.validation_status} else video.validation_status
        )
        return {
            "profile_id": video.profile_id, "drone_id": video.drone_id, "mode": video.mode,
            "display_name": Path(video.location).stem,
            "enabled": video.enabled and telemetry.enabled, "validation_status": status,
            "validated_at": video.validated_at,
            "validation_error_code": video.validation_error_code or telemetry.validation_error_code,
            "revision": max(video.revision, telemetry.revision),
            "video": {
                "id": video.id, "source_type": video.source_type,
                "location_hint": _masked_location(video.location),
                "credential_ref_present": bool(video.credential_ref),
            },
            "telemetry": {
                "id": telemetry.id, "source_type": telemetry.source_type,
                "location_hint": _masked_location(telemetry.location),
                "credential_ref_present": bool(telemetry.credential_ref),
                "time_offset_sec": (telemetry.config or {}).get("time_offset_sec", 0.0),
                "sync_tolerance_sec": (telemetry.config or {}).get("sync_tolerance_sec", 0.5),
            },
        }

    @staticmethod
    def _plan_dict(row: FlightPlanRecord) -> dict:
        return {
            "id": row.id, "name": row.name, "drone_id": row.drone_id,
            "source_profile": {"video_source_id": row.video_source_id, "telemetry_source_id": row.telemetry_source_id},
            "inter_id": row.inter_id, "road_data_version": row.road_data_version,
            "ai_mode": row.ai_mode, "schedule": row.schedule, "timezone": row.timezone,
            "state": row.state, "revision": row.revision,
            "created_at": row.created_at, "updated_at": row.updated_at,
        }

    async def _mission_dict(self, session: AsyncSession, row: MissionRecord) -> dict:
        pipeline = await session.get(PipelineRecord, row.pipeline_id) if row.pipeline_id else None
        runtime = self._pipeline.get(row.pipeline_id) if row.pipeline_id else None
        video_stream_url = (runtime or {}).get("video_stream_url")
        if not video_stream_url and pipeline and pipeline.video_port:
            video_stream_url = detector_video_stream_url(pipeline.video_port)
        return {
            "id": row.id, "name": row.name, "flight_plan_id": row.flight_plan_id,
            "parent_mission_id": row.parent_mission_id, "retry_index": row.retry_index,
            "trigger_type": row.trigger_type, "drone_id": row.drone_id,
            "inter_id": row.inter_id, "road_data_version": row.road_data_version,
            "scheduled_start_at": row.scheduled_start_at, "scheduled_end_at": row.scheduled_end_at,
            "actual_start_at": row.actual_start_at, "actual_end_at": row.actual_end_at,
            "status": row.status, "reason_code": row.reason_code,
            "error_message": row.error_message, "pipeline_id": row.pipeline_id,
            "pipeline": {
                "id": pipeline.id, "desired_status": pipeline.desired_status,
                "observed_status": pipeline.observed_status, "topic_name": pipeline.topic_name,
                "camera_id": pipeline.camera_id, "video_port": pipeline.video_port,
                "video_stream_url": video_stream_url,
                "error_message": pipeline.error_message,
            } if pipeline else None,
            "context_snapshot": row.context_snapshot,
            "created_at": row.created_at, "updated_at": row.updated_at,
        }
