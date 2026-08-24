import json

import numpy as np

from elements.FrameElement import FrameElement
from nodes.HomographyCalibrationNode import HomographyCalibrationNode
from nodes.MotionCompensationNode import MotionCompensationNode
from utils_local.coordinates import enu_to_gcj02


ANCHOR = [117.0, 36.0]
INTRINSICS = {
    "focal_length_mm": 4.5,
    "sensor_width_mm": 6.4,
    "sensor_height_mm": 3.6,
}


def _bundle() -> dict:
    return {
        "map_status": "lane_verified",
        "coordinate_system": "GCJ02",
        "map_version_id": "CMV-opaque",
        "anchor_gcj02": ANCHOR,
        # Deliberately wrong legacy matrices: neither may affect world projection.
        "visual_registrations": [
            {
                "source_profile_id": "SRC-A",
                "homography_pixel_to_enu": [[1, 0, 999], [0, 1, 999], [0, 0, 1]],
            }
        ],
        "lanes": [],
    }


def _frame(east_m: float = 10.0, north_m: float = 5.0) -> FrameElement:
    lon, lat = enu_to_gcj02(east_m, north_m, ANCHOR)
    frame = FrameElement(
        "video.mp4", np.zeros((40, 40, 3), dtype=np.uint8), 0.0, 0, {}
    )
    frame.telemetry = {
        "position_gcj02": {"longitude": lon, "latitude": lat},
        "coordinate_system": "GCJ02",
        "altitude_agl": 100.0,
        "gimbal_pitch": -90.0,
        "gimbal_roll": 0.0,
        "gimbal_yaw": 0.0,
        "horizontal_speed": 2.0,
        "zoom_factor": 1.0,
    }
    return frame


def _calibrate_and_compensate(frame: FrameElement):
    calibrated = HomographyCalibrationNode(
        {"calibration": {"mode": "auto", "camera_intrinsics": INTRINSICS}}
    ).process(frame)
    return MotionCompensationNode(
        {"motion_compensation": {"anchor_gcj02": ANCHOR}}
    ).process(calibrated)


def test_runtime_map_does_not_replace_video_srt_world_matrix(monkeypatch):
    monkeypatch.setenv("RUNTIME_MAP_BUNDLE_JSON", json.dumps(_bundle()))

    result = _calibrate_and_compensate(_frame())

    assert result.calibration_mode == "telemetry"
    assert result.map_version_id == "CMV-opaque"
    assert result.runtime_map_bundle["map_version_id"] == "CMV-opaque"
    assert not hasattr(result, "runtime_visual_registration") or result.runtime_visual_registration is None
    assert not np.allclose(result.homography_matrix, np.eye(3))
    assert np.allclose(result.drone_displacement_m, [10.0, 5.0], atol=0.01)


def test_world_matrix_is_identical_with_or_without_road_map(monkeypatch):
    monkeypatch.delenv("RUNTIME_MAP_BUNDLE_JSON", raising=False)
    without_map = _calibrate_and_compensate(_frame())

    monkeypatch.setenv("RUNTIME_MAP_BUNDLE_JSON", json.dumps(_bundle()))
    with_map = _calibrate_and_compensate(_frame())

    np.testing.assert_allclose(
        with_map.homography_matrix, without_map.homography_matrix, atol=1e-12
    )
    np.testing.assert_allclose(
        with_map.drone_displacement_m, without_map.drone_displacement_m, atol=1e-6
    )


def test_missing_strict_agl_fails_closed_without_crashing_calibration(monkeypatch):
    monkeypatch.delenv("RUNTIME_MAP_BUNDLE_JSON", raising=False)
    frame = _frame()
    frame.telemetry["altitude_agl"] = None

    result = HomographyCalibrationNode(
        {"calibration": {"mode": "auto", "camera_intrinsics": INTRINSICS}}
    ).process(frame)

    assert result.homography_matrix is None
    assert result.calibration_mode is None
