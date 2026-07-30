"""Pipeline management API — start/stop/monitor detection pipelines."""
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.services.pipeline_manager import redact_video_source
from app.services.runtime_capabilities import capability_report_from_runtime_quality

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pipelines", tags=["pipelines"])


def _require_role(request: Request, *roles: str) -> dict:
    user = getattr(request.state, "user", None) or {}
    if user.get("role") not in roles:
        logger.warning(
            "audit actor=%s role=%s action=%s outcome=denied",
            user.get("username") or user.get("sub") or "anonymous",
            user.get("role") or "unknown",
            request.url.path,
        )
        raise HTTPException(status_code=403, detail="Insufficient pipeline role")
    return user


async def _audit(
    request: Request,
    user: dict,
    action: str,
    resource: str,
    after_value: dict | None = None,
) -> None:
    service = getattr(request.app.state, "audit_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Persistent audit service unavailable")
    await service.record(
        actor=user,
        action=action,
        target_type="pipeline",
        target_id=resource,
        after_value=after_value,
    )
    logger.info(
        "audit actor=%s role=%s action=%s resource=%s outcome=recorded",
        user.get("username") or user.get("sub") or "unknown",
        user.get("role") or "unknown",
        action,
        resource,
    )


def _audit_payload(body: BaseModel) -> dict:
    payload = body.model_dump(mode="json")
    video_src = payload.get("video_src")
    if isinstance(video_src, str):
        payload["video_src"] = redact_video_source(video_src)
    return payload


# ── Request / Response schemas ──


class PipelineCreateRequest(BaseModel):
    """Request body for starting a new pipeline."""

    drone_id: str = Field(..., description="Drone providing the video stream")
    intersection_id: str = Field(..., description="Intersection to monitor")
    video_src: str = Field(
        ...,
        description="Video source: RTSP URL, file path, or camera index",
    )
    road_data_version: str | None = Field(default=None, min_length=1, max_length=100)
    map_version_id: str | None = Field(default=None, min_length=1, max_length=40)
    telemetry_source: str | None = Field(
        default=None,
        description="Telemetry source override, e.g. srt or file",
    )
    telemetry_file_path: str | None = Field(
        default=None,
        description="Telemetry file path for offline replay",
    )
    telemetry_time_offset_sec: float | None = Field(default=None, ge=-86400, le=86400)
    telemetry_sync_tolerance_sec: float | None = Field(default=None, gt=0, le=60)
    tracking_profile: str = Field(
        default="hover_cruise_v1", pattern="^(hover_cruise_v1|hover_only_legacy)$"
    )


class PipelineResponse(BaseModel):
    """Pipeline instance state."""

    pipeline_id: str
    drone_id: str
    intersection_id: str
    mission_id: str | None = None
    source_profile_id: str | None = None
    inter_id: str | None = None
    road_data_version: str | None = None
    video_src: str
    map_version_id: str | None
    candidate_only: bool = False
    topic_name: str
    camera_id: int
    video_port: int
    video_stream_url: str
    road_context_status: str = "missing"
    quality_status: str = "unverified"
    tracking_profile: str = "hover_cruise_v1"
    capabilities: dict[str, bool | None]
    capability_reasons: dict[str, list[str]]
    status: str
    started_at: float
    stopped_at: float
    error_message: str
    uptime_seconds: float


# ── Helpers ──


def _get_pm(request: Request):
    """Get the PipelineManager from app state, or raise 503."""
    pm = getattr(request.app.state, "pipeline_manager", None)
    if pm is None:
        raise HTTPException(
            status_code=503,
            detail="PipelineManager not initialized",
        )
    return pm


async def _with_runtime_capabilities(request: Request, pipelines: list[dict]) -> list[dict]:
    """Overlay active-process metadata with the last canonical stats sample."""
    metric_store = getattr(request.app.state, "metric_store", None)
    read_quality = getattr(metric_store, "pipeline_runtime_quality", None)
    if read_quality is None or not pipelines:
        return pipelines
    try:
        runtime_quality = await read_quality(
            [str(item.get("pipeline_id") or "") for item in pipelines]
        )
    except Exception as exc:  # Keep process monitoring available during DB outages.
        logger.warning("pipeline runtime capability lookup failed: %s", exc)
        return pipelines
    enriched = []
    for item in pipelines:
        payload = dict(item)
        pipeline_id = str(payload.get("pipeline_id") or "")
        if pipeline_id in runtime_quality:
            capabilities, reasons = capability_report_from_runtime_quality(
                runtime_quality[pipeline_id]
            )
            payload["capabilities"] = capabilities
            payload["capability_reasons"] = reasons
        enriched.append(payload)
    return enriched


