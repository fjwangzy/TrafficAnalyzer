"""Calibration API endpoints."""
import json
import logging
import math
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from services.SrtTelemetryParser import SrtTelemetryParser
from services.TelemetryFileReader import TelemetryFileReader
from shapely.geometry import LineString, Polygon
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from utils_local.coordinates import COORDINATE_SYSTEM, TRANSFORM_VERSION, enu_to_gcj02

from app.core.config import settings
from app.core.database import get_db
from app.models.mission import (
    CalibrationReviewRecord,
    ChannelizedMapVersion,
    DroneRecord,
    FlightSegmentRecord,
    IntersectionProject,
    RoadContextSnapshot,
    SourceIntersectionBinding,
    TelemetrySourceRecord,
    VideoIngestionJob,
    VideoSourceRecord,
    VisualLaneBinding,
    VisualRegistration,
)
from app.models.survey import SurveyCaptureBatch, SurveyFrame, SurveyTask
from app.services.intersection_video_discovery import HoverIntersectionDiscovery
from app.services.survey_geometry import align_homography_to_map_enu
from app.services.survey_service import SurveyService
from app.services.ycx_road_import import YcxRoadImporter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/calibration", tags=["calibration"])


class LanePayload(BaseModel):
    lane_id: str | None = None
    name: str | None = None
    direction: str | None = None
    polygon: list[float] = Field(min_length=6)


class SaveLaneAnnotationPayload(BaseModel):
    lanes: list[LanePayload] = Field(min_length=1)
    roads: dict[str, Any] | None = None


class LaneTaskFromSurveyFramePayload(BaseModel):
    frame_id: str = Field(min_length=1, max_length=40)


class LaneKeyframeExtractionPayload(BaseModel):
    inter_id: str = Field(min_length=1, max_length=100)
    source_profile_id: str = Field(min_length=1, max_length=40)
    road_data_version: str | None = Field(default=None, max_length=100)
    checklist: dict[str, bool]


class ChannelizedLanePayload(BaseModel):
    local_lane_id: str = Field(min_length=1, max_length=100)
    source_lane_id: str | None = Field(default=None, max_length=100)
    link_id: str | None = Field(default=None, max_length=100)
    geometry_source: str = Field(pattern="^(link_offset_derived|imagery_fitted|manual_override)$")
    geometry_gcj02: dict
    geometry_enu_m: dict
    match_confidence: float | None = Field(default=None, ge=0, le=1)


class ChannelizedMapPayload(BaseModel):
    inter_id: str = Field(min_length=1, max_length=100)
    road_data_version: str = Field(min_length=1, max_length=100)
    anchor_gcj02: list[float] = Field(min_length=2, max_length=2)
    geometry_gcj02: dict = Field(default_factory=dict)
    geometry_enu_m: dict = Field(default_factory=dict)
    topology: dict = Field(default_factory=dict)
    quality: dict = Field(default_factory=dict)
    source_checksum: str | None = Field(default=None, max_length=64)
    lanes: list[ChannelizedLanePayload] = Field(default_factory=list)


class VisualRegistrationPayload(BaseModel):
    source_profile_id: str | None = Field(default=None, max_length=40)
    source_image_path: str = Field(min_length=1, max_length=500)
    orthophoto_path: str | None = Field(default=None, max_length=500)
    control_points: list = Field(default_factory=list)
    homography_pixel_to_enu: list | None = None
    residuals: dict = Field(default_factory=dict)
    orthophoto_bounds_gcj02: list[list[float]] | None = None
    registration_pose: dict = Field(default_factory=dict)
    camera_calibration: dict = Field(default_factory=dict)
    map_coverage_enu_m: dict = Field(default_factory=dict)


class PublishChannelizedMapPayload(BaseModel):
    target_status: str = Field(pattern="^(candidate|link_verified|lane_verified)$")


class VerifyRegistrationPayload(BaseModel):
    verified: bool = True


class ImageFittedLanePayload(BaseModel):
    local_lane_id: str = Field(min_length=1, max_length=100)
    source_lane_id: str | None = Field(default=None, max_length=100)
    link_id: str | None = Field(default=None, max_length=100)
    direction: str | None = Field(default=None, max_length=40)
    polygon_px: list[list[float]] = Field(min_length=3)


class ImageFittedFeaturePayload(BaseModel):
    feature_id: str = Field(min_length=1, max_length=100)
    feature_type: str = Field(
        pattern="^(lane_boundary|stop_line|guide_zone|waiting_zone)$"
    )
    points_px: list[list[float]] = Field(min_length=2)
    properties: dict = Field(default_factory=dict)


class ImageFitPayload(BaseModel):
    task_id: str = Field(min_length=1, max_length=120)
    source_profile_id: str = Field(min_length=1, max_length=40)
    homography_pixel_to_enu: list[list[float]] = Field(min_length=3, max_length=3)
    control_points: list[dict] = Field(default_factory=list)
    lanes: list[ImageFittedLanePayload] = Field(min_length=1)
    features: list[ImageFittedFeaturePayload] = Field(default_factory=list)
    link_residual_p95_m: float = Field(ge=0)
    lane_residual_median_m: float = Field(ge=0)
    lane_residual_p95_m: float = Field(ge=0)
    topology_errors: int = Field(default=0, ge=0)
    direction_checks_passed: bool = False
    stop_line_checks_passed: bool = False
    reviewed: bool = False
    registration_pose: dict = Field(default_factory=dict)
    camera_calibration: dict = Field(default_factory=dict)
    map_coverage_enu_m: dict = Field(default_factory=dict)


class YcxRoadImportPayload(BaseModel):
    inter_id: str = Field(min_length=1, max_length=100)
    road_data_version: str | None = Field(default=None, max_length=100)
    create_draft: bool = True


