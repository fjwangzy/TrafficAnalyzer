import numpy as np

from elements.FrameElement import FrameElement
from nodes.GroundTrajectoryTrackerNode import GroundTrajectoryTrackerNode
from nodes.PostTrackingWorldProjectionNode import PostTrackingWorldProjectionNode
from nodes.TrackerInfoUpdateNode import TrackerInfoUpdateNode
from utils_local.homography import undistort_points


def _config():
    return {
        "tracking_node": {
            "first_track_thresh": 0.5,
            "second_track_thresh": 0.1,
            "match_thresh": 0.8,
            "track_buffer": 30,
            "max_lost_sec": 2.0,
            "max_frame_gap_sec": 0.5,
            "candidate_trajectory_tail_points": 30,
        }
    }


def _frame(timestamp: float, projection: np.ndarray) -> FrameElement:
    frame = FrameElement(
        source="test",
        frame=np.zeros((80, 120, 3), dtype=np.uint8),
        timestamp=timestamp,
        frame_num=int(timestamp * 10),
        roads_info={},
        detected_conf=[0.9],
        detected_cls=["car"],
        detected_cls_ids=[3],
        detected_xyxy=[[20, 20, 40, 40]],
    )
    frame.camera_motion_warp = np.eye(3)
    frame.pixel_to_map_enu = projection
    frame.geo_reference_quality = {"status": "verified"}
    frame.geo_analytics_eligible = True
    frame.road_analytics_eligible = True
    frame.tcc_analytics_eligible = True
    frame.formal_analytics_eligible = True
    return frame


def test_world_projection_is_a_separate_post_bytetrack_stage():
    tracker = GroundTrajectoryTrackerNode(_config())
    projector = PostTrackingWorldProjectionNode(_config())
    frame = _frame(0.0, np.eye(3))

    associated = tracker.process(frame)

    assert associated.id_list == [1]
    assert associated.association_trajectories[0]["trajectory_px"] == [[30.0, 40.0]]
    assert "trajectory_enu_m" not in associated.association_trajectories[0]
    assert associated.formal_track_id_by_association is None

    enriched = projector.process(associated)

    assert enriched.track_id_by_association == {1: 1}
    assert enriched.formal_track_id_by_association == {1: 1}
    assert enriched.association_trajectories[0]["trajectory_enu_m"] == [[30.0, 40.0]]


def test_world_coordinates_remain_verified_when_only_road_context_is_missing():
    tracker = GroundTrajectoryTrackerNode(_config())
    projector = PostTrackingWorldProjectionNode(_config())
    frame = _frame(0.0, np.eye(3))
    frame.road_analytics_eligible = False
    frame.formal_analytics_eligible = False
    frame.geo_reference_quality = {
        "status": "degraded",
        "geo_status": "verified",
        "road_status": "missing",
        "reasons": ["lane_verified_map_required"],
    }

    result = projector.process(tracker.process(frame))
    trajectory = result.association_trajectories[0]

    assert trajectory["trajectory_enu_m"] == [[30.0, 40.0]]
    assert trajectory["geo_analytics_eligible"] is True
    assert trajectory["road_analytics_eligible"] is False
    assert trajectory["geo_reference_quality"] == "verified"
    assert trajectory["road_match_quality"] == "missing"


