import math

import numpy as np

from utils_local.homography import compute_homography_from_telemetry


CAMERA_INTRINSICS = {
    "focal_length_mm": 24.0,
    "sensor_width_mm": 17.3,
    "sensor_height_mm": 13.0,
}
IMAGE_SIZE = (3840, 2160)


def _heading_deg(matrix: np.ndarray, start: tuple[float, float], end: tuple[float, float]) -> float:
    def project(point: tuple[float, float]) -> np.ndarray:
        homogeneous = matrix @ np.array([point[0], point[1], 1.0])
        return homogeneous[:2] / homogeneous[2]

    delta = project(end) - project(start)
    return math.degrees(math.atan2(delta[0], delta[1])) % 360.0


def _axis_distance_deg(left: float, right: float) -> float:
    return abs((left - right + 180.0) % 360.0 - 180.0)


def test_near_nadir_roll_keeps_dji_yaw_orientation_continuous():
    """Crossing the roll shortcut threshold must not rotate ENU by another yaw."""
    common = {
        "altitude_agl": 202.5,
        "gimbal_pitch": -90.0,
        "gimbal_yaw": -117.0,
        "zoom_factor": 1.0,
    }
    shortcut = compute_homography_from_telemetry(
        {**common, "gimbal_roll": 0.49}, CAMERA_INTRINSICS, IMAGE_SIZE
    )
    full_pose = compute_homography_from_telemetry(
        {**common, "gimbal_roll": 0.51}, CAMERA_INTRINSICS, IMAGE_SIZE
    )

    center = (IMAGE_SIZE[0] / 2, IMAGE_SIZE[1] / 2)
    image_right = (center[0] + 100, center[1])
    shortcut_heading = _heading_deg(shortcut, center, image_right)
    full_pose_heading = _heading_deg(full_pose, center, image_right)

    assert _axis_distance_deg(shortcut_heading, full_pose_heading) < 2.0
