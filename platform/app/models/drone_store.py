"""Drone data store — in-memory state for drones and missions.

This module is the single source of truth for drone state within the
platform process.  It is updated from two sources:

1. **Kafka telemetry messages** — published by the detection pipeline's
   TelemetrySubscriber (or a future TelemetryKafkaNode).  Handled by
   ``update_drone_telemetry()``.

2. **Kafka stats messages** — the ``drone_position`` field inside every
   statistics message from KafkaProducerNode / MotionCompensationNode.
   Handled by ``update_drone_from_stats()``.

Both update functions are called by ``KafkaConsumerService`` in
``platform/app/kafka/consumer.py``.
"""
import math
import time
import logging

logger = logging.getLogger(__name__)


# ─── Drone Registry ───
DRONES: dict[str, dict] = {
    "drone_001": {
        "id": "drone_001",
        "name": "M300 RTK #1",
        "status": "flying",
        "battery_pct": 78,
        "current_intersection_id": "INT_camera_1",
        "last_telemetry": {
            "drone_id": "drone_001",
            "intersection_id": "INT_camera_1",
            "lat": 36.70291,
            "lon": 117.02228,
            "alt_agl": 120.0,
            "gimbal_pitch": -85.0,
            "gimbal_roll": 0.0,
            "gimbal_yaw": 45.0,
            "drone_pitch": 2.1,
            "drone_roll": -1.3,
            "drone_yaw": 45.0,
            "gps_type": "RTK_FIXED",
            "satellite_count": 24,
            "wind_speed": 3.2,
            "battery_pct": 78,
            "video_bitrate": 8.5,
            "timestamp": time.time(),
        },
    },
    "drone_002": {
        "id": "drone_002",
        "name": "M300 RTK #2",
        "status": "hovering",
        "battery_pct": 65,
        "current_intersection_id": "INT_camera_2",
        "last_telemetry": {
            "drone_id": "drone_002",
            "intersection_id": "INT_camera_2",
            "lat": 36.70501,
            "lon": 117.02501,
            "alt_agl": 100.0,
            "gimbal_pitch": -90.0,
            "gimbal_roll": 0.0,
            "gimbal_yaw": 0.0,
            "drone_pitch": 0.0,
            "drone_roll": 0.0,
            "drone_yaw": 0.0,
            "gps_type": "RTK_FIXED",
            "satellite_count": 22,
            "wind_speed": 2.8,
            "battery_pct": 65,
            "video_bitrate": 7.2,
            "timestamp": time.time(),
        },
    },
    "drone_003": {
        "id": "drone_003",
        "name": "M300 RTK #3",
        "status": "flying",
        "battery_pct": 85,
        "current_intersection_id": "INT_camera_3",
        "last_telemetry": {
            "drone_id": "drone_003",
            "intersection_id": "INT_camera_3",
            "lat": 36.70400,
            "lon": 117.02300,
            "alt_agl": 110.0,
            "gimbal_pitch": -88.0,
            "gimbal_roll": 0.0,
            "gimbal_yaw": 0.0,
            "drone_pitch": 1.5,
            "drone_roll": -0.8,
            "drone_yaw": 0.0,
            "gps_type": "RTK_FIXED",
            "satellite_count": 20,
            "wind_speed": 2.5,
            "battery_pct": 85,
            "video_bitrate": 9.0,
            "timestamp": time.time(),
        },
    },
}


# ─── Missions ───
MISSIONS: dict[str, dict] = {
    "mission_001": {
        "id": "mission_001",
        "name": "小清河水屯巡检",
        "intersection_id": "INT_camera_1",
        "drone_id": "drone_001",
        "status": "active",
        "waypoints": [
            {"lat": 36.70291, "lon": 117.02228, "alt_agl": 120, "hover_sec": 300},
            {"lat": 36.70320, "lon": 117.02250, "alt_agl": 130, "hover_sec": 180},
        ],
        "created_at": "2026-05-28T07:00:00Z",
    },
    "mission_002": {
        "id": "mission_002",
        "name": "和平路光华街巡检",
        "intersection_id": "INT_camera_2",
        "drone_id": "drone_002",
        "status": "active",
        "waypoints": [
            {"lat": 36.70501, "lon": 117.02501, "alt_agl": 100, "hover_sec": 240},
        ],
        "created_at": "2026-05-28T07:30:00Z",
    },
}


