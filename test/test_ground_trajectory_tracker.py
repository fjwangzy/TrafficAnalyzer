import json

import numpy as np

from byte_tracker.utils.basetrack import BaseTrack
from elements.FrameElement import FrameElement
from nodes.GroundTrajectoryTrackerNode import GroundTrajectoryTrackerNode
from nodes.PostTrackingWorldProjectionNode import PostTrackingWorldProjectionNode
from nodes.TrackerInfoUpdateNode import TrackerInfoUpdateNode


def _config():
    return {
        "general": {"buffer_analytics": 1, "min_time_life_track": 0},
        "trajectory": {"min_track_duration_sec": 0.0},
        "tracking_node": {
            "first_track_thresh": 0.5,
            "second_track_thresh": 0.1,
            "match_thresh": 0.8,
            "track_buffer": 30,
            "max_lost_sec": 2.0,
            "max_frame_gap_sec": 0.5,
        }
    }


class _TrackingPipeline:
    """Test adapter for the two explicit tracking stages used in production."""

    def __init__(self, config):
        self.tracker = GroundTrajectoryTrackerNode(config)
        self.projector = PostTrackingWorldProjectionNode(config)

    def process(self, frame):
        return self.projector.process(self.tracker.process(frame))

    update = process

    def flush(self, reason):
        self.tracker.flush(reason)
        return self.projector.flush(reason)


def _frame(timestamp, bbox, warp=None):
    frame = FrameElement(
        source="test",
        frame=np.zeros((80, 120, 3), dtype=np.uint8),
        timestamp=timestamp,
        frame_num=int(timestamp * 10),
        roads_info={},
        detected_conf=[0.9],
        detected_cls=["car"],
        detected_cls_ids=[3],
        detected_xyxy=[bbox],
    )
    frame.camera_motion_warp = np.eye(3) if warp is None else warp
    frame.geo_reference_quality = {"status": "verified"}
    frame.geo_analytics_eligible = True
    frame.road_analytics_eligible = True
    frame.tcc_analytics_eligible = True
    frame.formal_analytics_eligible = True
    return frame


def _multi_frame(timestamp, boxes, projection):
    frame = FrameElement(
        source="test",
        frame=np.zeros((80, 120, 3), dtype=np.uint8),
        timestamp=timestamp,
        frame_num=int(timestamp * 10),
        roads_info={},
        detected_conf=[0.9] * len(boxes),
        detected_cls=["car"] * len(boxes),
        detected_cls_ids=[3] * len(boxes),
        detected_xyxy=boxes,
    )
    frame.camera_motion_warp = np.eye(3)
    frame.pixel_to_world_enu = projection
    frame.geo_reference_quality = {"status": "verified"}
    frame.geo_analytics_eligible = True
    frame.road_analytics_eligible = True
    frame.tcc_analytics_eligible = True
    frame.formal_analytics_eligible = True
    return frame


def test_tracked_class_name_survives_current_frame_class_switch_pending():
    tracker = GroundTrajectoryTrackerNode(_config())
    first = _frame(0.0, [20, 20, 40, 40])
    first.detected_cls = ["tricycle"]
    first.detected_cls_ids = [6]
    tracker.process(first)

    second = _frame(0.1, [20, 20, 40, 40])
    second.detected_cls = ["car"]
    second.detected_cls_ids = [3]
    result = tracker.process(second)

    assert result.tracked_cls_ids == [6]
    assert result.tracked_cls == ["tricycle"]


def test_image_association_is_invariant_to_world_projection_jitter():
    """Changing only H must not change image identities or matched boxes."""

    stable_projection = np.array(
        [[0.1, 0.0, 0.0], [0.0, 0.1, 0.0], [0.0, 0.0, 1.0]]
    )
    jittered_projection = np.array(
        [[0.1, 0.0, 6.0], [0.0, 0.1, 0.0], [0.0, 0.0, 1.0]]
    )

    def run(second_projection):
        tracker = _TrackingPipeline(_config())
        tracker.process(
            _multi_frame(
                0.0,
                [[20, 0, 30, 20], [35, 0, 45, 20]],
                stable_projection,
            )
        )
        result = tracker.process(
            _multi_frame(
                0.1,
                [[15, 0, 25, 20], [30, 0, 40, 20]],
                second_projection,
            )
        )
        return result

    stable = run(stable_projection)
    jittered = run(jittered_projection)
    stable_assignments = sorted(
        (int(track_id), tuple(box))
        for track_id, box in zip(stable.id_list, stable.tracked_xyxy)
    )
    jittered_assignments = sorted(
        (int(track_id), tuple(box))
        for track_id, box in zip(jittered.id_list, jittered.tracked_xyxy)
    )

    assert jittered_assignments == stable_assignments
    # World facts are intentionally still frame-specific and therefore differ;
    # the important invariant is that this post-ID error cannot change identity.
    assert (
        jittered.association_trajectories[0]["trajectory_enu_m"][-1]
        != stable.association_trajectories[0]["trajectory_enu_m"][-1]
    )