class IntersectionProjectCreatePayload(BaseModel):
    inter_id: str | None = Field(default=None, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    center_gcj02: list[float] | None = Field(default=None, min_length=2, max_length=2)


class IntersectionProjectPatchPayload(BaseModel):
    revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    inter_id: str | None = Field(default=None, max_length=100)
    center_gcj02: list[float] | None = Field(default=None, min_length=2, max_length=2)


class VideoIngestionPayload(BaseModel):
    project_id: str | None = Field(default=None, max_length=40)
    source_profile_id: str | None = Field(default=None, max_length=40)
    drone_id: str | None = Field(default=None, max_length=40)
    video_location: str | None = Field(default=None, max_length=500)
    telemetry_location: str | None = Field(default=None, max_length=500)
    telemetry_type: str | None = Field(default=None, pattern="^(srt|json|file|mqtt)$")


class VideoIngestionResolvePayload(BaseModel):
    action: str = Field(pattern="^(bind_expected_project|bind_existing_project|create_project)$")
    project_id: str | None = Field(default=None, max_length=40)
    segment_index: int = Field(default=0, ge=0)
    project_name: str | None = Field(default=None, max_length=200)
    inter_id: str | None = Field(default=None, max_length=100)


class CalibrationCheckPayload(BaseModel):
    result: str = Field(pattern="^(approved|rejected)$")
    issues: list[dict] = Field(default_factory=list)
    checklist: dict[str, bool] = Field(default_factory=dict)
    comment: str | None = Field(default=None, max_length=2000)


REQUIRED_CALIBRATION_REVIEW_CHECKS = frozenset({
    "imagery_map_alignment",
    "version_diff",
    "registration_error",
    "topology",
    "lane_directions",
    "stop_lines",
})

def _calibration_review_checklist_failures(checklist: dict[str, bool]) -> list[str]:
    return sorted(
        key for key in REQUIRED_CALIBRATION_REVIEW_CHECKS
        if checklist.get(key) is not True
    )


def _project_stage_after_source_binding(stage: str) -> str:
    if stage in {"discovered", "road_matched"}:
        return "source_ready"
    return stage


def _intersection_project_next_action(
    *, has_inter_id: bool, has_verified_road: bool,
    has_bindings: bool, map_statuses: set[str],
) -> str:
    if not has_inter_id:
        return "match_road_context"
    if not has_verified_road:
        return "verify_road_context"
    if not has_bindings:
        return "connect_video"
    if "lane_verified" in map_statuses:
        return "operate_runtime"
    if map_statuses & {"draft", "candidate", "link_verified"}:
        return "continue_draft"
    return "extract_keyframes"


def _load_calibration_db(path: str) -> dict:
    """Load calibration database JSON."""
    try:
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load calibration DB: {e}")
    return {}


def _lane_store(request: Request):
    store = getattr(request.app.state, "lane_annotation_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="lane annotation store unavailable")
    return store


@router.get("/summary")
async def get_calibration_summary(request: Request):
    """Get calibration summary."""
    path = request.app.state.settings.calibration_db_path
    db = _load_calibration_db(path)
    records = db.get("records", db) if isinstance(db, dict) else {}

    if isinstance(records, list):
        total = len(records)
        ok_count = sum(1 for r in records if r.get("quality", {}).get("score", 0) > 0.9)
        return {"total": total, "ok": ok_count, "degraded": total - ok_count}

    return {
        "total": len(records) if isinstance(records, dict) else 0,
        "records_count": len(records) if isinstance(records, dict) else 0,
    }


@router.get("/records")
async def list_calibration_records(request: Request):
    """List all calibration records."""
    path = request.app.state.settings.calibration_db_path
    db = _load_calibration_db(path)
    records = db.get("records", db) if isinstance(db, dict) else {}

    if isinstance(records, dict):
        return [{"key": k, **v} if isinstance(v, dict) else {"key": k, "value": v} for k, v in records.items()]
    elif isinstance(records, list):
        return records
    return []


@router.get("/records/{calib_key}")
async def get_calibration_record(calib_key: str, request: Request):
    """Get a specific calibration record."""
    path = request.app.state.settings.calibration_db_path
    db = _load_calibration_db(path)
    records = db.get("records", db) if isinstance(db, dict) else {}

    if isinstance(records, dict):
        record = records.get(calib_key)
        if record:
            return {"key": calib_key, **record} if isinstance(record, dict) else record
    return {"error": "not_found", "key": calib_key}


@router.get("/coverage/{intersection_id}")
async def get_coverage(intersection_id: str, request: Request):
    """Get calibration coverage heatmap data."""
    path = request.app.state.settings.calibration_db_path
    db = _load_calibration_db(path)
    records = db.get("records", db) if isinstance(db, dict) else {}

    coverage = []
    if isinstance(records, dict):
        for key, val in records.items():
            if intersection_id in key:
                if isinstance(val, dict):
                    quality = val.get("quality", {})
                    coverage.append({
                        "key": key,
                        "altitude": val.get("altitude_agl", 0),
                        "pitch": val.get("gimbal_pitch", 0),
                        "quality": "ok" if quality.get("score", 0) > 0.9 else "degraded",
                    })

    return coverage


@router.get("/lane-tasks")
async def list_lane_annotation_tasks(request: Request):
    """List hover-created lane annotation tasks."""
    return _lane_store(request).list_tasks()


@router.post("/lane-keyframe-extractions", status_code=201)
async def start_lane_keyframe_extraction(
    payload: LaneKeyframeExtractionPayload,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
):
    """Create a lane-calibration survey task and enqueue its retained source media."""
    _require_admin(request)
    required = {
        "task_context",
        "operator_authorized",
        "site_command_confirmed",
        "device_ready",
        "storage_ready",
    }
    if set(payload.checklist) != required or not all(payload.checklist.values()):
        raise HTTPException(
            status_code=422,
            detail="lane keyframe extraction requires exactly five confirmed precheck items",
        )
    request_id = idempotency_key or request.headers.get("X-Request-ID")
    if request_id and len(request_id) > 80:
        raise HTTPException(status_code=422, detail="request identifier exceeds 80 characters")

    source = (
        await db.execute(
            select(VideoSourceRecord).where(
                VideoSourceRecord.profile_id == payload.source_profile_id
            )
        )
    ).scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="source profile not found")
    drone = await db.get(DroneRecord, source.drone_id)
    if drone is None or drone.default_inter_id != payload.inter_id:
        raise HTTPException(
            status_code=422,
            detail="source profile is not registered to the requested intersection",
        )
    if not drone.enabled or not source.enabled or source.mode != "local":
        raise HTTPException(
            status_code=422,
            detail="lane keyframe extraction requires an enabled local source profile",
        )
    if source.validation_status != "valid":
        raise HTTPException(
            status_code=422,
            detail="lane keyframe extraction requires a valid source profile",
        )

    context = (
        await db.execute(
            select(RoadContextSnapshot)
            .where(RoadContextSnapshot.inter_id == payload.inter_id)
            .order_by(RoadContextSnapshot.created_at.desc())
        )
    ).scalars().first()
    intersection = ((context.payload or {}).get("intersection") or {}) if context else {}
    location = intersection.get("name") or payload.inter_id
    road_data_version = payload.road_data_version or (
        context.road_data_version if context else None
    )
    user = getattr(request.state, "user", None) or {}
    actor_id = _actor_id(request)
    actor_name = user.get("username") or user.get("name") or "admin"
    service = SurveyService(db)
    try:
        task = await service.create_task(
            {
                "title": f"渠化标注抽帧 · {location}",
                "scene_location": location,
                "source": "lane_calibration",
                "inter_id": payload.inter_id,
                "road_data_version": road_data_version,
            },
            actor_id,
            actor_name,
            request_id,
        )
        prechecking = await service.transition(
            task["id"], "start_precheck", task["revision"], {},
            actor_id, "admin", request_id,
        )
        await service.transition(
            task["id"], "complete_precheck", prechecking["revision"],
            {"checklist": payload.checklist}, actor_id, "admin", request_id,
        )
        batch = await service.import_capture_batch(
            task["id"], None, None, payload.source_profile_id,
            actor_id, "admin", request_id,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=422, detail="registered source media is unavailable") from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "task": await service.get_task(task["id"], actor_id, "admin"),
        "batch": batch,
    }


@router.post("/lane-tasks/from-survey-frame", status_code=201)
async def create_lane_task_from_survey_frame(
    payload: LaneTaskFromSurveyFramePayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Create a recoverable lane task from an already persisted real source keyframe."""
    user = getattr(request.state, "user", None) or {}
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="administrator capability is required")
    frame = await db.get(SurveyFrame, payload.frame_id)
    if frame is None:
        raise HTTPException(status_code=404, detail="survey frame not found")
    task = await db.get(SurveyTask, frame.task_id)
    if task is None or not task.inter_id:
        raise HTTPException(status_code=422, detail="survey frame has no intersection context")
    batch = await db.get(SurveyCaptureBatch, frame.batch_id)
    if batch is None or not batch.source_profile_id:
        raise HTTPException(
            status_code=422,
            detail="survey frame has no registered source_profile_id",
        )
    if frame.homography is None:
        raise HTTPException(
            status_code=422,
            detail="survey frame has no pixel-to-ENU transform",
        )
    try:
        metric_transform = np.asarray(frame.homography, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail="survey frame has an invalid pixel-to-ENU transform",
        ) from exc
    if metric_transform.shape != (3, 3) or not np.all(np.isfinite(metric_transform)):
        raise HTTPException(
            status_code=422,
            detail="survey frame has an invalid pixel-to-ENU transform",
        )
    try:
        actor_id = int(user.get("sub")) if user.get("sub") is not None else None
    except (TypeError, ValueError):
        actor_id = None
    _, image_path = await SurveyService(db).evidence_item(frame.image_evidence_id, actor_id, "admin")
    context = (
        await db.execute(
            select(RoadContextSnapshot)
            .where(RoadContextSnapshot.inter_id == task.inter_id)
            .order_by(RoadContextSnapshot.created_at.desc())
        )
    ).scalars().first()
    if context is None:
        await import_ycx_road_context(
            YcxRoadImportPayload(inter_id=task.inter_id, create_draft=True),
            request,
            db,
        )
        context = (
            await db.execute(
                select(RoadContextSnapshot)
                .where(RoadContextSnapshot.inter_id == task.inter_id)
                .order_by(RoadContextSnapshot.created_at.desc())
            )
        ).scalars().first()
    map_version = (
        await db.execute(
            select(ChannelizedMapVersion)
            .where(ChannelizedMapVersion.inter_id == task.inter_id)
            .order_by(ChannelizedMapVersion.version_no.desc())
        )
    ).scalars().first()
    if map_version is None:
        raise HTTPException(
            status_code=422,
            detail="survey frame has no channelized-map ENU anchor",
        )
    try:
        metric_transform = align_homography_to_map_enu(
            metric_transform, frame.telemetry, map_version.anchor_gcj02
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    roads = ((context.payload or {}).get("intersection") or {}) if context else {}
    return _lane_store(request).ensure_task_from_snapshot(
        task.inter_id,
        image_path.read_bytes(),
        frame.image_width,
        frame.image_height,
        frame.id,
        roads,
        source_profile_id=batch.source_profile_id,
        homography_pixel_to_enu=metric_transform.tolist(),
        map_version_id=map_version.id,
        map_anchor_gcj02=map_version.anchor_gcj02,
        homography_coordinate_frame="map_enu",
    )


@router.get("/lane-annotations")
async def list_lane_annotations(request: Request):
    """List saved lane annotation parameters."""
    return _lane_store(request).list_annotations()


@router.get("/lane-annotations/{intersection_id}")
async def get_lane_annotation(intersection_id: str, request: Request):
    """Get reusable lane parameters for one intersection."""
    annotation = _lane_store(request).get_annotation(intersection_id)
    if annotation is None:
        raise HTTPException(status_code=404, detail="lane annotation not found")
    return annotation


@router.get("/lane-tasks/{task_id}/image")
async def get_lane_task_image(task_id: str, request: Request):
    """Return the detector snapshot attached to a lane annotation task."""
    image_path = _lane_store(request).get_task_image_path(task_id)
    if image_path is None:
        raise HTTPException(status_code=404, detail="lane annotation task image not found")
    return FileResponse(image_path, media_type="image/jpeg")


@router.post("/lane-tasks/{task_id}/annotation")
async def save_lane_annotation(
    task_id: str,
    payload: SaveLaneAnnotationPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Save a task's manual lane annotation as reusable pipeline parameters."""
    raise HTTPException(
        status_code=410,
        detail="legacy pixel lane annotation is retired; use /calibration/channelized-maps",
    )


def _actor_id(request: Request) -> int | None:
    user = getattr(request.state, "user", None) or {}
    try:
        return int(user.get("sub")) if user.get("sub") is not None else None
    except (TypeError, ValueError):
        return None


def _require_admin(request: Request) -> None:
    user = getattr(request.state, "user", None) or {}
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="administrator capability is required")


