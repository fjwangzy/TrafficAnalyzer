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
# T-206: 空初始化，不再包含硬编码 mock 数据。
# 无人机通过 Kafka telemetry 消息自动注册（update_drone_telemetry），
# 或通过 Pipeline API 创建任务时绑定。
DRONES: dict[str, dict] = {}


# ─── Missions ───
# T-206: 空初始化，不再包含硬编码 mock 数据。
# 任务通过 Pipeline API 动态创建。
MISSIONS: dict[str, dict] = {}


# ─── Intersection ↔ Drone mapping ───
# T-206: 空初始化，通过 Pipeline API 动态绑定。
_INTERSECTION_DRONE_MAP: dict[str, str] = {}


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

