import json

import numpy as np
import pytest

from elements.FrameElement import FrameElement
from nodes.HomographyCalibrationNode import HomographyCalibrationNode
from nodes.MotionCompensationNode import MotionCompensationNode
from nodes.TrackerInfoUpdateNode import TrackerInfoUpdateNode
from utils_local.coordinates import enu_to_gcj02


def _bundle(*, include_reference: bool = True) -> dict:
    residuals = {
        "registration_gimbal_yaw_deg": 0.0,
    }
    if include_reference:
        residuals["registration_position_gcj02"] = [117.0, 36.0]
    return {
        "map_status": "lane_verified",
        "coordinate_system": "GCJ02",
        "map_version_id": "CMV-opaque",
        "anchor_gcj02": [117.0, 36.0],
        "visual_registrations": [
            {
                "source_profile_id": "SRC-A",
                "status": "verified",
                "homography_pixel_to_enu": [
                    [1.0, 0.0, 100.0],
                    [0.0, 1.0, 100.0],
                    [0.0, 0.0, 1.0],
                ],
                "residuals": residuals,
            },
            {
                "source_profile_id": "SRC-B",
                "status": "verified",
                "homography_pixel_to_enu": [
                    [1.0, 0.0, 0.0],
                    [0.0, 1.0, 0.0],
                    [0.0, 0.0, 1.0],
                ],
                "residuals": residuals,
            },
        ],
    }


def _frame(timestamp: float = 0.0) -> FrameElement:
    frame = FrameElement(
        "video.mp4", np.zeros((40, 40, 3), dtype=np.uint8), timestamp, timestamp, {}
    )
    frame.id_list = [7]
    frame.tracked_xyxy = [[0.0, 0.0, 10.0, 20.0]]
    frame.tracked_cls = ["car"]
    frame.tracked_cls_ids = [2]
    return frame


def test_runtime_map_locks_exact_source_and_registration_relative_motion(monkeypatch):
    bundle = _bundle()
    monkeypatch.setenv("SOURCE_PROFILE_ID", "SRC-B")
    monkeypatch.setenv("RUNTIME_MAP_BUNDLE_JSON", json.dumps(bundle))
    lon, lat = enu_to_gcj02(10.0, 5.0, [117.0, 36.0])
    frame = _frame()
    frame.telemetry = {
        "position_gcj02": {"longitude": lon, "latitude": lat},
        "coordinate_system": "GCJ02",
        "horizontal_speed": 0.0,
        "gimbal_yaw": 0.0,
    }

    calibrated = HomographyCalibrationNode({"calibration": {}}).process(frame)
    result = MotionCompensationNode({}).process(calibrated)

    assert result.calibration_mode == "runtime_map"
    assert result.map_version_id == "CMV-opaque"
    assert result.runtime_visual_registration["source_profile_id"] == "SRC-B"
    assert np.allclose(result.homography_matrix, np.eye(3))
    assert np.allclose(result.drone_displacement_m, [10.0, 5.0], atol=0.01)


def test_runtime_map_requires_motion_reference(monkeypatch):
    monkeypatch.setenv("SOURCE_PROFILE_ID", "SRC-B")
    monkeypatch.setenv("RUNTIME_MAP_BUNDLE_JSON", json.dumps(_bundle(include_reference=False)))
    frame = HomographyCalibrationNode({"calibration": {}}).process(_frame())

    with pytest.raises(ValueError, match="registration_position_gcj02"):
        MotionCompensationNode({}).process(frame)


def test_tracker_accumulates_each_frames_ground_contact_in_map_enu(monkeypatch):
    monkeypatch.setenv("SOURCE_PROFILE_ID", "SRC-B")
    monkeypatch.setenv("RUNTIME_MAP_BUNDLE_JSON", json.dumps(_bundle()))
    calibration = HomographyCalibrationNode({"calibration": {}})
    motion = MotionCompensationNode({})
    tracker = TrackerInfoUpdateNode(
        {
            "general": {"buffer_analytics": 1, "min_time_life_track": 1},
            "trajectory": {"min_track_duration_sec": 0},
        }
    )

    for timestamp, east in ((0.0, 0.0), (1.0, 10.0)):
        lon, lat = enu_to_gcj02(east, 0.0, [117.0, 36.0])
        frame = _frame(timestamp)
        frame.telemetry = {
            "position_gcj02": {"longitude": lon, "latitude": lat},
            "coordinate_system": "GCJ02",
            "horizontal_speed": 0.0,
            "gimbal_yaw": 0.0,
        }
        tracker.process(motion.process(calibration.process(frame)))

    track = tracker.buffer_tracks[7]
    assert track.map_version_id == "CMV-opaque"
    assert np.allclose(track.trajectory_enu_m[0], [5.0, 20.0], atol=0.01)
    assert np.allclose(track.trajectory_enu_m[1], [15.0, 20.0], atol=0.01)
    assert len(track.trajectory_gcj02) == 2
