"""Persistent drone, source, FlightPlan, Mission, and telemetry endpoints."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.drone_store import (
    DRONES,
)
from app.models.drone_store import (
    get_drone_trajectory as read_drone_trajectory,
)
from app.models.drone_store import (
    get_telemetry_history as read_telemetry_history,
)
from app.models.metrics import ConflictEvent, TrackEvent, TrafficMetric
from app.models.mission import (
    FlightSegmentRecord,
    LaneAnnotationTaskRecord,
    MissionRecord,
    TelemetrySourceRecord,
    VideoSourceRecord,
)
from app.models.survey import (
    SceneAnnotation,
    SurveyCaptureBatch,
    SurveyFrame,
    SurveyReport,
    SurveyTask,
)
from app.schemas.mission import (
    DroneCreate,
    DroneUpdate,
    FlightPlanCreate,
    FlightPlanUpdate,
    MissionAction,
    MissionCreate,
    RevisionAction,
    SourcePairCreate,
    SourcePairUpdate,
)
from app.services.mission_orchestrator import MissionError, MissionOrchestrator

router = APIRouter(prefix="", tags=["drones"])
telemetry_router = APIRouter(prefix="/telemetry", tags=["telemetry"])


def _orchestrator(request: Request) -> MissionOrchestrator:
    orchestrator = getattr(request.app.state, "mission_orchestrator", None)
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="MissionOrchestrator unavailable")
    return orchestrator


def _admin(request: Request) -> int | None:
    user = getattr(request.state, "user", None)
    if user is None:  # Small test apps do not install the production auth middleware.
        return None
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Administrator role required")
    try:
        return int(user.get("sub"))
    except (TypeError, ValueError):
        return None


async def _call(awaitable):
    try:
        return await awaitable
    except MissionError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.detail},
        ) from exc


def _runtime_drone(payload: dict) -> dict:
    runtime = DRONES.get(payload["id"], {})
    telemetry = runtime.get("last_telemetry")
    return {
        **payload,
        "status": runtime.get("status", "offline"),
        "battery_pct": runtime.get("battery_pct"),
        "current_intersection_id": runtime.get("current_intersection_id"),
        "last_telemetry": telemetry,
        "telemetry_status": "fresh" if telemetry and runtime.get("status") != "offline" else "stale",
    }


@router.get("/drones")
async def list_drones(request: Request):
    rows = await _call(_orchestrator(request).list_drones())
    return [_runtime_drone(row) for row in rows]


@router.post("/drones", status_code=status.HTTP_201_CREATED)
async def create_drone(body: DroneCreate, request: Request):
    _admin(request)
    return await _call(_orchestrator(request).create_drone(body))


@router.get("/drones/{drone_id}")
async def get_drone(drone_id: str, request: Request):
    return _runtime_drone(await _call(_orchestrator(request).get_drone(drone_id)))


@router.patch("/drones/{drone_id}")
async def update_drone(drone_id: str, body: DroneUpdate, request: Request):
    _admin(request)
    return await _call(_orchestrator(request).update_drone(drone_id, body))


@router.get("/drones/{drone_id}/sources")
async def list_drone_sources(drone_id: str, request: Request):
    await _call(_orchestrator(request).get_drone(drone_id))
    return await _call(_orchestrator(request).list_sources(drone_id))


@router.get("/sources")
async def list_sources(request: Request):
    return await _call(_orchestrator(request).list_sources())


@router.get("/sources/{profile_id}/results")
async def get_source_results(profile_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """Return persisted Mission, situation, insight, survey and annotation entrypoints for one source."""
    video = (
        await db.execute(select(VideoSourceRecord).where(VideoSourceRecord.profile_id == profile_id))
    ).scalar_one_or_none()
    telemetry = (
        await db.execute(select(TelemetrySourceRecord).where(TelemetrySourceRecord.profile_id == profile_id))
    ).scalar_one_or_none()
    if video is None or telemetry is None:
        raise HTTPException(status_code=404, detail="source profile not found")
    missions = (
        await db.execute(
            select(MissionRecord)
            .where(MissionRecord.video_source_id == video.id, MissionRecord.telemetry_source_id == telemetry.id)
            .order_by(MissionRecord.created_at.desc())
        )
    ).scalars().all()
    batches = (
        await db.execute(
            select(SurveyCaptureBatch, SurveyTask)
            .join(SurveyTask, SurveyTask.id == SurveyCaptureBatch.task_id)
            .where(SurveyCaptureBatch.source_profile_id == profile_id)
            .order_by(SurveyCaptureBatch.created_at.desc())
        )
    ).all()
    task_ids = list(dict.fromkeys(batch.task_id for batch, _ in batches))
    frame_count = int(await db.scalar(select(func.count()).select_from(SurveyFrame).where(SurveyFrame.task_id.in_(task_ids)))) if task_ids else 0
    annotation_count = int(await db.scalar(select(func.count()).select_from(SceneAnnotation).where(SceneAnnotation.task_id.in_(task_ids)))) if task_ids else 0
    report_count = int(await db.scalar(select(func.count()).select_from(SurveyReport).where(SurveyReport.task_id.in_(task_ids)))) if task_ids else 0
    inter_id = missions[0].inter_id if missions else (batches[0][1].inter_id if batches else None)
    metric_count = int(await db.scalar(select(func.count()).select_from(TrafficMetric).where(TrafficMetric.inter_id == inter_id))) if inter_id else 0
    track_count = int(await db.scalar(select(func.count()).select_from(TrackEvent).where(TrackEvent.inter_id == inter_id))) if inter_id else 0
    conflict_count = int(await db.scalar(select(func.count()).select_from(ConflictEvent).where(ConflictEvent.inter_id == inter_id))) if inter_id else 0
    lane_tasks = (
        await db.execute(
            select(LaneAnnotationTaskRecord)
            .where(LaneAnnotationTaskRecord.inter_id == inter_id)
            .order_by(LaneAnnotationTaskRecord.created_at.desc())
        )
    ).scalars().all() if inter_id else []
    flight_segments = (
        await db.execute(
            select(FlightSegmentRecord)
            .where(FlightSegmentRecord.source_profile_id == profile_id)
            .order_by(FlightSegmentRecord.start_offset_sec.asc())
        )
    ).scalars().all()
    return {
        "profile_id": profile_id,
        "drone_id": video.drone_id,
        "inter_id": inter_id,
        "telemetry_type": (telemetry.config or {}).get("format") or telemetry.source_type,
        "sync_config": telemetry.config or {},
        "missions": [
            {
                "id": row.id,
                "status": row.status,
                "reason_code": row.reason_code,
                "pipeline_id": row.pipeline_id,
                "actual_start_at": row.actual_start_at,
                "actual_end_at": row.actual_end_at,
            }
            for row in missions
        ],
        "survey_tasks": [
            {
                "id": task.id,
                "status": task.state,
                "batch_id": batch.id,
                "batch_status": batch.status,
                "telemetry_coverage": batch.telemetry_coverage,
            }
            for batch, task in batches
        ],
        "counts": {
            "traffic_metrics": metric_count,
            "tracks": track_count,
            "conflicts": conflict_count,
            "survey_frames": frame_count,
            "scene_annotations": annotation_count,
            "survey_reports": report_count,
            "lane_annotations": len(lane_tasks),
        },
        "lane_tasks": [{"id": row.id, "status": row.status, "revision": row.revision} for row in lane_tasks],
        "flight_segments": [
            {
                "id": row.id,
                "mission_id": row.mission_id,
                "start_offset_sec": row.start_offset_sec,
                "end_offset_sec": row.end_offset_sec,
                "phase": row.phase,
                "quality_status": row.quality_status,
                "classifier_version": row.classifier_version,
                "motion_statistics": row.motion_statistics,
                "map_version_id": row.map_version_id,
                "created_at": row.created_at,
            }
            for row in flight_segments
        ],
        "links": {
            "situation": f"/gis?intersection_id={inter_id}&period=24h" if inter_id else "/gis?period=24h",
            "monitoring": "/drones?tab=fleet",
            "insight": f"/gis?intersection_id={inter_id}&period=24h&layer=trajectory" if inter_id else "/gis?period=24h&layer=trajectory",
            "survey": f"/survey/{task_ids[0]}/capture?task_id={task_ids[0]}" if task_ids else "/survey",
            "scene_annotation": f"/survey/{task_ids[0]}/measure?task_id={task_ids[0]}" if task_ids else "/survey",
            "lane_annotation": "/admin/calibration?tab=lane",
        },
    }


@router.post("/drones/{drone_id}/sources", status_code=status.HTTP_201_CREATED)
async def create_drone_source(drone_id: str, body: SourcePairCreate, request: Request):
    _admin(request)
    return await _call(_orchestrator(request).create_source_pair(drone_id, body))


@router.patch("/drones/{drone_id}/sources/{profile_id}")
async def update_drone_source(
    drone_id: str, profile_id: str, body: SourcePairUpdate, request: Request
):
    _admin(request)
    return await _call(_orchestrator(request).update_source_pair(drone_id, profile_id, body))


@router.post("/drones/{drone_id}/sources/{profile_id}/validate")
async def validate_drone_source(drone_id: str, profile_id: str, request: Request):
    _admin(request)
    return await _call(_orchestrator(request).validate_source_pair(drone_id, profile_id))


@router.get("/flight-plans")
async def list_flight_plans(request: Request):
    return await _call(_orchestrator(request).list_plans())


@router.post("/flight-plans", status_code=status.HTTP_201_CREATED)
async def create_flight_plan(body: FlightPlanCreate, request: Request):
    actor_id = _admin(request)
    return await _call(_orchestrator(request).create_plan(body, actor_id))


@router.get("/flight-plans/{plan_id}")
async def get_flight_plan(plan_id: str, request: Request):
    return await _call(_orchestrator(request).get_plan(plan_id))


@router.patch("/flight-plans/{plan_id}")
async def update_flight_plan(plan_id: str, body: FlightPlanUpdate, request: Request):
    _admin(request)
    return await _call(_orchestrator(request).update_plan(plan_id, body))


@router.delete("/flight-plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_flight_plan(plan_id: str, request: Request):
    _admin(request)
    await _call(_orchestrator(request).delete_plan(plan_id))


@router.post("/flight-plans/{plan_id}/enable")
async def enable_flight_plan(plan_id: str, body: RevisionAction, request: Request):
    _admin(request)
    return await _call(_orchestrator(request).change_plan_state(plan_id, body.revision, "enable"))


@router.post("/flight-plans/{plan_id}/pause")
async def pause_flight_plan(plan_id: str, body: RevisionAction, request: Request):
    _admin(request)
    return await _call(_orchestrator(request).change_plan_state(plan_id, body.revision, "pause"))


@router.post("/flight-plans/{plan_id}/retire")
async def retire_flight_plan(plan_id: str, body: RevisionAction, request: Request):
    _admin(request)
    return await _call(_orchestrator(request).change_plan_state(plan_id, body.revision, "retire"))


@router.get("/flight-plans/{plan_id}/occurrences")
async def flight_plan_occurrences(
    plan_id: str,
    request: Request,
    count: int = Query(default=10, ge=1, le=100),
    from_at: datetime | None = None,
):
    return await _call(_orchestrator(request).preview(plan_id, count, from_at))


@router.get("/missions")
async def list_missions(request: Request, mission_status: str | None = Query(default=None, alias="status")):
    return await _call(_orchestrator(request).list_missions(mission_status))


@router.post("/missions", status_code=status.HTTP_201_CREATED)
async def create_mission(body: MissionCreate, request: Request):
    actor_id = _admin(request)
    return await _call(_orchestrator(request).create_manual_mission(body, actor_id))


@router.get("/missions/{mission_id}")
async def get_mission(mission_id: str, request: Request):
    return await _call(_orchestrator(request).get_mission(mission_id))


@router.post("/missions/{mission_id}/stop")
async def stop_mission(mission_id: str, body: MissionAction, request: Request):
    _admin(request)
    return await _call(_orchestrator(request).stop_mission(mission_id, body.reason))


@router.post("/missions/{mission_id}/retry", status_code=status.HTTP_201_CREATED)
async def retry_mission(mission_id: str, body: MissionAction, request: Request):
    actor_id = _admin(request)
    return await _call(_orchestrator(request).retry_mission(mission_id, body.reason, actor_id))


@router.get("/drones/{drone_id}/trajectory")
async def get_drone_trajectory(drone_id: str, request: Request, start: str = "", end: str = ""):
    await _call(_orchestrator(request).get_drone(drone_id))
    return read_drone_trajectory(drone_id)


@router.get("/drones/{drone_id}/hover-points")
async def get_hover_points(drone_id: str, request: Request):
    await _call(_orchestrator(request).get_drone(drone_id))
    return [point for point in read_drone_trajectory(drone_id) if point.get("is_hovering")]


@telemetry_router.get("/{drone_id}")
async def get_telemetry(drone_id: str):
    drone = DRONES.get(drone_id)
    if not drone:
        raise HTTPException(status_code=404, detail="drone telemetry not found")
    telemetry = drone.get("last_telemetry")
    if not telemetry:
        raise HTTPException(status_code=404, detail="no telemetry")
    return telemetry


@telemetry_router.get("/{drone_id}/history")
async def get_telemetry_history(drone_id: str, limit: int = Query(default=50, ge=0, le=500)):
    return read_drone_telemetry_history(drone_id, limit)


def read_drone_telemetry_history(drone_id: str, limit: int) -> list[dict]:
    return read_telemetry_history(drone_id, limit=limit)
