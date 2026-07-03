"""Drone and telemetry API endpoints."""
import time
import uuid

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.models.drone_store import (
    DRONES,
    MISSIONS,
    assign_drone_to_intersection,
    get_drone_trajectory as read_drone_trajectory,
    get_telemetry_history as read_telemetry_history,
)


router = APIRouter(prefix="", tags=["drones"])

# Telemetry router (mounted at /api/v1/telemetry by main.py)
telemetry_router = APIRouter(prefix="/telemetry", tags=["telemetry"])


class MissionCreateRequest(BaseModel):
    """Create a mission and bind it to a detection pipeline."""

    name: str | None = Field(default=None, description="Mission display name")
    drone_id: str = Field(..., description="Drone assigned to the mission")
    intersection_id: str = Field(..., description="Intersection to monitor")
    video_src: str = Field(..., description="MP4, RTSP, or camera source")
    roads_json: str = Field(default="configs/entry_exit_lanes.json")
    telemetry_source: str | None = None
    telemetry_file_path: str | None = None


@router.get("/drones")
async def list_drones():
    """List all drones."""
    return list(DRONES.values())


@router.get("/drones/{drone_id}")
async def get_drone(drone_id: str):
    """Get a single drone by ID."""
    drone = DRONES.get(drone_id)
    if not drone:
        return {"error": "not_found", "id": drone_id}
    return drone


@router.get("/drones/{drone_id}/trajectory")
async def get_drone_trajectory(
    drone_id: str,
    start: str = "",
    end: str = "",
):
    """Get drone flight trajectory from recorded telemetry."""
    drone = DRONES.get(drone_id)
    if not drone:
        return {"error": "not_found", "id": drone_id}
    return read_drone_trajectory(drone_id)


@router.get("/drones/{drone_id}/hover-points")
async def get_hover_points(drone_id: str):
    """Get recorded drone hover points."""
    drone = DRONES.get(drone_id)
    if not drone:
        return {"error": "not_found", "id": drone_id}
    return [
        point
        for point in read_drone_trajectory(drone_id)
        if point.get("is_hovering")
    ]


@router.get("/missions")
async def list_missions():
    """List all missions."""
    return list(MISSIONS.values())


@router.post("/missions", status_code=status.HTTP_201_CREATED)
async def create_mission(body: MissionCreateRequest, request: Request):
    """Create a mission and immediately start its detection pipeline."""
    pm = getattr(request.app.state, "pipeline_manager", None)
    if pm is None:
        raise HTTPException(
            status_code=503,
            detail="PipelineManager not initialized",
        )

    mission_id = f"mission-{uuid.uuid4().hex[:8]}"
    now = time.time()
    mission = {
        "id": mission_id,
        "name": body.name or mission_id,
        "drone_id": body.drone_id,
        "intersection_id": body.intersection_id,
        "video_src": body.video_src,
        "roads_json": body.roads_json,
        "telemetry_source": body.telemetry_source,
        "telemetry_file_path": body.telemetry_file_path,
        "status": "starting",
        "created_at": now,
        "updated_at": now,
        "pipeline_id": None,
        "pipeline": None,
    }
    MISSIONS[mission_id] = mission

    if body.drone_id not in DRONES:
        DRONES[body.drone_id] = {
            "id": body.drone_id,
            "name": body.drone_id,
            "status": "assigned",
            "battery_pct": 100,
            "current_intersection_id": body.intersection_id,
            "last_telemetry": None,
        }
    assign_drone_to_intersection(body.drone_id, body.intersection_id)

    try:
        pipeline = await pm.start_pipeline(
            drone_id=body.drone_id,
            intersection_id=body.intersection_id,
            video_src=body.video_src,
            roads_json=body.roads_json,
            telemetry_source=body.telemetry_source,
            telemetry_file_path=body.telemetry_file_path,
        )
    except Exception as exc:
        mission["status"] = "error"
        mission["error_message"] = str(exc)
        mission["updated_at"] = time.time()
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    pipeline_data = pipeline.to_dict()
    mission["pipeline_id"] = pipeline_data["pipeline_id"]
    mission["pipeline"] = pipeline_data
    mission["status"] = (
        "running" if pipeline_data.get("status") == "running" else "error"
    )
    mission["error_message"] = pipeline_data.get("error_message", "")
    mission["updated_at"] = time.time()
    return mission


@router.get("/missions/{mission_id}")
async def get_mission(mission_id: str):
    """Get a single mission by ID."""
    mission = MISSIONS.get(mission_id)
    if not mission:
        return {"error": "not_found", "id": mission_id}
    return mission


# ─── Telemetry endpoints ───


@telemetry_router.get("/{drone_id}")
async def get_telemetry(drone_id: str):
    """Get latest telemetry for a drone."""
    drone = DRONES.get(drone_id)
    if not drone:
        return {"error": "not_found", "id": drone_id}
    telem = drone.get("last_telemetry")
    if not telem:
        return {"error": "no_telemetry", "id": drone_id}
    return telem


@telemetry_router.get("/{drone_id}/history")
async def get_telemetry_history(drone_id: str, limit: int = 50):
    """Get telemetry history for a drone."""
    drone = DRONES.get(drone_id)
    if not drone:
        return {"error": "not_found", "id": drone_id}
    return read_telemetry_history(drone_id, limit=limit)
