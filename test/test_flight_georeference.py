import numpy as np
import pytest

from elements.FrameElement import FrameElement
from nodes.FlightGeoReferenceNode import FlightGeoReferenceNode
from nodes.PostTrackingWorldProjectionNode import PostTrackingWorldProjectionNode
from utils_local.coordinates import enu_to_gcj02


ANCHOR = (117.0, 36.0)


def _frame(timestamp: float, drone_east_m: float, *, runtime_map: bool = True):
    lon, lat = enu_to_gcj02(drone_east_m, 0.0, ANCHOR)
    frame = FrameElement(
        "video.mp4", np.zeros((100, 100, 3), dtype=np.uint8), timestamp, timestamp, {}
    )
    frame.telemetry = {
        "timestamp": timestamp,
        "position_gcj02": {"longitude": lon, "latitude": lat},
        "coordinate_system": "GCJ02",
        "altitude_agl": 100.0,
        "gimbal_pitch": -90.0,
        "gimbal_roll": 0.0,
        "gimbal_yaw": 0.0,
        "zoom_factor": 1.0,
    }
    frame.homography_matrix = np.eye(3)
    frame.drone_displacement_m = np.array([drone_east_m, 0.0])
    frame.calibration_mode = "runtime_map" if runtime_map else "telemetry"
    frame.map_version_id = "CMV-1" if runtime_map else None
    frame.runtime_map_bundle = {"map_version_id": "CMV-1"} if runtime_map else None
    frame.anchor_gcj02 = ANCHOR
    frame.detected_xyxy = []
    return frame


