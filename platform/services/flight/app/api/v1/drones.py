"""Drone and telemetry API endpoints."""
import random
import time
from fastapi import APIRouter

from app.models.drone_store import DRONES, MISSIONS

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
    """Get drone flight trajectory (simulated for POC)."""
    drone = DRONES.get(drone_id)
    if not drone:
        return {"error": "not_found", "id": drone_id}

    telem = drone.get("last_telemetry")
    if not telem:
        return []

    # Generate simulated trajectory points around current position
    base_lat = telem["lat"]
    base_lon = telem["lon"]
    points = []
    for i in range(20):
        points.append({
            "lat": base_lat + random.uniform(-0.001, 0.001),
            "lon": base_lon + random.uniform(-0.001, 0.001),
            "alt_agl": telem["alt_agl"] + random.uniform(-5, 5),
            "timestamp": time.time() - (20 - i) * 30,
        })
    return points


@router.get("/drones/{drone_id}/hover-points")
async def get_hover_points(drone_id: str):
    """Get drone hover points (simulated for POC)."""
    drone = DRONES.get(drone_id)
    if not drone:
        return {"error": "not_found", "id": drone_id}

    telem = drone.get("last_telemetry")
    if not telem:
        return []

    return [
        {
            "lat": telem["lat"],
            "lon": telem["lon"],
            "alt_agl": telem["alt_agl"],
            "duration_sec": 300,
            "timestamp": time.time() - 600,
        }
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
    """Get telemetry history for a drone (simulated for POC)."""
    drone = DRONES.get(drone_id)
    if not drone:
        return {"error": "not_found", "id": drone_id}
    telem = drone.get("last_telemetry")
    if not telem:
        return []

    # Generate simulated history points
    history = []
    base_lat = telem["lat"]
    base_lon = telem["lon"]
    now = time.time()
    for i in range(min(limit, 50)):
        history.append({
            "drone_id": drone_id,
            "lat": base_lat + random.uniform(-0.002, 0.002),
            "lon": base_lon + random.uniform(-0.002, 0.002),
            "alt_agl": telem["alt_agl"] + random.uniform(-10, 10),
            "battery_pct": max(0, telem["battery_pct"] - (limit - i)),
            "timestamp": now - (limit - i) * 10,
        })
    return history