def _project_response(row: IntersectionProject) -> dict[str, Any]:
    return {
        "project_id": row.id,
        "inter_id": row.inter_id,
        "name": row.name,
        "center_gcj02": row.center_gcj02,
        "stage": row.stage,
        "revision": row.revision,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _ingestion_response(row: VideoIngestionJob) -> dict[str, Any]:
    return {
        "job_id": row.id,
        "project_id": row.project_id,
        "mode": row.mode,
        "status": row.status,
        "source_profile_id": row.source_profile_id,
        "drone_id": row.drone_id,
        "video_location": row.video_location,
        "telemetry_location": row.telemetry_location,
        "telemetry_type": row.telemetry_type,
        "hover_evidence": row.hover_evidence,
        "candidate_intersections": row.candidate_intersections,
        "error_code": row.error_code,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


async def _road_candidates(db: AsyncSession) -> list[dict[str, Any]]:
    snapshots = (
        await db.execute(
            select(RoadContextSnapshot).order_by(
                RoadContextSnapshot.inter_id, RoadContextSnapshot.created_at.desc()
            )
        )
    ).scalars().all()
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for snapshot in snapshots:
        if snapshot.inter_id in seen:
            continue
        seen.add(snapshot.inter_id)
        intersection = (snapshot.payload or {}).get("intersection") or {}
        center = intersection.get("center_gcj02")
        if isinstance(center, list) and len(center) >= 2:
            result.append(
                {
                    "inter_id": snapshot.inter_id,
                    "name": intersection.get("name") or snapshot.inter_id,
                    "center_gcj02": center[:2],
                    "road_data_version": snapshot.road_data_version,
                    "quality_status": snapshot.quality_status,
                    "source": "road_context",
                }
            )
    return result


def _telemetry_records(location: str | None, source_type: str | None) -> tuple[dict, ...]:
    if not location or source_type == "mqtt":
        return ()
    path = _calibration_media_path(location, field="telemetry_location")
    if (source_type or path.suffix.lower().lstrip(".")) == "srt":
        return SrtTelemetryParser(str(path)).records
    return TelemetryFileReader(str(path)).records


async def _store_ingestion_upload(upload: Any, job_token: str, expected: set[str]) -> str:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in expected:
        raise HTTPException(status_code=422, detail=f"unsupported uploaded file type: {suffix or 'missing'}")
    directory = Path(settings.survey_storage_dir).expanduser().resolve() / "video_ingestions" / job_token
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{uuid.uuid4().hex}{suffix}"
    total = 0
    maximum = int(settings.survey_upload_max_bytes)
    with target.open("xb") as handle:
        while chunk := await upload.read(1024 * 1024):
            total += len(chunk)
            if total > maximum:
                target.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="uploaded calibration media exceeds configured limit")
            handle.write(chunk)
    return str(target)


async def _parse_video_ingestion_payload(request: Request) -> VideoIngestionPayload:
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" not in content_type:
        return VideoIngestionPayload.model_validate(await request.json())
    form = await request.form()
    token = uuid.uuid4().hex[:16]
    video_upload = form.get("video")
    telemetry_upload = form.get("telemetry")
    video_location = None
    telemetry_location = None
    telemetry_type = form.get("telemetry_type") or None
    if getattr(video_upload, "filename", None):
        video_location = await _store_ingestion_upload(video_upload, token, {".mp4"})
    if getattr(telemetry_upload, "filename", None):
        telemetry_location = await _store_ingestion_upload(telemetry_upload, token, {".srt", ".json", ".txt"})
        telemetry_type = "srt" if Path(telemetry_upload.filename).suffix.lower() == ".srt" else "json"
    if not video_location:
        raise HTTPException(status_code=422, detail="browser ingestion requires an MP4 video")
    return VideoIngestionPayload(
        project_id=form.get("project_id") or None,
        source_profile_id=form.get("source_profile_id") or None,
        drone_id=form.get("drone_id") or None,
        video_location=video_location,
        telemetry_location=telemetry_location,
        telemetry_type=telemetry_type,
    )


@router.get("/intersection-projects")
async def list_intersection_projects(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    _require_admin(request)
    rows = (
        await db.execute(
            select(IntersectionProject).order_by(IntersectionProject.updated_at.desc())
        )
    ).scalars().all()
    return [_project_response(row) for row in rows]


@router.post("/intersection-projects", status_code=201)
async def create_intersection_project(
    payload: IntersectionProjectCreatePayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    _require_admin(request)
    if payload.inter_id:
        existing = (
            await db.execute(
                select(IntersectionProject).where(IntersectionProject.inter_id == payload.inter_id)
            )
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail={"code": "intersection_project_exists", "project_id": existing.id})
    row = IntersectionProject(
        id=f"IPR-{uuid.uuid4().hex[:24]}",
        inter_id=payload.inter_id,
        name=payload.name,
        center_gcj02=payload.center_gcj02,
        stage="road_matched" if payload.inter_id else "discovered",
        created_by=_actor_id(request),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _project_response(row)


@router.get("/intersection-projects/{project_id}")
async def get_intersection_project(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    _require_admin(request)
    row = await db.get(IntersectionProject, project_id)
    if row is None:
        raise HTTPException(status_code=404, detail="intersection project not found")
    return _project_response(row)


@router.patch("/intersection-projects/{project_id}")
async def patch_intersection_project(
    project_id: str,
    payload: IntersectionProjectPatchPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    _require_admin(request)
    row = await db.get(IntersectionProject, project_id)
    if row is None:
        raise HTTPException(status_code=404, detail="intersection project not found")
    if row.revision != payload.revision:
        raise HTTPException(status_code=409, detail={"code": "revision_conflict", "current_revision": row.revision})
    for field in ("name", "inter_id", "center_gcj02"):
        value = getattr(payload, field)
        if value is not None:
            setattr(row, field, value)
    row.revision += 1
    if row.inter_id and row.stage == "discovered":
        row.stage = "road_matched"
    await db.commit()
    await db.refresh(row)
    return _project_response(row)


@router.get("/intersection-projects/{project_id}/workspace")
async def get_intersection_project_workspace(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    _require_admin(request)
    project = await db.get(IntersectionProject, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="intersection project not found")
    bindings = (
        await db.execute(
            select(SourceIntersectionBinding).where(
                SourceIntersectionBinding.project_id == project_id,
                SourceIntersectionBinding.active.is_(True),
            )
        )
    ).scalars().all()
    maps = []
    if project.inter_id:
        maps = (
            await db.execute(
                select(ChannelizedMapVersion)
                .where(ChannelizedMapVersion.inter_id == project.inter_id)
                .order_by(ChannelizedMapVersion.version_no.desc())
            )
        ).scalars().all()
    latest_reviews: dict[str, CalibrationReviewRecord] = {}
    if maps:
        reviews = (
            await db.execute(
                select(CalibrationReviewRecord)
                .where(CalibrationReviewRecord.map_version_id.in_([item.id for item in maps]))
                .order_by(CalibrationReviewRecord.created_at.desc())
            )
        ).scalars().all()
        for review in reviews:
            latest_reviews.setdefault(review.map_version_id, review)
    has_verified_road = False
    road_data_version = None
    if project.inter_id:
        road = (
            await db.execute(
                select(RoadContextSnapshot)
                .where(RoadContextSnapshot.inter_id == project.inter_id)
                .order_by(RoadContextSnapshot.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        has_verified_road = bool(road and road.quality_status == "verified")
        road_data_version = road.road_data_version if road else None
    next_action = _intersection_project_next_action(
        has_inter_id=bool(project.inter_id),
        has_verified_road=has_verified_road,
        has_bindings=bool(bindings),
        map_statuses={item.status for item in maps},
    )
    return {
        "project": _project_response(project),
        "readiness": {
            "formal_intersection": bool(project.inter_id),
            "road_context_verified": has_verified_road,
            "source_bound": bool(bindings),
            "road_data_version": road_data_version,
            "next_action": next_action,
        },
        "bindings": [
            {
                "binding_id": item.id,
                "source_profile_id": item.source_profile_id,
                "inter_id": item.inter_id,
                "start_offset_sec": item.start_offset_sec,
                "end_offset_sec": item.end_offset_sec,
                "binding_quality": item.binding_quality,
            }
            for item in bindings
        ],
        "channelized_maps": [
            {
                **_map_response(item),
                "latest_review": (
                    {
                        "review_id": latest_reviews[item.id].id,
                        "result": latest_reviews[item.id].result,
                        "issues": latest_reviews[item.id].issues,
                        "checklist": latest_reviews[item.id].checklist,
                        "comment": latest_reviews[item.id].comment,
                        "actor_id": latest_reviews[item.id].actor_id,
                        "created_at": latest_reviews[item.id].created_at,
                    }
                    if item.id in latest_reviews else None
                ),
            }
            for item in maps
        ],
    }


@router.post("/video-ingestions", status_code=201)
async def create_video_ingestion(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    _require_admin(request)
    payload = await _parse_video_ingestion_payload(request)
    if payload.project_id and await db.get(IntersectionProject, payload.project_id) is None:
        raise HTTPException(status_code=404, detail="expected intersection project not found")
    video_location, telemetry_location, telemetry_type = (
        payload.video_location, payload.telemetry_location, payload.telemetry_type
    )
    if video_location:
        video_location = str(_calibration_media_path(video_location, field="video_location"))
    if payload.source_profile_id:
        video = (
            await db.execute(
                select(VideoSourceRecord).where(VideoSourceRecord.profile_id == payload.source_profile_id)
            )
        ).scalar_one_or_none()
        telemetry = (
            await db.execute(
                select(TelemetrySourceRecord).where(TelemetrySourceRecord.profile_id == payload.source_profile_id)
            )
        ).scalar_one_or_none()
        if video is None:
            raise HTTPException(status_code=422, detail="source profile does not exist")
        video_location = video.location
        if telemetry:
            telemetry_location, telemetry_type = telemetry.location, telemetry.source_type
    records = _telemetry_records(telemetry_location, telemetry_type)
    discovery = HoverIntersectionDiscovery()
    local_candidates = await _road_candidates(db)
    analysis = discovery.discover(records, local_candidates)
    first_segment = ((analysis.get("hover_segments") or [None])[0])
    if first_segment and not first_segment.get("candidates"):
        try:
            ycx_candidates = await YcxRoadImporter(settings).nearby_intersections(
                first_segment["center_gcj02"], 250.0
            )
        except (OSError, TimeoutError, RuntimeError) as exc:
            logger.warning("YCX nearby candidate lookup unavailable: %s", exc)
            ycx_candidates = []
        if ycx_candidates:
            analysis = discovery.discover(records, ycx_candidates)
    segments = analysis.get("hover_segments") or []
    row = VideoIngestionJob(
        id=f"VIJ-{uuid.uuid4().hex[:24]}",
        project_id=payload.project_id,
        mode="project_first" if payload.project_id else "video_first",
        status=analysis["status"],
        source_profile_id=payload.source_profile_id,
        drone_id=payload.drone_id,
        video_location=video_location,
        telemetry_location=telemetry_location,
        telemetry_type=telemetry_type,
        hover_evidence=analysis,
        candidate_intersections=[item for segment in segments for item in segment.get("candidates", [])],
        error_code=analysis.get("reason_code"),
        created_by=_actor_id(request),
    )
    db.add(row)
    if payload.source_profile_id:
        for segment in analysis.get("flight_segments") or []:
            db.add(
                FlightSegmentRecord(
                    id=f"FSG-{uuid.uuid4().hex[:24]}",
                    source_profile_id=payload.source_profile_id,
                    mission_id=None,
                    start_offset_sec=segment["start_offset_sec"],
                    end_offset_sec=segment["end_offset_sec"],
                    phase=segment["phase"],
                    quality_status=segment["quality_status"],
                    classifier_version=segment["classifier_version"],
                    motion_statistics=segment.get("motion_statistics") or {},
                    map_version_id=None,
                )
            )
    await db.commit()
    await db.refresh(row)
    return _ingestion_response(row)


@router.get("/video-ingestions/{job_id}")
async def get_video_ingestion(
    job_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    _require_admin(request)
    row = await db.get(VideoIngestionJob, job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="video ingestion job not found")
    return _ingestion_response(row)


@router.get("/source-profiles/{source_profile_id}/flight-segments")
async def list_source_flight_segments(
    source_profile_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    _require_admin(request)
    rows = (
        await db.execute(
            select(FlightSegmentRecord)
            .where(FlightSegmentRecord.source_profile_id == source_profile_id)
            .order_by(
                FlightSegmentRecord.created_at.desc(),
                FlightSegmentRecord.start_offset_sec,
            )
        )
    ).scalars().all()
    return [
        {
            "id": item.id,
            "source_profile_id": item.source_profile_id,
            "mission_id": item.mission_id,
            "start_offset_sec": item.start_offset_sec,
            "end_offset_sec": item.end_offset_sec,
            "phase": item.phase,
            "quality_status": item.quality_status,
            "classifier_version": item.classifier_version,
            "motion_statistics": item.motion_statistics,
            "map_version_id": item.map_version_id,
            "created_at": item.created_at,
        }
        for item in rows
    ]


@router.post("/video-ingestions/{job_id}/resolve")
async def resolve_video_ingestion(
    job_id: str,
    payload: VideoIngestionResolvePayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    _require_admin(request)
    job = await db.get(VideoIngestionJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="video ingestion job not found")
    segments = (job.hover_evidence or {}).get("hover_segments") or []
    resolved_segments = set((job.hover_evidence or {}).get("resolved_segment_indexes") or [])
    if payload.segment_index in resolved_segments:
        raise HTTPException(status_code=409, detail="hover segment is already resolved")
    if job.status == "bound" and not segments:
        raise HTTPException(status_code=409, detail="video ingestion is already resolved")
    segment = segments[payload.segment_index] if payload.segment_index < len(segments) else None
    if segments and segment is None:
        raise HTTPException(status_code=422, detail="hover segment does not exist")
    top_candidate = ((segment or {}).get("candidates") or [None])[0]
    target_id = job.project_id if payload.action == "bind_expected_project" else payload.project_id
    project = await db.get(IntersectionProject, target_id) if target_id else None
    if payload.action == "create_project":
        inter_id = payload.inter_id or (top_candidate or {}).get("inter_id")
        if inter_id:
            existing = (
                await db.execute(select(IntersectionProject).where(IntersectionProject.inter_id == inter_id))
            ).scalar_one_or_none()
            if existing:
                raise HTTPException(status_code=409, detail={"code": "intersection_project_exists", "project_id": existing.id})
        project = IntersectionProject(
            id=f"IPR-{uuid.uuid4().hex[:24]}", inter_id=inter_id,
            name=payload.project_name or (top_candidate or {}).get("name") or "待路网匹配项目",
            center_gcj02=(segment or {}).get("center_gcj02"),
            stage="road_matched" if inter_id else "discovered", created_by=_actor_id(request),
        )
        db.add(project)
        await db.flush()
    if project is None:
        raise HTTPException(status_code=422, detail="target intersection project is required")
    if payload.action == "bind_expected_project" and top_candidate:
        if project.inter_id != top_candidate.get("inter_id") or float(top_candidate.get("distance_m", 999)) > 80:
            raise HTTPException(
                status_code=409,
                detail={"code": "video_intersection_mismatch", "candidate": top_candidate, "expected_project_id": project.id},
            )
    if not job.source_profile_id:
        if not job.drone_id or not job.video_location:
            raise HTTPException(status_code=422, detail={"code": "source_profile_required", "message": "上传素材绑定前必须选择登记无人机"})
        drone = await db.get(DroneRecord, job.drone_id)
        if drone is None:
            raise HTTPException(status_code=422, detail="selected drone does not exist")
        profile_id = f"SRC-ING-{uuid.uuid4().hex[:16].upper()}"
        telemetry_location = job.telemetry_location
        telemetry_type = job.telemetry_type or "file"
        telemetry_status = "valid"
        telemetry_error = None
        if not telemetry_location:
            placeholder_directory = (
                Path(settings.survey_storage_dir).expanduser().resolve()
                / "video_ingestions" / job.id
            )
            placeholder_directory.mkdir(parents=True, exist_ok=True)
            placeholder = placeholder_directory / "telemetry-missing.json"
            placeholder.write_text("[]", encoding="utf-8")
            telemetry_location = str(placeholder)
            telemetry_type = "file"
            telemetry_status = "invalid"
            telemetry_error = "telemetry_unavailable_manual_binding"
        video_source = VideoSourceRecord(
            id=f"VID-{uuid.uuid4().hex[:24]}", profile_id=profile_id,
            drone_id=job.drone_id, mode="local", source_type="mp4",
            location=job.video_location, enabled=True, validation_status="valid",
            validated_at=datetime.now(UTC),
        )
        telemetry_source = TelemetrySourceRecord(
            id=f"TEL-{uuid.uuid4().hex[:24]}", profile_id=profile_id,
            drone_id=job.drone_id, mode="local", source_type=telemetry_type,
            location=telemetry_location,
            config={"format": "dji_cloud_json"} if telemetry_type == "file" else {},
            enabled=True, validation_status=telemetry_status,
            validation_error_code=telemetry_error,
            validated_at=datetime.now(UTC) if telemetry_status == "valid" else None,
        )
        db.add_all([video_source, telemetry_source])
        await db.flush()
        job.source_profile_id = profile_id
    source = (
        await db.execute(select(VideoSourceRecord).where(VideoSourceRecord.profile_id == job.source_profile_id))
    ).scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=422, detail="source profile does not exist")
    quality = (segment or {}).get("confidence") or "manual_unverified"
    if quality == "auto_high_confidence" and payload.action != "bind_expected_project":
        quality = "admin_confirmed"
    start_offset = (segment or {}).get("start_offset_sec", 0)
    end_offset = (segment or {}).get("end_offset_sec")
    binding_conditions = [
        SourceIntersectionBinding.source_profile_id == job.source_profile_id,
        SourceIntersectionBinding.project_id == project.id,
        SourceIntersectionBinding.start_offset_sec == start_offset,
        SourceIntersectionBinding.active.is_(True),
    ]
    binding_conditions.append(
        SourceIntersectionBinding.end_offset_sec.is_(None)
        if end_offset is None else SourceIntersectionBinding.end_offset_sec == end_offset
    )
    binding = (
        await db.execute(select(SourceIntersectionBinding).where(*binding_conditions))
    ).scalar_one_or_none()
    if binding is None:
        binding = SourceIntersectionBinding(
            id=f"SIB-{uuid.uuid4().hex[:24]}", source_profile_id=job.source_profile_id,
            project_id=project.id, inter_id=project.inter_id,
            start_offset_sec=start_offset, end_offset_sec=end_offset, binding_quality=quality,
            coordinate_evidence={
                **((job.hover_evidence or {}).get("coordinate_evidence") or {}),
                "segment": segment,
            },
            confirmed_by=_actor_id(request),
        )
        db.add(binding)
        project.stage = _project_stage_after_source_binding(project.stage)
        project.revision += 1
    job.project_id = project.id
    evidence = dict(job.hover_evidence or {})
    evidence["resolved_segment_indexes"] = sorted([*resolved_segments, payload.segment_index])
    job.hover_evidence = evidence
    job.status = "bound" if not segments or len(evidence["resolved_segment_indexes"]) >= len(segments) else "awaiting_confirmation"
    await db.commit()
    return {"job": _ingestion_response(job), "project": _project_response(project), "binding_id": binding.id}


def _calibration_media_path(value: str, *, field: str) -> Path:
    """Resolve a retained media file without allowing arbitrary filesystem reads."""
    repository_root = Path(__file__).resolve().parents[4]

    def anchored(raw_value: str) -> Path:
        candidate = Path(raw_value).expanduser()
        if not candidate.is_absolute():
            candidate = repository_root / candidate
        return candidate.resolve()

    path = anchored(value)
    roots = [anchored(root) for root in settings.calibration_media_roots]
    if not any(path == root or root in path.parents for root in roots):
        raise HTTPException(
            status_code=422,
            detail=f"{field} must be inside an approved calibration media root",
        )
    if not path.is_file():
        raise HTTPException(status_code=422, detail=f"{field} file is unavailable")
    return path


async def _lock_intersection(db: AsyncSession, inter_id: str) -> None:
    """Serialize local draft creation while keeping YCX itself strictly read-only."""
    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:inter_id))"),
            {"inter_id": inter_id},
        )


def _map_response(row: ChannelizedMapVersion, lanes: list[VisualLaneBinding] | None = None) -> dict:
    return {
        "id": row.id,
        "inter_id": row.inter_id,
        "road_data_version": row.road_data_version,
        "version_no": row.version_no,
        "status": row.status,
        "coordinate_system": row.coordinate_system,
        "coordinate_transform_version": row.coordinate_transform_version,
        "anchor_gcj02": row.anchor_gcj02,
        "geometry_gcj02": row.geometry_gcj02,
        "geometry_enu_m": row.geometry_enu_m,
        "topology": row.topology,
        "quality": row.quality,
        "source_checksum": row.source_checksum,
        "published_at": row.published_at,
        "lanes": [
            {
                "local_lane_id": lane.local_lane_id,
                "source_lane_id": lane.canonical_lane_id,
                "link_id": lane.canonical_link_id,
                "geometry_source": lane.geometry_source,
                "geometry_gcj02": lane.geometry_gcj02,
                "geometry_enu_m": lane.geometry_enu_m,
                "match_confidence": lane.match_confidence,
                "status": lane.status,
            }
            for lane in (lanes or [])
        ],
    }


def _pixel_to_enu(point: list[float], matrix: list[list[float]]) -> list[float]:
    if len(point) < 2 or len(matrix) != 3 or any(len(row) != 3 for row in matrix):
        raise HTTPException(status_code=422, detail="invalid pixel point or 3x3 homography")
    x, y = float(point[0]), float(point[1])
    scale = matrix[2][0] * x + matrix[2][1] * y + matrix[2][2]
    if abs(scale) < 1e-12:
        raise HTTPException(status_code=422, detail="homography projects a point to infinity")
    return [
        (matrix[0][0] * x + matrix[0][1] * y + matrix[0][2]) / scale,
        (matrix[1][0] * x + matrix[1][1] * y + matrix[1][2]) / scale,
    ]


def _control_point_residuals(control_points: list[dict], matrix: list[list[float]]) -> dict:
    residuals = []
    for item in control_points:
        pixel = item.get("pixel")
        target = item.get("enu_m")
        if not isinstance(pixel, list) or not isinstance(target, list) or len(target) < 2:
            continue
        projected = _pixel_to_enu(pixel, matrix)
        residuals.append(math.hypot(projected[0] - float(target[0]), projected[1] - float(target[1])))
    if not residuals:
        return {"count": 0, "rmse_m": None, "p95_m": None}
    ordered = sorted(residuals)
    p95_index = min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1)
    return {
        "count": len(ordered),
        "rmse_m": math.sqrt(sum(value * value for value in ordered) / len(ordered)),
        "p95_m": ordered[p95_index],
    }


@router.post("/road-context/import-ycx", status_code=201)
async def import_ycx_road_context(
    payload: YcxRoadImportPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    _require_admin(request)
    await _lock_intersection(db, payload.inter_id)
    imported = await YcxRoadImporter(settings).import_intersection(
        payload.inter_id, payload.road_data_version
    )
    snapshot = (
        await db.execute(
            select(RoadContextSnapshot).where(
                RoadContextSnapshot.inter_id == imported.inter_id,
                RoadContextSnapshot.road_data_version == imported.road_data_version,
            )
        )
    ).scalar_one_or_none()
    if snapshot is None:
        snapshot = RoadContextSnapshot(
            id=f"RCS-{uuid.uuid4().hex[:24]}", inter_id=imported.inter_id,
            road_data_version=imported.road_data_version, source="ycx_readonly",
            checksum=imported.checksum,
            coordinate_reference={
                "display": "GCJ02", "metric": "local_ENU", "status": "candidate",
                "transform_version": TRANSFORM_VERSION,
            },
            payload=imported.payload, quality_status="candidate",
        )
        db.add(snapshot)
    else:
        snapshot.checksum = imported.checksum
        snapshot.payload = imported.payload
        snapshot.coordinate_reference = {
            "display": "GCJ02", "metric": "local_ENU", "status": "candidate",
            "transform_version": TRANSFORM_VERSION,
        }
        snapshot.quality_status = "candidate"

    map_row = None
    if payload.create_draft:
        version_no = int(await db.scalar(
            select(func.coalesce(func.max(ChannelizedMapVersion.version_no), 0)).where(
                ChannelizedMapVersion.inter_id == imported.inter_id
            )
        ) or 0) + 1
        map_row = ChannelizedMapVersion(
            id=f"CMV-{uuid.uuid4().hex[:24]}", inter_id=imported.inter_id,
            road_data_version=imported.road_data_version, version_no=version_no,
            status="draft", coordinate_system="GCJ02",
            coordinate_transform_version=TRANSFORM_VERSION,
            anchor_gcj02=imported.anchor_gcj02,
            geometry_gcj02=imported.geometry_gcj02,
            geometry_enu_m=imported.geometry_enu_m,
            topology=imported.topology,
            quality={"topology_errors": 0, "source_lane_geometry": "candidate_only"},
            source_checksum=imported.checksum, created_by=_actor_id(request),
        )
        db.add(map_row)
        await db.flush()
        for lane in imported.payload["lanes"]:
            db.add(VisualLaneBinding(
                id=f"VLB-{uuid.uuid4().hex[:24]}", inter_id=imported.inter_id,
                road_data_version=imported.road_data_version, map_version_id=map_row.id,
                local_lane_id=f"candidate:{lane['lane_id']}",
                canonical_link_id=lane.get("link_id"), canonical_lane_id=lane.get("lane_id"),
                geometry_source="link_offset_derived",
                geometry_gcj02=lane.get("geometry_gcj02"),
                geometry_enu_m=imported.geometry_enu_m["lane_candidates"].get(lane["lane_id"]),
                status="candidate", confirmed_by=None,
            ))
    await db.commit()
    return {
        "inter_id": imported.inter_id,
        "road_data_version": imported.road_data_version,
        "checksum": imported.checksum,
        "coordinate_system": "GCJ02",
        "link_count": len(imported.payload["links"]),
        "lane_candidate_count": len(imported.payload["lanes"]),
        "map_version_id": map_row.id if map_row else None,
    }


@router.post("/channelized-maps/bootstrap/{inter_id}", status_code=201)
async def bootstrap_channelized_map(
    inter_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Return the local map or import exactly one missing intersection from YCX."""
    _require_admin(request)
    await _lock_intersection(db, inter_id)
    local = (
        await db.execute(
            select(ChannelizedMapVersion)
            .where(ChannelizedMapVersion.inter_id == inter_id)
            .order_by(ChannelizedMapVersion.version_no.desc())
        )
    ).scalars().first()
    if local is not None:
        return {"source": "local", "map": await get_channelized_map(local.id, db)}
    imported = await import_ycx_road_context(
        YcxRoadImportPayload(inter_id=inter_id, create_draft=True), request, db
    )
    created = await db.get(ChannelizedMapVersion, imported["map_version_id"])
    return {"source": "ycx_on_demand", "map": await get_channelized_map(created.id, db)}


@router.get("/channelized-maps")
async def list_channelized_maps(
    inter_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    statement = select(ChannelizedMapVersion)
    if inter_id:
        statement = statement.where(ChannelizedMapVersion.inter_id == inter_id)
    rows = (await db.execute(statement.order_by(ChannelizedMapVersion.created_at.desc()))).scalars().all()
    return [_map_response(row) for row in rows]


@router.get("/channelized-maps/{map_version_id}")
async def get_channelized_map(map_version_id: str, db: AsyncSession = Depends(get_db)):
    row = await db.get(ChannelizedMapVersion, map_version_id)
    if row is None:
        raise HTTPException(status_code=404, detail="channelized map not found")
    lanes = (
        await db.execute(
            select(VisualLaneBinding).where(VisualLaneBinding.map_version_id == map_version_id)
        )
    ).scalars().all()
    result = _map_response(row, list(lanes))
    registrations = (
        await db.execute(
            select(VisualRegistration)
            .where(VisualRegistration.map_version_id == map_version_id)
            .order_by(VisualRegistration.created_at.desc())
        )
    ).scalars().all()
    registration = registrations[0] if registrations else None
    if registration is not None:
        result["visual_registration"] = {
            "id": registration.id,
            "source_profile_id": registration.source_profile_id,
            "status": registration.status,
            "residuals": registration.residuals,
            "registration_pose": registration.registration_pose,
            "camera_calibration": registration.camera_calibration,
            "map_coverage_enu_m": registration.map_coverage_enu_m,
            "orthophoto_url": (
                f"/api/v1/calibration/visual-registrations/{registration.id}/orthophoto"
                if registration.orthophoto_path else None
            ),
            "orthophoto_bounds_gcj02": (registration.residuals or {}).get(
                "orthophoto_bounds_gcj02"
            ),
        }
    result["visual_registrations"] = [
        {
            "id": item.id,
            "source_profile_id": item.source_profile_id,
            "status": item.status,
            "residuals": item.residuals,
            "registration_pose": item.registration_pose,
            "camera_calibration": item.camera_calibration,
            "map_coverage_enu_m": item.map_coverage_enu_m,
        }
        for item in registrations
    ]
    return result


@router.get("/channelized-maps/{map_version_id}/runtime-bundle")
async def get_runtime_map_bundle(
    map_version_id: str,
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(ChannelizedMapVersion, map_version_id)
    if row is None:
        raise HTTPException(status_code=404, detail="channelized map not found")
    if row.status != "lane_verified":
        raise HTTPException(status_code=409, detail="runtime map must be lane_verified")
    registrations = (
        await db.execute(
            select(VisualRegistration)
            .where(
                VisualRegistration.map_version_id == row.id,
                VisualRegistration.status == "verified",
            )
            .order_by(VisualRegistration.updated_at.desc())
        )
    ).scalars().all()
    if not registrations:
        raise HTTPException(status_code=409, detail="verified visual registration is required")
    registration = registrations[0]
    lanes = (
        await db.execute(
            select(VisualLaneBinding).where(
                VisualLaneBinding.map_version_id == row.id,
                VisualLaneBinding.status == "lane_verified",
            )
        )
    ).scalars().all()
    if not lanes:
        raise HTTPException(status_code=409, detail="verified lane bindings are required")
    return {
        "schema_version": "uav.runtime-road-map/v1",
        "map_version_id": row.id,
        "map_status": row.status,
        "inter_id": row.inter_id,
        "road_data_version": row.road_data_version,
        "coordinate_system": row.coordinate_system,
        "coordinate_transform_version": row.coordinate_transform_version,
        "anchor_gcj02": row.anchor_gcj02,
        "geometry_gcj02": row.geometry_gcj02,
        "geometry_enu_m": row.geometry_enu_m,
        "topology": row.topology,
        "quality": row.quality,
        "visual_registration": {
            "id": registration.id,
            "source_profile_id": registration.source_profile_id,
            "homography_pixel_to_enu": registration.homography_pixel_to_enu,
            "residuals": registration.residuals,
            "registration_pose": registration.registration_pose,
            "camera_calibration": registration.camera_calibration,
            "map_coverage_enu_m": registration.map_coverage_enu_m,
        },
        "visual_registrations": [
            {
                "id": item.id,
                "source_profile_id": item.source_profile_id,
                "homography_pixel_to_enu": item.homography_pixel_to_enu,
                "residuals": item.residuals,
                "registration_pose": item.registration_pose,
                "camera_calibration": item.camera_calibration,
                "map_coverage_enu_m": item.map_coverage_enu_m,
            }
            for item in registrations
        ],
        "lanes": [
            {
                "local_lane_id": item.local_lane_id,
                "source_lane_id": item.canonical_lane_id,
                "link_id": item.canonical_link_id,
                "geometry_enu_m": item.geometry_enu_m,
                "geometry_gcj02": item.geometry_gcj02,
                "geometry_source": item.geometry_source,
                "match_confidence": item.match_confidence,
            }
            for item in lanes
        ],
    }


@router.post("/channelized-maps", status_code=201)
async def create_channelized_map(
    payload: ChannelizedMapPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    _require_admin(request)
    await _lock_intersection(db, payload.inter_id)
    version_no = int(
        await db.scalar(
            select(func.coalesce(func.max(ChannelizedMapVersion.version_no), 0)).where(
                ChannelizedMapVersion.inter_id == payload.inter_id
            )
        )
        or 0
    ) + 1
    row = ChannelizedMapVersion(
        id=f"CMV-{uuid.uuid4().hex[:24]}",
        inter_id=payload.inter_id,
        road_data_version=payload.road_data_version,
        version_no=version_no,
        status="draft",
        coordinate_system=COORDINATE_SYSTEM,
        coordinate_transform_version=TRANSFORM_VERSION,
        anchor_gcj02=payload.anchor_gcj02,
        geometry_gcj02=payload.geometry_gcj02,
        geometry_enu_m=payload.geometry_enu_m,
        topology=payload.topology,
        quality=payload.quality,
        source_checksum=payload.source_checksum,
        created_by=_actor_id(request),
    )
    db.add(row)
    await db.flush()
    for lane in payload.lanes:
        db.add(
            VisualLaneBinding(
                id=f"VLB-{uuid.uuid4().hex[:24]}",
                inter_id=payload.inter_id,
                road_data_version=payload.road_data_version,
                map_version_id=row.id,
                local_lane_id=lane.local_lane_id,
                canonical_link_id=lane.link_id,
                canonical_lane_id=lane.source_lane_id,
                geometry_source=lane.geometry_source,
                geometry_gcj02=lane.geometry_gcj02,
                geometry_enu_m=lane.geometry_enu_m,
                match_confidence=lane.match_confidence,
                status="candidate",
                confirmed_by=_actor_id(request),
            )
        )
    await db.commit()
    return await get_channelized_map(row.id, db)


@router.put("/channelized-maps/{map_version_id}")
async def update_channelized_map(
    map_version_id: str,
    payload: ChannelizedMapPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    _require_admin(request)
    row = await db.get(ChannelizedMapVersion, map_version_id)
    if row is None:
        raise HTTPException(status_code=404, detail="channelized map not found")
    if row.status not in {"draft", "candidate"}:
        raise HTTPException(status_code=409, detail="published channelized map is immutable")
    if row.inter_id != payload.inter_id or row.road_data_version != payload.road_data_version:
        raise HTTPException(status_code=422, detail="map identity cannot be changed")
    row.anchor_gcj02 = payload.anchor_gcj02
    row.geometry_gcj02 = payload.geometry_gcj02
    row.geometry_enu_m = payload.geometry_enu_m
    row.topology = payload.topology
    row.quality = payload.quality
    await db.execute(
        VisualLaneBinding.__table__.delete().where(VisualLaneBinding.map_version_id == row.id)
    )
    for lane in payload.lanes:
        db.add(VisualLaneBinding(
            id=f"VLB-{uuid.uuid4().hex[:24]}", inter_id=row.inter_id,
            road_data_version=row.road_data_version, map_version_id=row.id,
            local_lane_id=lane.local_lane_id, canonical_link_id=lane.link_id,
            canonical_lane_id=lane.source_lane_id, geometry_source=lane.geometry_source,
            geometry_gcj02=lane.geometry_gcj02, geometry_enu_m=lane.geometry_enu_m,
            match_confidence=lane.match_confidence, status="candidate",
        ))
    await db.commit()
    return await get_channelized_map(row.id, db)


@router.post("/channelized-maps/{map_version_id}/fit-from-image")
async def fit_channelized_map_from_image(
    map_version_id: str,
    payload: ImageFitPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Project reviewed image-space lane polygons into canonical ENU and GCJ-02 geometry."""
    _require_admin(request)
    row = await db.get(ChannelizedMapVersion, map_version_id)
    if row is None:
        raise HTTPException(status_code=404, detail="channelized map not found")
    if row.status not in {"draft", "candidate"}:
        raise HTTPException(status_code=409, detail="published channelized map is immutable")
    task = _lane_store(request).get_task(payload.task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="lane annotation task not found")
    if task.get("intersection_id") != row.inter_id:
        raise HTTPException(status_code=422, detail="task and map intersection do not match")
    if task.get("homography_coordinate_frame") != "map_enu":
        raise HTTPException(
            status_code=422,
            detail="annotation task must be refreshed with a map-aligned keyframe transform",
        )
    task_anchor = task.get("map_anchor_gcj02")
    if (
        not isinstance(task_anchor, list)
        or len(task_anchor) != 2
        or any(abs(float(task_anchor[index]) - float(row.anchor_gcj02[index])) > 1e-9 for index in range(2))
    ):
        raise HTTPException(
            status_code=422,
            detail="annotation task and map ENU anchors do not match",
        )
    image_path = _lane_store(request).get_task_image_path(payload.task_id)
    if image_path is None:
        raise HTTPException(status_code=422, detail="annotation task has no retained source image")

    enu_lanes: dict[str, dict] = {}
    gcj_lanes: dict[str, dict] = {}
    fitted: list[tuple[ImageFittedLanePayload, dict, dict]] = []
    polygons: list[tuple[str, Polygon]] = []
    for lane in payload.lanes:
        ring = [_pixel_to_enu(point, payload.homography_pixel_to_enu) for point in lane.polygon_px]
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        polygon = Polygon(ring)
        if not polygon.is_valid or polygon.area <= 0:
            raise HTTPException(
                status_code=422,
                detail=f"lane {lane.local_lane_id} has an invalid or self-intersecting polygon",
            )
        for other_lane, other in polygons:
            overlap = polygon.intersection(other).area
            if overlap > min(polygon.area, other.area) * 0.05:
                raise HTTPException(
                    status_code=422,
                    detail=f"lanes {other_lane} and {lane.local_lane_id} overlap by more than 5%",
                )
        polygons.append((lane.local_lane_id, polygon))
        enu_geometry = {"type": "Polygon", "coordinates": [ring]}
        gcj_ring = [list(enu_to_gcj02(point[0], point[1], row.anchor_gcj02)) for point in ring]
        gcj_geometry = {"type": "Polygon", "coordinates": [gcj_ring]}
        enu_lanes[lane.local_lane_id] = enu_geometry
        gcj_lanes[lane.local_lane_id] = gcj_geometry
        fitted.append((lane, gcj_geometry, enu_geometry))

    control_residuals = _control_point_residuals(
        payload.control_points, payload.homography_pixel_to_enu
    )
    enu_features: dict[str, dict] = {}
    gcj_features: dict[str, dict] = {}
    for feature in payload.features:
        points = [
            _pixel_to_enu(point, payload.homography_pixel_to_enu)
            for point in feature.points_px
        ]
        is_area = feature.feature_type in {"guide_zone", "waiting_zone"}
        if is_area:
            if len(points) < 3:
                raise HTTPException(status_code=422, detail=f"{feature.feature_id} requires a polygon")
            if points[0] != points[-1]:
                points.append(points[0])
            shape = Polygon(points)
            geometry_type = "Polygon"
            coordinates = [points]
        else:
            shape = LineString(points)
            geometry_type = "LineString"
            coordinates = points
        if not shape.is_valid or shape.is_empty or shape.length <= 0:
            raise HTTPException(status_code=422, detail=f"invalid feature {feature.feature_id}")
        gcj_points = [list(enu_to_gcj02(point[0], point[1], row.anchor_gcj02)) for point in points]
        feature_meta = {
            "feature_type": feature.feature_type,
            "properties": feature.properties,
        }
        enu_features[feature.feature_id] = {
            **feature_meta, "geometry": {"type": geometry_type, "coordinates": coordinates}
        }
        gcj_features[feature.feature_id] = {
            **feature_meta,
            "geometry": {
                "type": geometry_type,
                "coordinates": [gcj_points] if is_area else gcj_points,
            },
        }

    quality = {
        **(row.quality or {}),
        "link_residual_p95_m": payload.link_residual_p95_m,
        "lane_residual_median_m": payload.lane_residual_median_m,
        "lane_residual_p95_m": payload.lane_residual_p95_m,
        "topology_errors": payload.topology_errors,
        "self_intersection_checks_passed": True,
        "overlap_checks_passed": True,
        "direction_checks_passed": payload.direction_checks_passed,
        "stop_line_checks_passed": payload.stop_line_checks_passed,
        "reviewed": payload.reviewed,
        "control_point_residuals": control_residuals,
        "lane_count": len(fitted),
    }
    geometry_enu = dict(row.geometry_enu_m or {})
    geometry_gcj = dict(row.geometry_gcj02 or {})
    geometry_enu["lanes"] = enu_lanes
    geometry_gcj["lanes"] = gcj_lanes
    geometry_enu["features"] = enu_features
    geometry_gcj["features"] = gcj_features
    row.geometry_enu_m = geometry_enu
    row.geometry_gcj02 = geometry_gcj
    topology = dict(row.topology or {})
    topology["lane_properties"] = {
        lane.local_lane_id: {
            "direction": lane.direction,
            "source_lane_id": lane.source_lane_id,
            "link_id": lane.link_id,
        }
        for lane in payload.lanes
    }
    row.topology = topology
    row.quality = quality
    row.status = "candidate"

    await db.execute(
        VisualLaneBinding.__table__.delete().where(VisualLaneBinding.map_version_id == row.id)
    )
    for lane, gcj_geometry, enu_geometry in fitted:
        db.add(VisualLaneBinding(
            id=f"VLB-{uuid.uuid4().hex[:24]}", inter_id=row.inter_id,
            road_data_version=row.road_data_version, map_version_id=row.id,
            local_lane_id=lane.local_lane_id, canonical_link_id=lane.link_id,
            canonical_lane_id=lane.source_lane_id, geometry_source="imagery_fitted",
            geometry_gcj02=gcj_geometry, geometry_enu_m=enu_geometry,
            match_confidence=None, status="candidate", confirmed_by=_actor_id(request),
        ))
    source_exists = (
        await db.execute(
            select(VideoSourceRecord.id).where(
                VideoSourceRecord.profile_id == payload.source_profile_id
            )
        )
    ).scalar_one_or_none()
    if source_exists is None:
        raise HTTPException(status_code=422, detail="source_profile_id is not registered")
    registration_statement = select(VisualRegistration).where(
        VisualRegistration.map_version_id == row.id,
        VisualRegistration.source_profile_id == payload.source_profile_id,
    )
    registration = (await db.execute(registration_statement)).scalar_one_or_none()
    if registration is None:
        registration = VisualRegistration(
            id=f"VRG-{uuid.uuid4().hex[:24]}",
            map_version_id=row.id,
            source_profile_id=payload.source_profile_id,
            source_image_path=str(image_path),
            control_points=payload.control_points,
            homography_pixel_to_enu=payload.homography_pixel_to_enu,
            residuals=control_residuals,
            registration_pose=payload.registration_pose,
            camera_calibration=payload.camera_calibration,
            map_coverage_enu_m=payload.map_coverage_enu_m,
            status="registered",
            created_by=_actor_id(request),
        )
        db.add(registration)
    else:
        registration.source_image_path = str(image_path)
        registration.control_points = payload.control_points
        registration.homography_pixel_to_enu = payload.homography_pixel_to_enu
        registration.residuals = control_residuals
        registration.registration_pose = payload.registration_pose
        registration.camera_calibration = payload.camera_calibration
        registration.map_coverage_enu_m = payload.map_coverage_enu_m
        registration.status = "registered"
        registration.created_by = _actor_id(request)
    await db.commit()
    result = await get_channelized_map(row.id, db)
    result["registration"] = {"id": registration.id, "status": registration.status}
    return result


@router.post("/channelized-maps/{map_version_id}/registrations", status_code=201)
async def add_visual_registration(
    map_version_id: str,
    payload: VisualRegistrationPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    _require_admin(request)
    row = await db.get(ChannelizedMapVersion, map_version_id)
    if row is None:
        raise HTTPException(status_code=404, detail="channelized map not found")
    if row.status not in {"draft", "candidate"}:
        raise HTTPException(status_code=409, detail="published channelized map is immutable")
    source_image_path = _calibration_media_path(
        payload.source_image_path, field="source_image_path"
    )
    orthophoto_path = (
        _calibration_media_path(payload.orthophoto_path, field="orthophoto_path")
        if payload.orthophoto_path
        else None
    )
    registration = VisualRegistration(
        id=f"VRG-{uuid.uuid4().hex[:24]}", map_version_id=map_version_id,
        source_profile_id=payload.source_profile_id,
        source_image_path=str(source_image_path),
        orthophoto_path=str(orthophoto_path) if orthophoto_path else None,
        control_points=payload.control_points,
        homography_pixel_to_enu=payload.homography_pixel_to_enu,
        residuals={
            **payload.residuals,
            **({"orthophoto_bounds_gcj02": payload.orthophoto_bounds_gcj02}
               if payload.orthophoto_bounds_gcj02 else {}),
        },
        registration_pose=payload.registration_pose,
        camera_calibration=payload.camera_calibration,
        map_coverage_enu_m=payload.map_coverage_enu_m,
        status="registered" if payload.homography_pixel_to_enu else "draft",
        created_by=_actor_id(request),
    )
    db.add(registration)
    await db.commit()
    return {
        "id": registration.id,
        "map_version_id": map_version_id,
        "source_profile_id": registration.source_profile_id,
        "status": registration.status,
    }


@router.post("/visual-registrations/{registration_id}/verify")
async def verify_visual_registration(
    registration_id: str,
    payload: VerifyRegistrationPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    _require_admin(request)
    registration = await db.get(VisualRegistration, registration_id)
    if registration is None:
        raise HTTPException(status_code=404, detail="visual registration not found")
    if payload.verified and not registration.homography_pixel_to_enu:
        raise HTTPException(status_code=422, detail="homography is required before verification")
    registration.status = "verified" if payload.verified else "rejected"
    await db.commit()
    return {"id": registration.id, "status": registration.status}


@router.get("/visual-registrations/{registration_id}/orthophoto")
async def get_visual_registration_orthophoto(
    registration_id: str,
    db: AsyncSession = Depends(get_db),
):
    registration = await db.get(VisualRegistration, registration_id)
    if registration is None or not registration.orthophoto_path:
        raise HTTPException(status_code=404, detail="orthophoto not found")
    try:
        path = _calibration_media_path(
            registration.orthophoto_path, field="orthophoto_path"
        )
    except HTTPException as exc:
        raise HTTPException(status_code=404, detail="orthophoto file is unavailable") from exc
    return FileResponse(path)


@router.post("/channelized-maps/{map_version_id}/submit-check", status_code=201)
async def submit_channelized_map_check(
    map_version_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    _require_admin(request)
    row = await db.get(ChannelizedMapVersion, map_version_id)
    if row is None:
        raise HTTPException(status_code=404, detail="channelized map not found")
    if row.status not in {"draft", "candidate"}:
        raise HTTPException(status_code=409, detail="only a draft or candidate can be submitted")
    record = CalibrationReviewRecord(
        id=f"CRV-{uuid.uuid4().hex[:24]}", map_version_id=row.id,
        result="submitted", issues=[], checklist={}, actor_id=_actor_id(request),
    )
    db.add(record)
    await db.execute(
        IntersectionProject.__table__.update()
        .where(IntersectionProject.inter_id == row.inter_id)
        .values(stage="checking", revision=IntersectionProject.revision + 1)
    )
    await db.commit()
    return {"review_id": record.id, "map_version_id": row.id, "result": record.result}


@router.post("/channelized-maps/{map_version_id}/check", status_code=201)
async def check_channelized_map(
    map_version_id: str,
    payload: CalibrationCheckPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    _require_admin(request)
    row = await db.get(ChannelizedMapVersion, map_version_id)
    if row is None:
        raise HTTPException(status_code=404, detail="channelized map not found")
    submitted = (
        await db.execute(
            select(CalibrationReviewRecord)
            .where(
                CalibrationReviewRecord.map_version_id == row.id,
                CalibrationReviewRecord.result == "submitted",
            )
            .order_by(CalibrationReviewRecord.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if submitted is None:
        raise HTTPException(status_code=409, detail="submit the draft for checking first")
    failed_checks = _calibration_review_checklist_failures(payload.checklist)
    if payload.result == "approved" and (payload.issues or failed_checks):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "calibration_review_incomplete",
                "message": "approved checks require all quality gates and no open issues",
                "failed_checks": failed_checks,
            },
        )
    record = CalibrationReviewRecord(
        id=f"CRV-{uuid.uuid4().hex[:24]}", map_version_id=row.id,
        result=payload.result, issues=payload.issues, checklist=payload.checklist,
        comment=payload.comment, actor_id=_actor_id(request),
    )
    db.add(record)
    quality = dict(row.quality or {})
    quality["reviewed"] = payload.result == "approved"
    quality["review_record_id"] = record.id
    row.quality = quality
    await db.execute(
        IntersectionProject.__table__.update()
        .where(IntersectionProject.inter_id == row.inter_id)
        .values(
            stage="checking" if payload.result == "approved" else "drafting",
            revision=IntersectionProject.revision + 1,
        )
    )
    await db.commit()
    return {"review_id": record.id, "map_version_id": row.id, "result": record.result}


@router.post("/channelized-maps/{map_version_id}/publish")
async def publish_channelized_map(
    map_version_id: str,
    payload: PublishChannelizedMapPayload,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    _require_admin(request)
    row = await db.get(ChannelizedMapVersion, map_version_id)
    if row is None:
        raise HTTPException(status_code=404, detail="channelized map not found")
    if row.status in {"lane_verified", "retired"}:
        raise HTTPException(status_code=409, detail="published channelized map is immutable")
    quality = row.quality or {}
    failures: list[str] = []
    if payload.target_status in {"link_verified", "lane_verified"}:
        if float(quality.get("link_residual_p95_m", 999)) > 3:
            failures.append("link_residual_p95_m must be <= 3")
        if int(quality.get("topology_errors", 1)) != 0:
            failures.append("topology_errors must be 0")
    if payload.target_status == "lane_verified":
        latest_review = (
            await db.execute(
                select(CalibrationReviewRecord)
                .where(CalibrationReviewRecord.map_version_id == row.id)
                .order_by(CalibrationReviewRecord.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if latest_review is None or latest_review.result != "approved":
            failures.append("an approved calibration check is required")
        if float(quality.get("lane_residual_median_m", 999)) > 0.75:
            failures.append("lane_residual_median_m must be <= 0.75")
        if float(quality.get("lane_residual_p95_m", 999)) > 1.5:
            failures.append("lane_residual_p95_m must be <= 1.5")
        lane_count = int(await db.scalar(select(func.count()).select_from(VisualLaneBinding).where(
            VisualLaneBinding.map_version_id == row.id,
            VisualLaneBinding.geometry_source.in_(("imagery_fitted", "manual_override")),
        )) or 0)
        if lane_count == 0:
            failures.append("at least one fitted lane is required")
        if quality.get("reviewed") is not True:
            failures.append("manual review is required")
        if quality.get("self_intersection_checks_passed") is not True:
            failures.append("self-intersection checks must pass")
        if quality.get("overlap_checks_passed") is not True:
            failures.append("overlap checks must pass")
        if quality.get("direction_checks_passed") is not True:
            failures.append("entry, exit and turn direction checks must pass")
        if quality.get("stop_line_checks_passed") is not True:
            failures.append("stop-line checks must pass")
        features = (row.geometry_enu_m or {}).get("features") or {}
        if not any(item.get("feature_type") == "stop_line" for item in features.values()):
            failures.append("at least one fitted stop line is required")
        registration_count = int(await db.scalar(
            select(func.count()).select_from(VisualRegistration).where(
                VisualRegistration.map_version_id == row.id,
                VisualRegistration.status == "verified",
            )
        ) or 0)
        if registration_count == 0:
            failures.append("a verified visual registration is required")
    if failures:
        raise HTTPException(status_code=422, detail={"code": "map_quality_gate_failed", "failures": failures})
    if payload.target_status == "lane_verified":
        await db.execute(
            ChannelizedMapVersion.__table__.update()
            .where(
                ChannelizedMapVersion.inter_id == row.inter_id,
                ChannelizedMapVersion.status == "lane_verified",
                ChannelizedMapVersion.id != row.id,
            )
            .values(status="retired")
        )
        snapshot_predicates = [RoadContextSnapshot.inter_id == row.inter_id]
        if row.source_checksum:
            snapshot_predicates.append(RoadContextSnapshot.checksum == row.source_checksum)
        else:
            snapshot_predicates.append(
                RoadContextSnapshot.road_data_version == row.road_data_version
            )
        await db.execute(
            RoadContextSnapshot.__table__.update()
            .where(*snapshot_predicates)
            .values(
                quality_status="verified",
                coordinate_reference={
                    "coordinate_system": "GCJ02",
                    "display": "GCJ02",
                    "metric": "local_ENU",
                    "status": "verified",
                    "usage": "lane_verified_runtime",
                    "transform_version": row.coordinate_transform_version,
                    "coordinate_transform_version": row.coordinate_transform_version,
                    "anchor_gcj02": row.anchor_gcj02,
                    "map_version_id": row.id,
                },
            )
        )
    row.status = payload.target_status
    row.published_at = datetime.now(UTC) if payload.target_status.endswith("verified") else None
    await db.execute(
        VisualLaneBinding.__table__.update()
        .where(VisualLaneBinding.map_version_id == row.id)
        .values(status=payload.target_status)
    )
    if payload.target_status == "lane_verified":
        await db.execute(
            IntersectionProject.__table__.update()
            .where(IntersectionProject.inter_id == row.inter_id)
            .values(stage="published", revision=IntersectionProject.revision + 1)
        )
    await db.commit()
    return await get_channelized_map(row.id, db)