def test_geo_reference_does_not_replace_image_motion_with_pose_warp():
    node = FlightGeoReferenceNode({
        "tracking_profile": "hover_only_legacy",
        "geo_reference": {"require_visual_validation": False},
    })
    first = _frame(0.0, 0.0)
    first.telemetry["horizontal_speed"] = 2.0
    first.visual_motion_quality = {"status": "bootstrap", "feature_count": 0}
    node.process(first)

    visual_warp = np.array(
        [[1.0, 0.0, 4.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    )
    current_frame = _frame(1.0, 10.0)
    current_frame.camera_motion_warp = visual_warp.copy()
    current_frame.visual_motion_quality = {
        "status": "verified",
        "feature_count": 50,
        "inlier_ratio": 0.9,
        "reprojection_p95_px": 0.5,
    }
    current = node.process(current_frame)
    previous_point = np.array([20.0, 30.0, 1.0])
    projected = current.pose_motion_warp @ previous_point
    projected = projected[:2] / projected[2]

    assert np.allclose(projected, [10.0, 30.0], atol=0.01)
    np.testing.assert_allclose(current.camera_motion_warp, visual_warp)
    assert current.flight_phase == "cruise_nadir"
    assert current.formal_analytics_eligible is True


def test_geo_reference_consumes_precomputed_image_motion_quality():
    node = FlightGeoReferenceNode({
        "tracking_profile": "hover_only_legacy",
        "geo_reference": {"require_visual_validation": True},
    })
    first = _frame(0.0, 0.0)
    first.telemetry["horizontal_speed"] = 2.0
    first.visual_motion_quality = {"status": "bootstrap", "feature_count": 0}
    node.process(first)

    second = _frame(0.1, 0.0)
    second.telemetry["horizontal_speed"] = 2.0
    second.camera_motion_warp = np.eye(3)
    second.visual_motion_quality = {
        "status": "verified",
        "feature_count": 80,
        "inlier_ratio": 0.95,
        "reprojection_p95_px": 0.4,
        "source": "background_lk_ransac",
    }

    result = node.process(second)

    assert result.geo_reference_quality["visual_warp"]["status"] == "verified"
    assert result.formal_analytics_eligible is True


def test_pose_visual_discontinuity_blocks_world_and_tcc_for_current_frame():
    node = FlightGeoReferenceNode({
        "tracking_profile": "hover_cruise_v1",
        "geo_reference": {
            "require_visual_validation": True,
            "max_pose_visual_residual_p95_px": 0.5,
        },
    })
    first = _frame(0.0, 0.0)
    first.telemetry["horizontal_speed"] = 2.0
    first.visual_motion_quality = {"status": "bootstrap", "feature_count": 0}
    node.process(first)

    current = _frame(0.1, 1.0)
    current.telemetry["horizontal_speed"] = 2.0
    current.camera_motion_warp = np.eye(3)
    current.visual_motion_quality = {
        "status": "verified",
        "feature_count": 80,
        "inlier_ratio": 0.95,
        "reprojection_p95_px": 0.4,
    }

    result = node.process(current)

    assert result.geo_reference_quality["visual_warp"]["status"] == "degraded"
    assert "pose_visual_residual_exceeded" in result.geo_reference_quality["geo_reasons"]
    assert result.geo_analytics_eligible is False
    assert result.tcc_analytics_eligible is False


def test_telemetry_projection_without_road_enables_geo_but_not_road_analytics():
    node = FlightGeoReferenceNode({
        "tracking_profile": "hover_only_legacy",
        "geo_reference": {"require_visual_validation": False},
    })

    frame = _frame(0.0, 0.0, runtime_map=False)
    frame.telemetry["horizontal_speed"] = 2.0
    result = node.process(frame)

    assert result.pixel_to_world_enu is not None
    assert result.geo_analytics_eligible is True
    assert result.road_analytics_eligible is False
    assert result.tcc_analytics_eligible is True
    assert result.formal_analytics_eligible is False
    assert result.geo_reference_quality["status"] == "degraded"
    assert "lane_verified_map_required" in result.geo_reference_quality["reasons"]


def test_detector_diagnostics_do_not_override_matrix_and_telemetry_capability():
    node = FlightGeoReferenceNode({
        "tracking_profile": "hover_only_legacy",
        "geo_reference": {"require_visual_validation": False},
    })
    frame = _frame(0.0, 0.0)
    frame.telemetry["horizontal_speed"] = 2.0
    frame.detected_xyxy = [[10.0, 10.0, 20.0, 20.0]]
    frame.detection_diagnostics = {
        "raw_detection_count": 2,
        "valid_detection_count": 1,
        "invalid_geometry_count": 1,
        "invalid_geometry_reasons": {"non_positive_extent": 1},
    }

    result = node.process(frame)

    assert result.detected_xyxy == [[10.0, 10.0, 20.0, 20.0]]
    assert result.geo_analytics_eligible is True
    assert result.tcc_analytics_eligible is True
    assert result.formal_analytics_eligible is True
    assert result.geo_reference_quality["detection_geometry"]["invalid_geometry_count"] == 1


def test_hover_cruise_uses_current_frame_matrix_without_source_registration():
    frame = _frame(0.0, 0.0)
    frame.telemetry["horizontal_speed"] = 2.0
    node = FlightGeoReferenceNode({
        "tracking_profile": "hover_cruise_v1",
        "geo_reference": {"require_visual_validation": False},
    })

    result = node.process(frame)

    assert result.formal_analytics_eligible is True
    assert result.geo_reference_quality["current_frame_matrix"]["status"] == "verified"
    assert result.pixel_to_world_enu is not None


def test_invalid_current_frame_matrix_blocks_world_and_tcc_with_reason():
    frame = _frame(0.0, 0.0)
    frame.telemetry["horizontal_speed"] = 2.0
    frame.homography_matrix = None
    node = FlightGeoReferenceNode({
        "tracking_profile": "hover_cruise_v1",
        "geo_reference": {"require_visual_validation": False},
    })

    result = node.process(frame)

    assert result.tcc_analytics_eligible is False
    assert result.formal_analytics_eligible is False
    assert result.geo_reference_quality["current_frame_matrix"] == {
        "status": "unavailable"
    }
    assert "current_frame_matrix_invalid" in result.geo_reference_quality["geo_reasons"]


@pytest.mark.parametrize(
    ("telemetry_mutation", "expected_reason"),
    [
        (None, "telemetry_unavailable"),
        ({"altitude_agl": 10.0}, "agl_out_of_range"),
        ({"gimbal_pitch": -60.0}, "gimbal_pitch_out_of_range"),
    ],
)
def test_invalid_current_telemetry_keeps_pixel_track_but_emits_no_world_fact(
    telemetry_mutation,
    expected_reason,
):
    frame = _frame(0.0, 0.0, runtime_map=False)
    if telemetry_mutation is None:
        frame.telemetry = None
    else:
        frame.telemetry.update(telemetry_mutation)
    frame.trajectory_output_eligible = True
    frame.id_list = [7]
    frame.association_trajectories = [
        {
            "association_id": 7,
            "track_id": 7,
            "trajectory_px": [[30.0, 40.0]],
            "trajectory_timestamps_sec": [0.0],
            "trajectory_frame_nums": [0],
        }
    ]
    frame.tracking_diagnostics = {"association_state_ids": [7]}

    referenced = FlightGeoReferenceNode(
        {"geo_reference": {"require_visual_validation": False}}
    ).process(frame)
    projected = PostTrackingWorldProjectionNode(
        {"tracking_node": {"candidate_trajectory_tail_points": 30}}
    ).process(referenced)

    assert projected.trajectory_output_eligible is True
    assert projected.geo_analytics_eligible is False
    assert projected.road_analytics_eligible is False
    assert projected.tcc_analytics_eligible is False
    assert expected_reason in projected.geo_reference_quality["geo_reasons"]
    assert projected.association_trajectories[0]["trajectory_enu_m"] == [None]