# ─── Intersection ↔ Drone mapping ───
# Populated at startup from MISSIONS, then updated dynamically as
# drones are reassigned via the Pipeline API.
_INTERSECTION_DRONE_MAP: dict[str, str] = {}
for _m in MISSIONS.values():
    _INTERSECTION_DRONE_MAP[_m["intersection_id"]] = _m["drone_id"]


# ─── Telemetry Update Functions ───


def update_drone_telemetry(drone_id: str, telemetry: dict) -> None:
    """Update drone state from a Kafka telemetry message.

    Called by ``KafkaConsumerService._handle_telemetry()`` when a
    ``msg_type=telemetry`` message arrives from the detection pipeline.

    Args:
        drone_id: Drone identifier (e.g., ``"drone_001"``).
        telemetry: Telemetry dict with keys like ``lat``, ``lon``,
            ``alt_agl``, ``gimbal_pitch``, ``gimbal_yaw``,
            ``battery_pct``, etc.
    """
    if drone_id not in DRONES:
        # Auto-register previously unknown drone
        DRONES[drone_id] = {
            "id": drone_id,
            "name": drone_id,
            "status": "flying",
            "battery_pct": telemetry.get("battery_pct", 100),
            "current_intersection_id": telemetry.get("intersection_id"),
            "last_telemetry": None,
        }
        logger.info(f"Auto-registered new drone: {drone_id}")

    drone = DRONES[drone_id]
    drone["last_telemetry"] = telemetry
    drone["battery_pct"] = telemetry.get("battery_pct", drone.get("battery_pct", 100))

    intersection_id = telemetry.get("intersection_id")
    if intersection_id:
        drone["current_intersection_id"] = intersection_id
        _INTERSECTION_DRONE_MAP[intersection_id] = drone_id

    # Derive status from telemetry freshness and hover flag
    ts = telemetry.get("timestamp", 0)
    age = time.time() - ts if ts else float("inf")
    if age < 30:
        drone["status"] = "hovering" if telemetry.get("is_hovering") else "flying"
    elif age > 60:
        drone["status"] = "offline"


def update_drone_from_stats(
    intersection_id: str,
    drone_position: dict,
    is_hovering: bool = False,
) -> None:
    """Update drone position from a stats message's ``drone_position`` field.

    Called by ``KafkaConsumerService._handle_stats()`` when a statistics
    message contains drone position data from MotionCompensationNode.

    The stats message carries ENU (East-North-Up) offsets relative to a
    GPS anchor.  This function reconstructs absolute lat/lon and writes
    the result into the drone's ``last_telemetry`` dict.

    Args:
        intersection_id: Intersection ID (e.g., ``"INT_camera_1"``).
        drone_position: Dict with ``anchor_lat``, ``anchor_lon``,
            ``easting_m``, ``northing_m``.
        is_hovering: Whether the drone is currently hovering.
    """
    drone_id = _INTERSECTION_DRONE_MAP.get(intersection_id)
    if not drone_id or drone_id not in DRONES:
        return

    drone = DRONES[drone_id]
    telem = drone.get("last_telemetry") or {}

    # Reconstruct lat/lon from GPS anchor + ENU offset
    anchor_lat = drone_position.get("anchor_lat", telem.get("lat", 0))
    anchor_lon = drone_position.get("anchor_lon", telem.get("lon", 0))
    easting_m = drone_position.get("easting_m", 0)
    northing_m = drone_position.get("northing_m", 0)

    lat = anchor_lat + northing_m / 111320
    lon = anchor_lon + easting_m / (111320 * math.cos(math.radians(anchor_lat)))

    telem.update({
        "drone_id": drone_id,
        "intersection_id": intersection_id,
        "lat": round(lat, 6),
        "lon": round(lon, 6),
        "is_hovering": is_hovering,
        "timestamp": time.time(),
    })

    drone["last_telemetry"] = telem
    drone["current_intersection_id"] = intersection_id
    drone["status"] = "hovering" if is_hovering else "flying"


def get_drone_for_intersection(intersection_id: str) -> dict | None:
    """Return the drone currently assigned to *intersection_id*, or ``None``."""
    drone_id = _INTERSECTION_DRONE_MAP.get(intersection_id)
    return DRONES.get(drone_id) if drone_id else None


def assign_drone_to_intersection(drone_id: str, intersection_id: str) -> None:
    """Assign a drone to monitor an intersection (called by PipelineManager)."""
    _INTERSECTION_DRONE_MAP[intersection_id] = drone_id
    if drone_id in DRONES:
        DRONES[drone_id]["current_intersection_id"] = intersection_id