def test_camera_motion_warp_keeps_id_when_raw_boxes_do_not_overlap():
    BaseTrack._count = 0
    node = _TrackingPipeline(_config())

    first = node.process(_frame(0.0, [20, 20, 40, 40]))
    warp = np.array([[1.0, 0.0, -20.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
    second = node.process(_frame(0.1, [0, 20, 20, 40], warp=warp))

    assert first.id_list == [1]
    assert second.id_list == [1]
    assert second.tracking_diagnostics["camera_motion_compensated"] is True
    assert second.tracking_diagnostics["tracking_method"] == "motion_compensated_image_v2"


def test_small_stride_motion_reports_mahalanobis_shadow_without_splitting_id():
    BaseTrack._count = 0
    node = GroundTrajectoryTrackerNode(_config())

    first = node.process(_frame(0.0, [20, 20, 30, 30]))
    moved = node.process(_frame(1 / 6, [24, 20, 34, 30]))

    assert first.id_list == [1]
    assert moved.id_list == [1]
    gate = moved.tracking_diagnostics["mahalanobis_gate"]
    assert gate["mahalanobis_gate_mode"] == "shadow"
    assert gate["eligible_pair_count"] == 1
    assert gate["would_reject_eligible_pair_count"] == 1
    assert gate["would_strand_track_count"] == 1


def test_adaptive_imgsz_switch_and_short_detection_gap_keep_same_image_id():
    """Source-plane boxes make adaptive inference size invisible to association."""
    BaseTrack._count = 0
    node = _TrackingPipeline(_config())

    first = _frame(0.0, [20, 20, 40, 40])
    first.inference_context = {"effective_imgsz": 640}
    first = node.process(first)

    switched = _frame(0.1, [21, 20, 41, 40])
    switched.inference_context = {"effective_imgsz": 960}
    switched = node.process(switched)

    missing = _multi_frame(0.2, [], np.eye(3))
    missing.inference_context = {"effective_imgsz": 1280}
    missing = node.process(missing)

    recovered = _frame(0.3, [22, 20, 42, 40])
    recovered.inference_context = {"effective_imgsz": 1280}
    recovered = node.process(recovered)

    assert first.id_list == [1]
    assert switched.id_list == [1]
    assert missing.id_list == []
    assert missing.tracking_diagnostics["terminated_track_ids"] == []
    assert recovered.id_list == [1]
    assert recovered.tracking_diagnostics["terminated_track_ids"] == []


def test_no_road_or_geo_still_emits_one_aligned_pixel_trajectory_at_eof():
    BaseTrack._count = 0
    tracker = _TrackingPipeline(_config())
    accumulator = TrackerInfoUpdateNode(_config())

    for index in range(5):
        frame = _frame(index * 0.1, [20 + index, 20, 40 + index, 40])
        frame.formal_analytics_eligible = False
        frame.geo_analytics_eligible = False
        frame.road_analytics_eligible = False
        frame.tcc_analytics_eligible = False
        frame.geo_reference_quality = {
            "status": "degraded",
            "reasons": ["lane_verified_map_required", "pixel_to_map_projection_unavailable"],
        }
        accumulated = accumulator.process(tracker.process(frame))

    assert list(accumulated.buffer_tracks) == [1]
    assert accumulated.trajectory_output_eligible is True
    assert accumulated.geo_analytics_eligible is False
    assert accumulated.road_analytics_eligible is False

    termination = tracker.flush("natural_eof")
    completed_frame = accumulator.flush(
        timestamp=0.4,
        reason=termination["termination_reason"],
        terminated_track_ids=termination["terminated_track_ids"],
    )

    assert completed_frame is not None
    assert len(completed_frame.completed_tracks) == 1
    completed = completed_frame.completed_tracks[0]
    assert completed["track_id"] == 1
    assert completed["association_id"] == 1
    assert completed["trajectory_output_eligible"] is True
    assert completed["geo_analytics_eligible"] is False
    assert completed["road_analytics_eligible"] is False
    assert completed["road_context_status"] == "missing"
    assert completed["quality_status"] == "degraded"
    assert completed["formal_analytics_eligible"] is False
    assert completed["trajectory_enu_m"] == [None] * 5
    assert completed["trajectory_gcj02"] == [None] * 5
    assert len(completed["trajectory_px"]) == 5
    assert len(completed["trajectory_timestamps_sec"]) == 5
    assert len(completed["trajectory_frame_nums"]) == 5


def test_source_time_gap_ends_association_instead_of_forcing_same_id():
    BaseTrack._count = 0
    node = _TrackingPipeline(_config())

    first = node.process(_frame(0.0, [20, 20, 40, 40]))
    second = node.process(_frame(0.7, [20, 20, 40, 40]))

    assert first.id_list == [1]
    assert second.id_list == [2]
    assert second.tracking_diagnostics["termination_reason"] == "source_time_gap"
    assert second.tracking_diagnostics["terminated_track_ids"] == [1]


def test_source_time_reversal_ends_association_instead_of_forcing_same_id():
    node = _TrackingPipeline(_config())
    first = node.process(_frame(1.0, [20, 20, 40, 40]))

    second = node.process(_frame(0.9, [20, 20, 40, 40]))

    assert first.id_list == [1]
    assert second.id_list == [2]
    assert second.tracking_diagnostics["termination_reason"] == "source_time_reversal"
    assert second.tracking_diagnostics["terminated_track_ids"] == [1]


def test_geo_reference_quality_break_keeps_same_output_track_in_business_buffer():
    BaseTrack._count = 0
    tracker = _TrackingPipeline(_config())
    accumulator = TrackerInfoUpdateNode(_config())

    formal = _frame(0.0, [20, 20, 40, 40])
    formal.homography_matrix = np.eye(3)
    formal.pixel_to_world_enu = np.eye(3)
    formal.drone_displacement_m = np.zeros(2)
    formal = tracker.process(formal)
    accumulated = accumulator.process(formal)
    assert list(accumulated.buffer_tracks) == [1]

    degraded = _frame(0.1, [20, 20, 40, 40])
    degraded.formal_analytics_eligible = False
    degraded.geo_analytics_eligible = False
    degraded.road_analytics_eligible = False
    degraded.tcc_analytics_eligible = False
    degraded.flight_phase = "unsupported_pose"
    degraded.geo_reference_quality = {"status": "degraded"}
    degraded.homography_matrix = np.eye(3)
    degraded.pixel_to_world_enu = np.eye(3)
    degraded.drone_displacement_m = np.zeros(2)
    degraded = tracker.process(degraded)
    accumulated = accumulator.process(degraded)

    assert degraded.id_list == [1]  # image association remains renderable/continuous
    assert degraded.association_id_list == [1]
    assert degraded.track_id_by_association == {1: 1}
    assert degraded.tracking_diagnostics["terminated_track_ids"] == []
    assert list(accumulated.buffer_tracks) == [1]
    assert len(accumulated.buffer_tracks[1].trajectory_points) == 2
    assert accumulated.buffer_tracks[1].trajectory_enu_m == [(30.0, 40.0), None]


def test_active_tail_keeps_image_history_across_geo_quality_break():
    tracker = _TrackingPipeline(_config())
    formal = _frame(0.0, [20, 20, 40, 40])
    formal.pixel_to_world_enu = np.eye(3)
    tracker.process(formal)

    degraded = _frame(0.1, [21, 20, 41, 40])
    degraded.formal_analytics_eligible = False
    degraded.geo_analytics_eligible = False
    degraded.road_analytics_eligible = False
    degraded.tcc_analytics_eligible = False
    degraded.geo_reference_quality = {
        "status": "degraded",
        "reasons": ["visual_warp_not_verified"],
    }
    degraded.pixel_to_world_enu = np.eye(3)

    result = tracker.process(degraded)

    assert result.id_list == [1]
    trajectory = result.association_trajectories[0]["trajectory_px"]
    assert result.candidate_trajectories == []
    assert len(trajectory) == 2
    np.testing.assert_allclose(trajectory[0], [30.0, 40.0])
    np.testing.assert_allclose(trajectory[1], [30.87, 40.0], atol=0.02)


def test_active_display_trace_uses_box_center_while_business_geometry_uses_ground_contact():
    BaseTrack._count = 0
    tracker = _TrackingPipeline(_config())
    frame = _frame(0.0, [20, 10, 40, 50])
    frame.formal_analytics_eligible = False
    frame.geo_analytics_eligible = False
    frame.road_analytics_eligible = False
    frame.tcc_analytics_eligible = False
    frame.geo_reference_quality = {"status": "degraded"}

    result = tracker.process(frame)

    trajectory = result.association_trajectories[0]
    assert trajectory["trajectory_px"] == [[30.0, 50.0]]
    assert trajectory["trajectory_display_px"] == [[30.0, 30.0]]


def test_target_outside_map_coverage_still_enters_output_buffer_without_road_match():
    BaseTrack._count = 0
    tracker = _TrackingPipeline(_config())
    accumulator = TrackerInfoUpdateNode(_config())
    frame = _frame(0.0, [20, 20, 40, 40])
    frame.pixel_to_world_enu = np.eye(3)
    frame.homography_matrix = np.eye(3)
    frame.drone_displacement_m = np.zeros(2)
    frame.road_analytics_eligible = False
    frame.formal_analytics_eligible = False
    frame.geo_reference_quality = {
        "status": "verified",
        "geo_status": "verified",
        "road_reasons": ["lane_verified_map_required"],
        # Historical map coverage metadata must not gate image/world tracks.
        "map_coverage": {
            "status": "verified",
            "geometry_enu_m": {
                "type": "Polygon",
                "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
            },
        },
    }

    frame = tracker.process(frame)
    frame = accumulator.process(frame)

    assert frame.id_list == [1]
    assert frame.formal_track_ids == []
    assert list(frame.buffer_tracks) == [1]
    assert len(frame.candidate_trajectories) == 1
    assert frame.candidate_trajectories[0]["trajectory_output_eligible"] is False
    trajectory = frame.association_trajectories[0]
    assert trajectory["track_id"] == 1
    assert trajectory["trajectory_output_eligible"] is True
    assert trajectory["geo_analytics_eligible"] is True
    assert trajectory["road_analytics_eligible"] is False
    assert trajectory["tcc_analytics_eligible"] is True
    assert trajectory["quality_reasons"] == ["lane_verified_map_required"]


def test_degraded_active_history_is_bounded_and_never_marked_road_eligible():
    BaseTrack._count = 0
    tracker = _TrackingPipeline(_config())
    frames = []
    for index in range(35):
        frame = _frame(index * 0.1, [20 + index, 20, 40 + index, 40])
        frame.formal_analytics_eligible = False
        frame.geo_analytics_eligible = False
        frame.road_analytics_eligible = False
        frame.tcc_analytics_eligible = False
        frame.flight_phase = "unsupported_pose"
        frame.geo_reference_quality = {
            "status": "degraded",
            "reasons": ["flight_pose_not_eligible"],
        }
        frame.pixel_to_world_enu = np.eye(3)
        frames.append(tracker.process(frame))

    trajectory = frames[-1].association_trajectories[0]
    assert trajectory["track_id"] == 1
    assert trajectory["tracking_quality"] == "verified"
    assert trajectory["quality_reasons"] == ["flight_pose_not_eligible"]
    assert len(trajectory["trajectory_px"]) == 30
    assert len(trajectory["trajectory_display_px"]) == 30
    assert len(trajectory["trajectory_enu_m"]) == 30
    assert frames[-1].formal_track_ids == []


def test_degraded_active_display_history_warps_old_points_into_current_frame():
    BaseTrack._count = 0
    tracker = _TrackingPipeline(_config())

    first = _frame(0.0, [20, 20, 40, 40])
    first.formal_analytics_eligible = False
    first.geo_analytics_eligible = False
    first.road_analytics_eligible = False
    first.tcc_analytics_eligible = False
    first.geo_reference_quality = {"status": "degraded"}
    tracker.process(first)

    warp = np.array([
        [1.0, 0.0, -20.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
    ])
    second = _frame(0.1, [5, 20, 25, 40], warp=warp)
    second.formal_analytics_eligible = False
    second.geo_analytics_eligible = False
    second.road_analytics_eligible = False
    second.tcc_analytics_eligible = False
    second.geo_reference_quality = {"status": "degraded"}

    result = tracker.process(second)

    trajectory = result.association_trajectories[0]
    assert np.allclose(trajectory["trajectory_px"][0], [30.0, 40.0])
    assert np.allclose(
        trajectory["trajectory_display_px"],
        [[10.0, 30.0], [trajectory["trajectory_px"][1][0], 30.0]],
    )


def test_degraded_active_keeps_source_pixels_without_world_projection():
    BaseTrack._count = 0
    tracker = _TrackingPipeline(_config())

    first = _frame(0.0, [20, 20, 40, 40])
    first.formal_analytics_eligible = False
    first.geo_analytics_eligible = False
    first.road_analytics_eligible = False
    first.tcc_analytics_eligible = False
    first.geo_reference_quality = {"status": "degraded"}
    first.pixel_to_world_enu = np.eye(3)
    tracker.process(first)

    current_h = np.array([
        [1.0, 0.0, 20.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
    ])
    current_warp = np.linalg.inv(current_h)
    second = _frame(0.1, [0, 20, 20, 40], warp=current_warp)
    second.formal_analytics_eligible = False
    second.geo_analytics_eligible = False
    second.road_analytics_eligible = False
    second.tcc_analytics_eligible = False
    second.geo_reference_quality = {"status": "degraded"}
    second.pixel_to_world_enu = current_h

    trajectory = tracker.process(second).association_trajectories[0]

    assert trajectory["trajectory_px"] == [[30.0, 40.0], [10.0, 40.0]]
    assert trajectory["trajectory_enu_m"] == [None, None]
    assert trajectory["trajectory_display_px"] == [[10.0, 30.0], [10.0, 30.0]]
    assert trajectory["trajectory_timestamps_sec"] == [0.0, 0.1]
    assert trajectory["trajectory_frame_nums"] == [0, 1]
    assert len(trajectory["point_quality_lineage"]) == 2


def test_short_telemetry_gap_keeps_same_output_track_id_through_recovery():
    BaseTrack._count = 0
    tracker = _TrackingPipeline(_config())

    formal = tracker.process(_frame(0.0, [20, 20, 40, 40]))
    missing = _frame(0.1, [20, 20, 40, 40])
    missing.formal_analytics_eligible = False
    missing.geo_analytics_eligible = False
    missing.road_analytics_eligible = False
    missing.tcc_analytics_eligible = False
    missing.flight_phase = "telemetry_unavailable"
    missing.geo_reference_quality = {
        "status": "degraded",
        "reasons": ["telemetry_unavailable"],
    }
    missing = tracker.process(missing)
    recovered = tracker.process(_frame(0.2, [20, 20, 40, 40]))

    assert formal.id_list == [1]
    assert missing.id_list == [1]
    assert missing.formal_track_ids == []
    assert missing.track_id_by_association == {1: 1}
    assert missing.tracking_diagnostics["termination_reason"] is None
    assert recovered.id_list == [1]
    assert recovered.formal_track_ids == [1]
    assert recovered.track_id_by_association == {1: 1}


def test_quality_recovery_keeps_one_output_track_in_same_image_family():
    tracker = _TrackingPipeline(_config())
    accumulator = TrackerInfoUpdateNode(_config())

    first = _frame(0.0, [20, 20, 40, 40])
    first.homography_matrix = np.eye(3)
    first.pixel_to_world_enu = np.eye(3)
    first.drone_displacement_m = np.zeros(2)
    accumulator.process(tracker.process(first))

    degraded = _frame(0.1, [20, 20, 40, 40])
    degraded.formal_analytics_eligible = False
    degraded.geo_analytics_eligible = False
    degraded.road_analytics_eligible = False
    degraded.tcc_analytics_eligible = False
    degraded.flight_phase = "telemetry_unavailable"
    degraded.geo_reference_quality = {
        "status": "degraded",
        "reasons": ["telemetry_unavailable"],
    }
    degraded.homography_matrix = np.eye(3)
    degraded.pixel_to_world_enu = np.eye(3)
    degraded.drone_displacement_m = np.zeros(2)
    accumulator.process(tracker.process(degraded))

    recovered = _frame(0.2, [20, 20, 40, 40])
    recovered.homography_matrix = np.eye(3)
    recovered.pixel_to_world_enu = np.eye(3)
    recovered.drone_displacement_m = np.zeros(2)
    result = accumulator.process(tracker.process(recovered))

    assert result.id_list == [1]
    assert list(result.buffer_tracks) == [1]
    formal_track = result.buffer_tracks[1]
    assert formal_track.association_id == 1
    assert formal_track.track_family_id == "association:1"
    assert formal_track.previous_track_id is None
    assert len(formal_track.trajectory_points) == 3


def test_mature_id_stays_mature_through_geo_and_road_degrade_recovery():
    config = _config()
    config["trajectory"]["min_track_duration_sec"] = 2.0
    tracker = _TrackingPipeline(config)
    accumulator = TrackerInfoUpdateNode(config)

    for index in range(22):
        accumulator.process(
            tracker.process(_frame(index * 0.1, [20, 20, 40, 40]))
        )

    degraded = _frame(2.2, [20, 20, 40, 40])
    degraded.geo_analytics_eligible = False
    degraded.road_analytics_eligible = False
    degraded.tcc_analytics_eligible = False
    degraded.formal_analytics_eligible = False
    degraded.geo_reference_quality = {
        "status": "degraded",
        "reasons": ["telemetry_unavailable", "lane_verified_map_required"],
    }
    degraded = accumulator.process(tracker.process(degraded))
    assert degraded.id_list == [1]
    assert list(degraded.mature_tracks) == [1]
    assert degraded.candidate_trajectories == []
    assert degraded.completed_tracks is None

    recovered = accumulator.process(
        tracker.process(_frame(2.3, [20, 20, 40, 40]))
    )
    assert recovered.id_list == [1]
    assert list(recovered.mature_tracks) == [1]
    assert recovered.candidate_trajectories == []
    assert recovered.completed_tracks is None
    assert (
        recovered.tracking_diagnostics["lifecycle"]
        ["same_id_mature_to_candidate_count"]
        == 0
    )


def test_mature_hover_queue_tracks_do_not_reenter_candidate_state_at_statistics_windows():
    """A statistics window must never restart an active image trajectory."""

    config = _config()
    config["general"] = {
        "buffer_analytics": 0.5,
        "min_time_life_track": 3,
    }
    config["trajectory"]["min_track_duration_sec"] = 2.0
    accumulator = TrackerInfoUpdateNode(config)
    association_ids = [1, 2, 3]
    boxes = [[10, 20, 25, 45], [40, 20, 55, 45], [70, 20, 85, 45]]
    completed_track_ids = []
    candidate_counts_after_maturity = []

    for index in range(701):
        timestamp = round(index * 0.1, 3)
        frame = _multi_frame(timestamp, boxes, np.eye(3))
        frame.id_list = list(association_ids)
        frame.association_id_list = list(association_ids)
        frame.tracked_xyxy = [list(box) for box in boxes]
        frame.tracked_cls = ["car"] * len(boxes)
        frame.tracked_cls_ids = [3] * len(boxes)
        frame.tracked_conf = [0.9] * len(boxes)
        frame.trajectory_output_eligible = True
        frame.trajectory_association_ids = list(association_ids)
        frame.track_id_by_association = {value: value for value in association_ids}
        frame.tracking_diagnostics = {
            "tracking_method": "motion_compensated_image_v2",
            "world_projection_stage": "post_bytetrack",
            "association_state_ids": list(association_ids),
            "terminated_track_ids": [],
            "termination_reason": None,
        }

        result = accumulator.process(frame)
        completed_track_ids.extend(
            track["track_id"] for track in (result.completed_tracks or [])
        )
        if timestamp >= 2.1:
            candidate_counts_after_maturity.append(
                len(result.candidate_trajectories or [])
            )
            assert sorted(result.buffer_tracks) == association_ids
            assert all(
                track.trajectory_output_eligible
                for track in result.buffer_tracks.values()
            )

    assert completed_track_ids == []
    assert candidate_counts_after_maturity
    assert max(candidate_counts_after_maturity) == 0


def test_tracker_info_exposes_active_and_mature_lifecycle_views():
    config = _config()
    config["trajectory"]["min_track_duration_sec"] = 2.0
    accumulator = TrackerInfoUpdateNode(config)

    def process(timestamp):
        frame = _frame(timestamp, [20, 20, 40, 40])
        frame.id_list = [1]
        frame.association_id_list = [1]
        frame.tracked_xyxy = [[20, 20, 40, 40]]
        frame.tracked_cls = ["car"]
        frame.tracked_cls_ids = [3]
        frame.tracked_conf = [0.9]
        frame.trajectory_output_eligible = True
        frame.trajectory_association_ids = [1]
        frame.track_id_by_association = {1: 1}
        frame.tracking_diagnostics = {
            "tracking_method": "motion_compensated_image_v2",
            "world_projection_stage": "post_bytetrack",
            "association_state_ids": [1],
            "terminated_track_ids": [],
            "termination_reason": None,
        }
        return accumulator.process(frame)

    candidate = process(0.0)
    assert list(candidate.active_tracks) == [1]
    assert candidate.mature_tracks == {}
    assert candidate.mature_trajectory_association_ids == []
    assert candidate.tracking_diagnostics["lifecycle"] == {
        "active_track_count": 1,
        "mature_track_count": 0,
        "candidate_track_count": 1,
        "completed_track_count": 0,
        "same_id_mature_to_candidate_count": 0,
        "termination_reason": None,
    }

    process(0.5)
    process(1.0)
    process(1.5)
    mature = process(2.1)
    assert list(mature.active_tracks) == [1]
    assert list(mature.mature_tracks) == [1]
    assert mature.mature_trajectory_association_ids == [1]
    assert mature.tracking_diagnostics["lifecycle"]["mature_track_count"] == 1
    assert mature.tracking_diagnostics["lifecycle"]["candidate_track_count"] == 0


def test_short_detection_gap_preserves_mature_id_until_recovery():
    config = _config()
    config["trajectory"]["min_track_duration_sec"] = 2.0
    tracker = _TrackingPipeline(config)
    accumulator = TrackerInfoUpdateNode(config)

    for index in range(22):
        frame = _frame(index * 0.1, [20, 20, 40, 40])
        mature = accumulator.process(tracker.process(frame))
    assert list(mature.mature_tracks) == [1]

    missing = _multi_frame(2.2, [], np.eye(3))
    missing = accumulator.process(tracker.process(missing))
    assert missing.id_list == []
    assert list(missing.active_tracks) == [1]
    assert list(missing.mature_tracks) == [1]
    assert missing.candidate_trajectories == []
    assert missing.completed_tracks is None

    recovered = accumulator.process(
        tracker.process(_frame(2.3, [20, 20, 40, 40]))
    )
    assert recovered.id_list == [1]
    assert list(recovered.mature_tracks) == [1]
    assert recovered.candidate_trajectories == []
    assert recovered.completed_tracks is None
    assert (
        recovered.tracking_diagnostics["lifecycle"]
        ["same_id_mature_to_candidate_count"]
        == 0
    )


def test_association_lost_beyond_two_seconds_completes_new_path_once():
    config = _config()
    config["trajectory"]["min_track_duration_sec"] = 2.0
    tracker = _TrackingPipeline(config)
    accumulator = TrackerInfoUpdateNode(config)

    for index in range(22):
        accumulator.process(
            tracker.process(_frame(index * 0.1, [20, 20, 40, 40]))
        )

    completion_frames = []
    for timestamp in (2.5, 3.0, 3.5, 4.0, 4.5, 5.0):
        result = accumulator.process(
            tracker.process(_multi_frame(timestamp, [], np.eye(3)))
        )
        if result.completed_tracks:
            completion_frames.append(result)

    assert len(completion_frames) == 1
    completed = completion_frames[0]
    assert [track["track_id"] for track in completed.completed_tracks] == [1]
    assert completed.completed_tracks[0]["termination_reason"] == "association_ended"
    assert completed.tracking_diagnostics["lifecycle"]["completed_track_count"] == 1
    assert (
        completed.tracking_diagnostics["lifecycle"]["termination_reason"]
        == "association_ended"
    )
    assert accumulator.buffer_tracks == {}


def test_source_time_gap_completes_old_mature_id_once_and_starts_candidate():
    config = _config()
    config["trajectory"]["min_track_duration_sec"] = 2.0
    tracker = _TrackingPipeline(config)
    accumulator = TrackerInfoUpdateNode(config)

    for index in range(22):
        accumulator.process(
            tracker.process(_frame(index * 0.1, [20, 20, 40, 40]))
        )

    jumped = accumulator.process(
        tracker.process(_frame(3.0, [20, 20, 40, 40]))
    )
    assert jumped.id_list == [2]
    assert [track["track_id"] for track in jumped.completed_tracks] == [1]
    assert jumped.completed_tracks[0]["termination_reason"] == "source_time_gap"
    assert list(jumped.active_tracks) == [2]
    assert jumped.mature_tracks == {}
    assert [track["track_id"] for track in jumped.candidate_trajectories] == [2]
    assert jumped.tracking_diagnostics["lifecycle"]["completed_track_count"] == 1
    assert jumped.tracking_diagnostics["lifecycle"]["termination_reason"] == "source_time_gap"

    continued = accumulator.process(
        tracker.process(_frame(3.1, [20, 20, 40, 40]))
    )
    assert continued.completed_tracks is None


def test_telemetry_gap_never_resets_image_association_tracker():
    BaseTrack._count = 0
    tracker = _TrackingPipeline(_config())
    tracker.process(_frame(0.0, [20, 20, 40, 40]))

    ids = []
    for timestamp in (0.1, 0.4, 0.61):
        frame = _frame(timestamp, [20, 20, 40, 40])
        frame.formal_analytics_eligible = False
        frame.geo_analytics_eligible = False
        frame.road_analytics_eligible = False
        frame.tcc_analytics_eligible = False
        frame.flight_phase = "telemetry_unavailable"
        frame.geo_reference_quality = {
            "status": "degraded",
            "reasons": ["telemetry_unavailable"],
        }
        result = tracker.process(frame)
        ids.append(result.id_list[0])

    assert ids == [1, 1, 1]
    assert result.formal_track_ids == []
    assert result.track_id_by_association == {1: 1}


def test_offline_shadow_tracker_writes_comparison_without_changing_primary(tmp_path):
    config = _config()
    report = tmp_path / "shadow" / "comparison.jsonl"
    config["tracking_shadow"] = {
        "enabled": True,
        "offline_only": True,
        "report_path": str(report),
    }
    tracker = _TrackingPipeline(config)

    result = tracker.process(_frame(0.0, [20, 20, 40, 40]))

    assert result.id_list == [1]
    comparison = result.tracking_diagnostics["shadow_comparison"]
    assert comparison == {
        "image_v2_track_count": 1,
        "legacy_track_count": 1,
        "matched_by_iou": [{
            "image_v2_track_id": 1,
            "legacy_track_id": 1,
            "iou": 1.0,
        }],
        "unmatched_image_v2": [],
        "unmatched_legacy": [],
    }
    record = json.loads(report.read_text(encoding="utf-8"))
    assert record["schema_version"] == "uav.tracking-shadow/v2"
    assert record["comparison"] == comparison


def test_natural_eof_flushes_remaining_formal_track_with_aligned_points():
    tracker = _TrackingPipeline(_config())
    accumulator = TrackerInfoUpdateNode(_config())
    for index in range(5):
        frame = _frame(index * 0.1, [20 + index, 20, 40 + index, 40])
        frame.homography_matrix = np.eye(3)
        frame.pixel_to_world_enu = np.eye(3)
        frame.drone_displacement_m = np.zeros(2)
        accumulator.process(tracker.update(frame))

    termination = tracker.flush("natural_eof")
    completed_frame = accumulator.flush(
        timestamp=0.4,
        reason=termination["termination_reason"],
        terminated_track_ids=termination["terminated_track_ids"],
    )

    assert termination["terminated_track_ids"] == [1]
    assert accumulator.buffer_tracks == {}
    assert completed_frame is not None
    assert len(completed_frame.completed_tracks) == 1
    completed = completed_frame.completed_tracks[0]
    assert completed["track_id"] == 1
    assert completed["termination_reason"] == "natural_eof"
    assert len(completed["trajectory_px"]) == 5
    assert len(completed["trajectory_enu_m"]) == 5
    assert len(completed["trajectory_timestamps_sec"]) == 5
    assert completed["trajectory_frame_nums"] == [0, 1, 2, 3, 4]
    assert len(completed["point_quality_lineage"]) == 5
    assert completed["trajectory_px"] == completed["ground_contact_points_px"]
    assert completed["trajectory_bbox_center_px"] != completed["trajectory_px"]
    assert (
        accumulator.flush(
            timestamp=0.4,
            reason="natural_eof",
            terminated_track_ids=[1],
        )
        is None
    )


def test_legacy_timeout_reports_reason_and_completes_mature_track_once():
    config = _config()
    config["tracking_profile"] = "hover_only_legacy"
    config["trajectory"]["min_track_duration_sec"] = 2.0
    accumulator = TrackerInfoUpdateNode(config)

    def legacy_frame(timestamp, present):
        frame = FrameElement(
            source="legacy-fixture",
            frame=np.zeros((80, 120, 3), dtype=np.uint8),
            timestamp=timestamp,
            frame_num=round(timestamp * 10),
            roads_info={},
        )
        frame.id_list = [1] if present else []
        frame.tracked_xyxy = [[20, 20, 40, 40]] if present else []
        frame.tracked_cls = ["car"] if present else []
        frame.tracked_cls_ids = [3] if present else []
        frame.tracked_conf = [0.9] if present else []
        return frame

    for timestamp in (0.0, 0.5, 1.0, 1.5, 2.1):
        mature = accumulator.process(legacy_frame(timestamp, True))
    assert list(mature.mature_tracks) == [1]

    completed = None
    for timestamp in (2.5, 3.0, 3.5, 4.0, 4.5):
        result = accumulator.process(legacy_frame(timestamp, False))
        if result.completed_tracks:
            completed = result

    assert completed is not None
    assert [track["track_id"] for track in completed.completed_tracks] == [1]
    assert completed.completed_tracks[0]["termination_reason"] == "association_timeout"
    assert (
        completed.tracking_diagnostics["lifecycle"]["termination_reason"]
        == "association_timeout"
    )

    repeated = accumulator.process(legacy_frame(5.0, False))
    assert repeated.completed_tracks is None