# ── Endpoints ──


@router.get(
    "", response_model=list[PipelineResponse], summary="List all pipeline instances"
)
async def list_pipelines(request: Request):
    """Return all pipeline instances and their current status."""
    pm = _get_pm(request)
    return await _with_runtime_capabilities(request, pm.list_pipelines())


@router.get("/summary", summary="Pipeline fleet summary")
async def pipeline_summary(request: Request):
    """Return counts of active / stopped / error pipelines."""
    pm = _get_pm(request)
    pipelines = pm.list_pipelines()
    return {
        "total": len(pipelines),
        "running": sum(1 for p in pipelines if p["status"] == "running"),
        "stopped": sum(1 for p in pipelines if p["status"] == "stopped"),
        "error": sum(1 for p in pipelines if p["status"] == "error"),
    }


@router.get("/proxy-map", summary="Camera ID → MJPEG port mapping")
async def proxy_map(request: Request):
    """Return the legacy diagnostic mapping of running camera IDs to ports."""
    pm = _get_pm(request)
    pipelines = pm.list_pipelines()
    return {
        str(p["camera_id"]): p["video_port"]
        for p in pipelines
        if p["status"] == "running"
    }


@router.post(
    "",
    response_model=PipelineResponse,
    status_code=201,
    summary="Start a new detection pipeline",
)
async def start_pipeline(body: PipelineCreateRequest, request: Request):
    """Start a detection pipeline bound to a drone and intersection.

    The pipeline runs as a child process executing
    ``main_optimized.py`` with the provided video source and roads
    configuration. Results are published using the canonical UAV Kafka
    topics, including ``uav_statistics_{camera_id}``,
    ``uav_track_complete_{camera_id}``, and ``uav_conflicts_{camera_id}``.
    """
    actor = _require_role(request, "operator", "admin")
    pm = _get_pm(request)
    await _audit(
        request,
        actor,
        "pipeline.start",
        body.intersection_id,
        _audit_payload(body),
    )
    try:
        context = None
        if body.map_version_id or body.road_data_version:
            if not body.map_version_id or not body.road_data_version:
                raise ValueError("map_version_id and road_data_version must be supplied together")
            road_context = getattr(request.app.state, "road_context", None)
            if road_context is None:
                raise ValueError("RoadContext is unavailable")
            try:
                selected = await road_context.get(
                    body.intersection_id, body.road_data_version
                )
            except LookupError:
                selected = None
            if (
                selected is not None
                and selected.map_version_id == body.map_version_id
                and selected.runtime_map_bundle
            ):
                context = selected
        pipeline = await pm.start_pipeline(
            drone_id=body.drone_id,
            intersection_id=body.intersection_id,
            video_src=body.video_src,
            runtime_map_bundle=context.runtime_map_bundle if context else None,
            telemetry_source=body.telemetry_source,
            telemetry_file_path=body.telemetry_file_path,
            telemetry_time_offset_sec=body.telemetry_time_offset_sec,
            telemetry_sync_tolerance_sec=body.telemetry_sync_tolerance_sec,
            inter_id=body.intersection_id,
            road_data_version=body.road_data_version,
            road_context_status=(
                "complete" if context else "version_mismatch" if body.map_version_id else "missing"
            ),
            quality_status="verified" if context else "degraded",
            tracking_profile=body.tracking_profile,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return pipeline.to_dict()


class PipelineRegisterRequest(BaseModel):
    """Request body for registering an externally-running pipeline."""

    drone_id: str
    intersection_id: str
    source_profile_id: str = Field(min_length=1, max_length=100)
    inter_id: str | None = Field(default=None, min_length=1, max_length=100)
    video_src: str
    map_version_id: str | None = Field(default=None, min_length=1, max_length=40)
    road_data_version: str | None = Field(default=None, min_length=1, max_length=100)
    camera_id: int | None = Field(default=None, ge=1, le=65535)
    video_port: int | None = Field(default=None, ge=1024, le=65535)
    topic_name: str | None = None
    video_stream_url: str | None = None
    tracking_profile: str = Field(
        default="hover_cruise_v1", pattern="^(hover_cruise_v1|hover_only_legacy)$"
    )
    candidate_only: bool = False


@router.post(
    "/register",
    response_model=PipelineResponse,
    status_code=201,
    summary="Register an externally-running pipeline",
)
async def register_pipeline(body: PipelineRegisterRequest, request: Request):
    """Register a pipeline that was started outside the Platform.

    Use this when the pipeline is running locally (e.g. via
    ``python main_optimized.py``) and the Platform container does not
    have the pipeline dependencies.
    """
    actor = _require_role(request, "admin")
    pm = _get_pm(request)
    await _audit(
        request,
        actor,
        "pipeline.register",
        body.intersection_id,
        _audit_payload(body),
    )
    try:
        verified_map_version_id = body.map_version_id
        road_context_status = "missing"
        quality_status = "degraded"
        if body.candidate_only:
            if body.map_version_id is not None or body.road_data_version is not None:
                raise ValueError("candidate-only registration must not claim road context")
            if body.tracking_profile != "hover_cruise_v1":
                raise ValueError("candidate-only registration requires hover_cruise_v1")
            quality_status = "unverified"
        elif body.map_version_id or body.road_data_version:
            if not body.map_version_id or not body.road_data_version:
                raise ValueError("map_version_id and road_data_version must be supplied together")
            road_context = getattr(request.app.state, "road_context", None)
            if road_context is None:
                raise ValueError("RoadContext is unavailable")
            try:
                context = await road_context.get(body.intersection_id, body.road_data_version)
            except LookupError:
                context = None
            if (
                context is None
                or context.map_version_id != body.map_version_id
                or context.map_status != "lane_verified"
            ):
                verified_map_version_id = None
                road_context_status = "version_mismatch"
            else:
                road_context_status = "complete"
                quality_status = "verified"
        pipeline = pm.register_pipeline(
            drone_id=body.drone_id,
            intersection_id=body.intersection_id,
            video_src=body.video_src,
            map_version_id=verified_map_version_id,
            camera_id=body.camera_id,
            video_port=body.video_port,
            topic_name=body.topic_name,
            video_stream_url=body.video_stream_url,
            source_profile_id=body.source_profile_id,
            inter_id=body.inter_id or body.intersection_id,
            tracking_profile=body.tracking_profile,
            candidate_only=body.candidate_only,
            road_context_status=road_context_status,
            quality_status=quality_status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return pipeline.to_dict()


@router.get(
    "/{pipeline_id}", response_model=PipelineResponse, summary="Get pipeline details"
)
async def get_pipeline(pipeline_id: str, request: Request):
    pm = _get_pm(request)
    pipeline = pm.get_pipeline(pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return (await _with_runtime_capabilities(request, [pipeline.to_dict()]))[0]


@router.get("/{pipeline_id}/status", summary="Get pipeline health status")
async def get_pipeline_status(pipeline_id: str, request: Request):
    pm = _get_pm(request)
    pipeline = pm.get_pipeline(pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    proc = pipeline.process
    alive = proc is not None and proc.returncode is None

    return {
        "pipeline_id": pipeline_id,
        "status": pipeline.status.value,
        "process_alive": alive,
        "pid": proc.pid if proc else None,
        "return_code": proc.returncode if proc else None,
        "uptime_seconds": pipeline.to_dict()["uptime_seconds"],
    }


@router.delete("/{pipeline_id}", summary="Stop and remove a pipeline")
async def stop_pipeline(pipeline_id: str, request: Request):
    """Gracefully stop a pipeline.  Sends SIGTERM, then SIGKILL after 10s."""
    actor = _require_role(request, "operator", "admin")
    pm = _get_pm(request)
    await _audit(request, actor, "pipeline.stop", pipeline_id)
    pipeline = await pm.stop_pipeline(pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return pipeline.to_dict()