def test_completed_world_trajectory_is_not_gated_by_road_matching():
    config = {
        **_config(),
        "general": {"buffer_analytics": 1, "min_time_life_track": 0},
        "trajectory": {"min_track_duration_sec": 0.0},
    }
    tracker = GroundTrajectoryTrackerNode(config)
    projector = PostTrackingWorldProjectionNode(config)
    accumulator = TrackerInfoUpdateNode(config)

    for index in range(5):
        frame = _frame(index * 0.1, np.eye(3))
        frame.road_analytics_eligible = False
        frame.formal_analytics_eligible = False
        frame.anchor_gcj02 = (117.0, 36.0)
        frame.geo_reference_quality = {
            "status": "degraded",
            "geo_status": "verified",
            "road_status": "missing",
            "reasons": ["lane_verified_map_required"],
        }
        accumulator.process(projector.process(tracker.process(frame)))

    termination = projector.flush("natural_eof")
    completed_frame = accumulator.flush(
        timestamp=0.4,
        reason=termination["termination_reason"],
        terminated_track_ids=termination["terminated_track_ids"],
    )
    completed = completed_frame.completed_tracks[0]

    assert completed["geo_analytics_eligible"] is True
    assert completed["road_analytics_eligible"] is False
    assert completed["geo_reference_quality"] == "verified"
    assert completed["road_match_quality"] == "missing"
    assert completed["matched_lane_key"] is None
    assert completed["matched_link_id"] is None
    assert all(point is not None for point in completed["trajectory_enu_m"])
    assert all(point is not None for point in completed["trajectory_gcj02"])
    assert len(completed["trajectory_gcj02"]) == len(completed["trajectory_px"])


