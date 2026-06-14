"""Pipeline management API — start/stop/monitor detection pipelines."""
import logging
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pipelines", tags=["pipelines"])


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
        default="configs/entry_exit_lanes.json",
        description="Path to road polygon JSON (relative to project root)",
    )
    telemetry_source: str | None = Field(
        default=None,
        description="Telemetry source override, e.g. srt or file",
    )
    telemetry_file_path: str | None = Field(
        default=None,
        description="Telemetry file path for offline replay",
    )


class PipelineResponse(BaseModel):
    """Pipeline instance state."""

    pipeline_id: str
    drone_id: str
    intersection_id: str
    video_src: str
    roads_json: str
    topic_name: str
    camera_id: int
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


def _resolve_roads_json(request: Request, intersection_id: str, roads_json: str) -> str:
    """Use saved lane annotation parameters when caller did not choose a file."""
    if roads_json != "configs/entry_exit_lanes.json":
        return roads_json

    store = getattr(request.app.state, "lane_annotation_store", None)
    if store is None:
        return roads_json

    annotation = store.get_annotation(intersection_id)
    if not annotation:
        return roads_json

    return annotation.get("export_path") or roads_json


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
    """Return a mapping of {camera_id: video_port} for running pipelines.

    Used by the Vite dev proxy to route ``/camera_N`` requests to the
    correct MJPEG server port (each pipeline binds to a unique port).
    """
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
    configuration.  Results are published to Kafka topics
    ``statistics_{camera_id}``, ``track_complete_{camera_id}``, and
    ``conflicts_{camera_id}``.
    """
    pm = _get_pm(request)
    pipeline = await pm.start_pipeline(
        drone_id=body.drone_id,
        intersection_id=body.intersection_id,
        video_src=body.video_src,
        roads_json=_resolve_roads_json(request, body.intersection_id, body.roads_json),
        telemetry_source=body.telemetry_source,
        telemetry_file_path=body.telemetry_file_path,
    )
    return pipeline.to_dict()


class PipelineRegisterRequest(BaseModel):
    """Request body for registering an externally-running pipeline."""

    drone_id: str
    intersection_id: str
    video_src: str
    roads_json: str = "configs/entry_exit_lanes.json"
    camera_id: int | None = None
    video_port: int | None = None
    topic_name: str | None = None


@router.post("/register", status_code=201, summary="Register an externally-running pipeline")
async def register_pipeline(body: PipelineRegisterRequest, request: Request):
    """Register a pipeline that was started outside the Platform.

    Use this when the pipeline is running locally (e.g. via
    ``python main_optimized.py``) and the Platform container does not
    have the pipeline dependencies.
    """
    pm = _get_pm(request)
    pipeline = pm.register_pipeline(
        drone_id=body.drone_id,
        intersection_id=body.intersection_id,
        video_src=body.video_src,
        roads_json=body.roads_json,
        camera_id=body.camera_id,
        video_port=body.video_port,
        topic_name=body.topic_name,
    )
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
    pm = _get_pm(request)
    pipeline = await pm.stop_pipeline(pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return pipeline.to_dict()
