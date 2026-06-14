"""Drone and telemetry API endpoints."""
from fastapi import APIRouter

from app.models.drone_store import (
    DRONES,
    MISSIONS,
    get_drone_trajectory as read_drone_trajectory,
    get_telemetry_history as read_telemetry_history,
)


router = APIRouter(prefix="", tags=["drones"])

# Telemetry router (mounted at /api/v1/telemetry by main.py)
telemetry_router = APIRouter(prefix="/telemetry", tags=["telemetry"])


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