def test_h_jitter_changes_world_fact_but_not_preceding_association_id():
    tracker = GroundTrajectoryTrackerNode(_config())
    projector = PostTrackingWorldProjectionNode(_config())

    first = projector.process(tracker.process(_frame(0.0, np.eye(3))))
    jittered_h = np.array(
        [[1.0, 0.0, 6.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    )
    second = projector.process(tracker.process(_frame(0.1, jittered_h)))

    assert first.id_list == second.id_list == [1]
    assert second.association_trajectories[0]["trajectory_enu_m"][-1] == [36.0, 40.0]


def test_short_detection_gap_preserves_aligned_image_and_world_history():
    tracker = GroundTrajectoryTrackerNode(_config())
    projector = PostTrackingWorldProjectionNode(_config())
    projector.process(tracker.process(_frame(0.0, np.eye(3))))

    missing = _frame(0.1, np.eye(3))
    missing.detected_conf = []
    missing.detected_cls = []
    missing.detected_cls_ids = []
    missing.detected_xyxy = []
    projector.process(tracker.process(missing))

    recovered = projector.process(tracker.process(_frame(0.2, np.eye(3))))
    trajectory = recovered.association_trajectories[0]

    assert recovered.id_list == [1]
    assert len(trajectory["trajectory_px"]) == 2
    assert len(trajectory["trajectory_enu_m"]) == 2
    assert len(trajectory["point_quality_lineage"]) == 2


def test_tracker_info_consumes_post_tracking_world_fact_without_reprojection():
    """Downstream accumulation must not turn a later H change into a new fact."""

    config = {
        **_config(),
        "general": {"buffer_analytics": 1, "min_time_life_track": 0},
        "trajectory": {"min_track_duration_sec": 0.0},
    }
    tracker = GroundTrajectoryTrackerNode(config)
    projector = PostTrackingWorldProjectionNode(config)
    accumulator = TrackerInfoUpdateNode(config)

    projected = projector.process(tracker.process(_frame(0.0, np.eye(3))))
    expected_world_fact = projected.association_trajectories[0][
        "trajectory_enu_m"
    ][-1]

    # Simulate an accidental downstream mutation. The already-produced world
    # fact remains authoritative and must be consumed as-is.
    projected.pixel_to_map_enu = np.array(
        [[1.0, 0.0, 100.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    )
    accumulated = accumulator.process(projected)

    formal_track = accumulated.buffer_tracks[1]
    assert formal_track.trajectory_enu_m == [tuple(expected_world_fact)]


def test_post_tracking_projection_owns_ground_point_undistortion():
    tracker = GroundTrajectoryTrackerNode(_config())
    projector = PostTrackingWorldProjectionNode(_config())
    frame = _frame(0.0, np.eye(3))
    frame.camera_intrinsics = {
        "focal_length_mm": 4.5,
        "sensor_width_mm": 6.4,
        "sensor_height_mm": 3.6,
    }
    frame.dist_coeffs = [0.35, 0.05, 0.0, 0.0, 0.0]

    projected = projector.process(tracker.process(frame))

    expected = undistort_points(
        np.asarray([[30.0, 40.0]], dtype=np.float64),
        frame.camera_intrinsics,
        (frame.frame.shape[1], frame.frame.shape[0]),
        frame.dist_coeffs,
    )[0]
    actual = projected.association_trajectories[0]["trajectory_enu_m"][-1]
    np.testing.assert_allclose(actual, expected, atol=0.01)


def test_tracker_info_consumes_projected_gcj02_without_anchor_recalculation():
    config = {
        **_config(),
        "general": {"buffer_analytics": 1, "min_time_life_track": 0},
        "trajectory": {"min_track_duration_sec": 0.0},
    }
    tracker = GroundTrajectoryTrackerNode(config)
    projector = PostTrackingWorldProjectionNode(config)
    accumulator = TrackerInfoUpdateNode(config)
    frame = _frame(0.0, np.eye(3))
    frame.anchor_gcj02 = [121.47, 31.23]

    projected = projector.process(tracker.process(frame))
    expected_gcj02 = projected.association_trajectories[0][
        "trajectory_gcj02"
    ][-1]

    projected.anchor_gcj02 = [120.0, 30.0]
    accumulated = accumulator.process(projected)

    assert accumulated.buffer_tracks[1].trajectory_gcj02 == [
        tuple(expected_gcj02)
    ]


def test_gcj02_history_stays_aligned_when_projection_recovers():
    tracker = GroundTrajectoryTrackerNode(_config())
    projector = PostTrackingWorldProjectionNode(_config())

    degraded = _frame(0.0, np.zeros((3, 3)))
    degraded.formal_analytics_eligible = False
    degraded.geo_analytics_eligible = False
    degraded.road_analytics_eligible = False
    degraded.tcc_analytics_eligible = False
    degraded.geo_reference_quality = {
        "status": "degraded",
        "reasons": ["pixel_to_map_projection_unavailable"],
    }
    degraded.anchor_gcj02 = [121.47, 31.23]
    projector.process(tracker.process(degraded))

    recovered = _frame(0.1, np.eye(3))
    recovered.anchor_gcj02 = [121.47, 31.23]
    trajectory = projector.process(
        tracker.process(recovered)
    ).association_trajectories[0]

    assert trajectory["trajectory_enu_m"][0] is None
    assert trajectory["trajectory_enu_m"][1] is not None
    assert trajectory["trajectory_gcj02"][0] is None
    assert trajectory["trajectory_gcj02"][1] is not None
    assert len(trajectory["trajectory_gcj02"]) == len(trajectory["trajectory_px"])


def test_map_coverage_uses_the_same_undistorted_ground_point_as_projection():
    tracker = GroundTrajectoryTrackerNode(_config())
    projector = PostTrackingWorldProjectionNode(_config())
    frame = _frame(0.0, np.eye(3))
    frame.camera_intrinsics = {
        "focal_length_mm": 4.5,
        "sensor_width_mm": 6.4,
        "sensor_height_mm": 3.6,
    }
    frame.dist_coeffs = [0.35, 0.05, 0.0, 0.0, 0.0]
    frame.geo_reference_quality = {
        "status": "verified",
        "map_coverage": {
            "status": "verified",
            "geometry_enu_m": {
                "type": "Polygon",
                "coordinates": [[
                    [31.0, 39.0],
                    [32.0, 39.0],
                    [32.0, 41.0],
                    [31.0, 41.0],
                    [31.0, 39.0],
                ]],
            },
        },
    }

    projected = projector.process(tracker.process(frame))

    assert projected.formal_track_ids == [1]
    assert projected.candidate_trajectories == []


def test_post_tracking_world_fact_preserves_precision_for_speed_regression():
    tracker = GroundTrajectoryTrackerNode(_config())
    projector = PostTrackingWorldProjectionNode(_config())
    projection = np.array(
        [[0.10001, 0.0, 0.0002], [0.0, 0.10001, 0.0003], [0.0, 0.0, 1.0]]
    )

    projected = projector.process(tracker.process(_frame(0.0, projection)))

    actual = projected.association_trajectories[0]["trajectory_enu_m"][-1]
    np.testing.assert_allclose(actual, [3.0005, 4.0007], atol=1e-9)
