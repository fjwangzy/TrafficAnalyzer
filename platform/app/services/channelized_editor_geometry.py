"""Deterministic geometry shared by the channelized-map registration API."""

from __future__ import annotations

import math
from typing import Any

import numpy as np


REGISTRATION_POSE_SCHEMA = "uav.channelized-editor/registration-pose/v1"


def overlap_must_be_disjoint(left_link_id: str | None, right_link_id: str | None) -> bool:
    """Parallel lanes on one Link must not overlap; crossing Links may conflict geometrically."""
    return not left_link_id or not right_link_id or left_link_id == right_link_id


def _normalized_pose(value: dict[str, Any]) -> dict[str, Any]:
    if value.get("schema_version") != REGISTRATION_POSE_SCHEMA:
        raise ValueError(f"registration_pose.schema_version must be {REGISTRATION_POSE_SCHEMA}")
    if value.get("fixed_surface") != "source_image":
        raise ValueError("registration_pose.fixed_surface must be source_image")
    center = value.get("center_px")
    translation = value.get("translation_px")
    if not isinstance(center, list) or len(center) != 2:
        raise ValueError("registration_pose.center_px must contain two numbers")
    if not isinstance(translation, list) or len(translation) != 2:
        raise ValueError("registration_pose.translation_px must contain two numbers")
    scale = float(value.get("uniform_scale", 1.0))
    if not math.isfinite(scale) or not 0.1 <= scale <= 10.0:
        raise ValueError("registration_pose.uniform_scale must be between 0.1 and 10")
    return {
        "center_px": [float(center[0]), float(center[1])],
        "translation_px": [float(translation[0]), float(translation[1])],
        "rotation_deg": float(value.get("rotation_deg", 0.0)),
        "uniform_scale": scale,
    }


def registration_transform(pose_value: dict[str, Any]) -> np.ndarray:
    pose = _normalized_pose(pose_value)
    center_x, center_y = pose["center_px"]
    offset_x, offset_y = pose["translation_px"]
    angle = math.radians(pose["rotation_deg"])
    cosine = math.cos(angle) * pose["uniform_scale"]
    sine = math.sin(angle) * pose["uniform_scale"]
    to_origin = np.asarray([[1.0, 0.0, -center_x], [0.0, 1.0, -center_y], [0.0, 0.0, 1.0]])
    rotate_scale = np.asarray([[cosine, -sine, 0.0], [sine, cosine, 0.0], [0.0, 0.0, 1.0]])
    translate_back = np.asarray([[1.0, 0.0, center_x + offset_x], [0.0, 1.0, center_y + offset_y], [0.0, 0.0, 1.0]])
    return translate_back @ rotate_scale @ to_origin


def compose_registration_homography(
    base_pixel_to_enu: list[list[float]], pose: dict[str, Any]
) -> list[list[float]]:
    base = np.asarray(base_pixel_to_enu, dtype=float)
    if base.shape != (3, 3) or not np.isfinite(base).all():
        raise ValueError("base homography must be a finite 3x3 matrix")
    composed = base @ np.linalg.inv(registration_transform(pose))
    return composed.tolist()


def transform_pixel(point: list[float], pose: dict[str, Any]) -> list[float]:
    projected = registration_transform(pose) @ np.asarray([float(point[0]), float(point[1]), 1.0])
    if abs(projected[2]) < 1e-12:
        raise ValueError("pixel projects to infinity")
    return [float(projected[0] / projected[2]), float(projected[1] / projected[2])]


def homographies_match(
    left: list[list[float]], right: list[list[float]], *, absolute_tolerance: float = 1e-7
) -> bool:
    left_matrix = np.asarray(left, dtype=float)
    right_matrix = np.asarray(right, dtype=float)
    if left_matrix.shape != (3, 3) or right_matrix.shape != (3, 3):
        return False
    if not np.isfinite(left_matrix).all() or not np.isfinite(right_matrix).all():
        return False
    if abs(left_matrix[2, 2]) < 1e-12 or abs(right_matrix[2, 2]) < 1e-12:
        return False
    return bool(np.allclose(
        left_matrix / left_matrix[2, 2],
        right_matrix / right_matrix[2, 2],
        rtol=0.0,
        atol=absolute_tolerance,
    ))


def resolve_registration_homography(
    base_pixel_to_enu: list[list[float]],
    client_pixel_to_enu: list[list[float]],
    pose: dict[str, Any] | None,
) -> list[list[float]]:
    """Return the server-owned matrix, preserving the legacy matrix-only contract."""
    if not pose:
        matrix = np.asarray(client_pixel_to_enu, dtype=float)
        if matrix.shape != (3, 3) or not np.isfinite(matrix).all():
            raise ValueError("homography_pixel_to_enu must be a finite 3x3 matrix")
        return matrix.tolist()
    expected = compose_registration_homography(base_pixel_to_enu, pose)
    if not homographies_match(expected, client_pixel_to_enu):
        raise ValueError("homography_pixel_to_enu does not match registration_pose")
    return expected
