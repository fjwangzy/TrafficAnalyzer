"""Survey-only pixel/BEV/ENU geometry operations.

This module deliberately accepts and returns plain matrices/points so the same
interface is exercised by REST callers and tests.
"""

from __future__ import annotations

import math

import cv2
import numpy as np


DEFAULT_CAMERA_INTRINSICS = {
    "focal_length_mm": 4.5,
    "sensor_width_mm": 6.4,
    "sensor_height_mm": 3.6,
}


def compute_homography_from_telemetry(
    telemetry: dict,
    image_size: tuple[int, int],
    camera_intrinsics: dict | None = None,
) -> np.ndarray | None:
    """Return a pixel->local ENU homography from frame telemetry."""
    camera = {**DEFAULT_CAMERA_INTRINSICS, **(camera_intrinsics or {})}
    img_w, img_h = image_size
    agl = float(telemetry.get("altitude_agl") or telemetry.get("height") or 0)
    if agl <= 0 or img_w <= 0 or img_h <= 0:
        return None
    fl = float(camera["focal_length_mm"])
    sw = float(camera["sensor_width_mm"])
    sh = float(camera.get("sensor_height_mm") or sw * img_h / img_w)
    zoom = float(telemetry.get("zoom_factor") or 1.0)
    effective_fl = fl / zoom if zoom > 0 else fl
    g_pitch = math.radians(float(telemetry.get("gimbal_pitch", -90)))
    g_yaw = math.radians(float(telemetry.get("gimbal_yaw", 0)))
    g_roll = math.radians(float(telemetry.get("gimbal_roll", 0)))

    if abs(g_pitch + math.pi / 2) < math.radians(10):
        gsd_x = agl * sw / (effective_fl * img_w)
        gsd_y = agl * sh / (effective_fl * img_h)
        cx, cy = img_w / 2.0, img_h / 2.0
        cos_y, sin_y = math.cos(g_yaw), math.sin(g_yaw)
        homography = np.array(
            [
                [gsd_x * cos_y, -gsd_y * sin_y, 0],
                [-gsd_x * sin_y, -gsd_y * cos_y, 0],
                [0, 0, 1],
            ],
            dtype=np.float64,
        )
        offset = homography @ np.array([cx, cy, 1.0])
        homography[0, 2], homography[1, 2] = -offset[0], -offset[1]
        return homography

    fx = effective_fl * img_w / sw
    fy = effective_fl * img_h / sh
    intrinsic = np.array([[fx, 0, img_w / 2], [0, fy, img_h / 2], [0, 0, 1]], dtype=np.float64)
    flip = np.diag([1.0, -1.0, -1.0])
    cz, sz = math.cos(g_yaw), math.sin(g_yaw)
    cy, sy = math.cos(g_pitch + math.pi / 2), math.sin(g_pitch + math.pi / 2)
    cx, sx = math.cos(g_roll), math.sin(g_roll)
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]], dtype=np.float64)
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], dtype=np.float64)
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]], dtype=np.float64)
    rotation = rz @ ry @ rx @ flip
    projection = intrinsic @ np.hstack([rotation, np.array([[0], [0], [agl]], dtype=np.float64)])
    world_to_pixel = np.column_stack([projection[:, 0], projection[:, 1], projection[:, 3]])
    if abs(np.linalg.det(world_to_pixel)) < 1e-10:
        return None
    homography = np.linalg.inv(world_to_pixel)
    center = homography @ np.array([img_w / 2, img_h / 2, 1.0])
    center = center[:2] / center[2]
    adjust = np.eye(3)
    adjust[0, 2], adjust[1, 2] = -center[0], -center[1]
    return adjust @ homography


def transform_points(points: list[list[float]], matrix: list | np.ndarray) -> list[list[float]]:
    pts = np.asarray(points, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] != 2:
        raise ValueError("geometry points must be [x,y] pairs")
    mat = np.asarray(matrix, dtype=np.float64)
    projected = (mat @ np.column_stack([pts, np.ones(len(pts))]).T).T
    if np.any(np.abs(projected[:, 2]) < 1e-10):
        raise ValueError("geometry crosses an invalid projective horizon")
    result = projected[:, :2] / projected[:, 2:3]
    if not np.all(np.isfinite(result)):
        raise ValueError("geometry produces non-finite metric coordinates")
    return result.tolist()


def create_bev(frame: np.ndarray, homography: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Warp a source frame to a bounded north-up ENU view.

    Returns the raster and source-image->BEV matrix.
    """
    h, w = frame.shape[:2]
    corners = transform_points([[0, 0], [w, 0], [w, h], [0, h]], homography)
    corners_np = np.asarray(corners)
    min_x, min_y = corners_np.min(axis=0)
    max_x, max_y = corners_np.max(axis=0)
    span_x, span_y = max(max_x - min_x, 1.0), max(max_y - min_y, 1.0)
    scale = min(12.0, 1800.0 / span_x, 1000.0 / span_y)
    out_w = int(max(640, min(1800, math.ceil(span_x * scale))))
    out_h = int(max(360, min(1000, math.ceil(span_y * scale))))
    world_to_view = np.array(
        [[scale, 0, -min_x * scale], [0, -scale, max_y * scale], [0, 0, 1]],
        dtype=np.float64,
    )
    image_to_view = world_to_view @ homography
    bev = cv2.warpPerspective(frame, image_to_view, (out_w, out_h), flags=cv2.INTER_LINEAR)
    return bev, image_to_view


def calculate_measurement(
    geometry_type: str,
    view_points: list[list[float]],
    pixel_to_metric: list | np.ndarray,
) -> tuple[list[list[float]], dict]:
    minimum = {"point": 1, "line": 2, "polyline": 2, "area": 3, "object": 3}
    if geometry_type not in minimum:
        raise ValueError("unsupported geometry_type")
    if len(view_points) < minimum[geometry_type]:
        raise ValueError(f"{geometry_type} requires at least {minimum[geometry_type]} points")
    metric = np.asarray(transform_points(view_points, pixel_to_metric), dtype=np.float64)
    values: dict[str, float | list[float]] = {}
    if geometry_type == "point":
        values["easting_m"] = round(float(metric[0, 0]), 4)
        values["northing_m"] = round(float(metric[0, 1]), 4)
    elif geometry_type in {"line", "polyline"}:
        values["length_m"] = round(float(np.linalg.norm(np.diff(metric, axis=0), axis=1).sum()), 4)
    else:
        closed = np.vstack([metric, metric[0]])
        perimeter = np.linalg.norm(np.diff(closed, axis=0), axis=1).sum()
        area = 0.5 * abs(np.dot(metric[:, 0], np.roll(metric[:, 1], 1)) - np.dot(metric[:, 1], np.roll(metric[:, 0], 1)))
        values["area_m2"] = round(float(area), 4)
        values["perimeter_m"] = round(float(perimeter), 4)
    return metric.tolist(), values
