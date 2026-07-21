"""Pipeline management API — start/stop/monitor detection pipelines."""
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.services.pipeline_manager import redact_video_source

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
    roads_json: str = Field(
        default="",
        description="Must be empty; pipelines start without road/lane annotation parameters",
    )
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


class PipelineResponse(BaseModel):
    """Pipeline instance state."""

    pipeline_id: str
    drone_id: str
    intersection_id: str
    video_src: str
    roads_json: str
    topic_name: str
    camera_id: int
    video_port: int
    video_stream_url: str
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


# ── Endpoints ──


@router.get("", summary="List all pipeline instances")
async def list_pipelines(request: Request):
    """Return all pipeline instances and their current status."""
    pm = _get_pm(request)
    return pm.list_pipelines()


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


@router.post("", status_code=201, summary="Start a new detection pipeline")
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
        pipeline = await pm.start_pipeline(
            drone_id=body.drone_id,
            intersection_id=body.intersection_id,
            video_src=body.video_src,
            roads_json=body.roads_json,
            telemetry_source=body.telemetry_source,
            telemetry_file_path=body.telemetry_file_path,
            telemetry_time_offset_sec=body.telemetry_time_offset_sec,
            telemetry_sync_tolerance_sec=body.telemetry_sync_tolerance_sec,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return pipeline.to_dict()


class PipelineRegisterRequest(BaseModel):
    """Request body for registering an externally-running pipeline."""

    drone_id: str
    intersection_id: str
    video_src: str
    roads_json: str = ""
    camera_id: int | None = Field(default=None, ge=1, le=65535)
    video_port: int | None = Field(default=None, ge=1024, le=65535)
    topic_name: str | None = None
    video_stream_url: str | None = None


@router.post("/register", status_code=201, summary="Register an externally-running pipeline")
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
        pipeline = pm.register_pipeline(
            drone_id=body.drone_id,
            intersection_id=body.intersection_id,
            video_src=body.video_src,
            roads_json=body.roads_json,
            camera_id=body.camera_id,
            video_port=body.video_port,
            topic_name=body.topic_name,
            video_stream_url=body.video_stream_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return pipeline.to_dict()


@router.get("/{pipeline_id}", summary="Get pipeline details")
async def get_pipeline(pipeline_id: str, request: Request):
    pm = _get_pm(request)
    pipeline = pm.get_pipeline(pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return pipeline.to_dict()


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
