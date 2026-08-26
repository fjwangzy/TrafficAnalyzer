"""DJI Cloud telemetry normalization with explicit altitude and lens lineage.

The project historically treated ``height`` as an AGL proxy.  That is unsafe
for Cloud API sources whose height is an ellipsoid altitude.  New source
profiles can request the strict ``laser_target`` policy; legacy profiles keep
their recorded behaviour until their own source semantics are verified.
"""

from __future__ import annotations

import math
from typing import Any


LASER_NORMAL = 0


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _camera_for_recording(payload: dict, osd: dict) -> tuple[dict | None, str | None]:
    """Resolve the declared recorded camera stream instead of trusting OSD zoom."""
    payload_index = osd.get("payload_index")
    cameras = payload.get("cameras")
    if not isinstance(cameras, list):
        return None, None
    candidates = [
        item for item in cameras
        if isinstance(item, dict)
        and (payload_index is None or item.get("payload_index") == payload_index)
        and "vision" in (item.get("video_storage_settings") or [])
    ]
    if len(candidates) != 1:
        return None, None
    return candidates[0], "vision"


def extract_dji_telemetry(
    payload: dict,
    timestamp: float,
    *,
    agl_policy: str = "legacy_height",
    laser_residual_max_m: float = 0.2,
    camera_lens_policy: str = "standard_wide_1x",
) -> dict:
    """Return one canonical telemetry record with provenance-rich quality fields.

    ``laser_target`` intentionally has no elevation fallback: a source that
    cannot prove laser-derived AGL is not eligible for formal world analytics.
    """
    osd = payload.get("99-0-0", payload)
    if not isinstance(osd, dict):
        osd = payload
    ellipsoid_height = _number(payload.get("height"))
    takeoff_relative = _number(payload.get("elevation"))
    target_altitude = _number(osd.get("measure_target_altitude"))
    laser_range = _number(osd.get("measure_target_distance"))
    laser_state = osd.get("measure_target_error_state")
    gimbal_pitch = _number(osd.get("gimbal_pitch"))
    vertical_laser = (
        laser_range * abs(math.sin(math.radians(gimbal_pitch)))
        if laser_range is not None and gimbal_pitch is not None
        else None
    )
    target_gap = (
        ellipsoid_height - target_altitude
        if ellipsoid_height is not None and target_altitude is not None
        else None
    )
    residual = (
        abs(target_gap - vertical_laser)
        if target_gap is not None and vertical_laser is not None
        else None
    )
    laser_verified = bool(
        laser_state == LASER_NORMAL
        and target_gap is not None
        and target_gap > 0
        and residual is not None
        and residual <= laser_residual_max_m
    )

    camera, detected_camera_stream = _camera_for_recording(payload, osd)
    camera_zoom = _number(camera.get("zoom_factor")) if camera else None
    if camera_lens_policy == "standard_wide_1x":
        camera_stream = "vision"
        camera_lens_verified = True
        zoom_factor = 1.0
        zoom_factor_source = "source_profile_standard_wide_1x"
    elif camera_lens_policy == "auto_from_telemetry":
        camera_stream = detected_camera_stream
        camera_lens_verified = bool(
            camera_stream == "vision"
            and camera_zoom is not None
            and abs(camera_zoom - 1.0) <= 0.05
        )
        zoom_factor = 1.0 if camera_lens_verified else None
        zoom_factor_source = "vision_wide_1x" if camera_lens_verified else "unavailable"
    else:
        raise ValueError(f"unsupported camera lens policy: {camera_lens_policy}")
    if agl_policy == "laser_target":
        altitude_agl = target_gap if laser_verified else None
        agl_source = "laser_target_altitude" if laser_verified else "unavailable"
        agl_quality = "verified" if laser_verified else "unavailable"
    elif agl_policy == "legacy_height":
        altitude_agl = ellipsoid_height
        agl_source = "legacy_height"
        agl_quality = "legacy"
    else:
        raise ValueError(f"unsupported telemetry AGL policy: {agl_policy}")

    return {
        "timestamp": float(timestamp),
        "latitude": payload.get("latitude"),
        "longitude": payload.get("longitude"),
        "height": ellipsoid_height,
        "elevation": takeoff_relative,
        "altitude_ellipsoid_m": ellipsoid_height,
        "altitude_takeoff_relative_m": takeoff_relative,
        "laser_target_altitude_m": target_altitude,
        "laser_range_m": laser_range,
        "laser_state": laser_state,
        "altitude_agl": altitude_agl,
        "altitude_agl_source": agl_source,
        "altitude_agl_quality": agl_quality,
        "altitude_agl_residual_m": residual,
        "attitude_head": payload.get("attitude_head", 0) or 0,
        "attitude_pitch": payload.get("attitude_pitch", 0) or 0,
        "gimbal_pitch": gimbal_pitch if gimbal_pitch is not None else -90.0,
        "gimbal_yaw": osd.get("gimbal_yaw", 0),
        "gimbal_roll": osd.get("gimbal_roll", 0),
        "camera_stream": camera_stream or "unresolved",
        "camera_lens_verified": camera_lens_verified,
        "zoom_factor": zoom_factor,
        "zoom_factor_source": zoom_factor_source,
        "horizontal_speed": payload.get("horizontal_speed"),
        "vertical_speed": payload.get("vertical_speed"),
    }
