"""Drone data store — in-memory state for drones and missions."""
import time


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
        "status": "offline",
        "battery_pct": 20,
        "current_intersection_id": None,
        "last_telemetry": None,
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
