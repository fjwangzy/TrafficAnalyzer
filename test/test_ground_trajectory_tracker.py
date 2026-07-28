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
    frame.pixel_to_map_enu = projection
    frame.geo_reference_quality = {"status": "verified"}
    frame.formal_analytics_eligible = True
    return frame


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


def test_geo_reference_quality_break_keeps_candidate_out_of_business_buffer():
    BaseTrack._count = 0
    tracker = _TrackingPipeline(_config())
    accumulator = TrackerInfoUpdateNode(_config())

    formal = tracker.process(_frame(0.0, [20, 20, 40, 40]))
    formal.homography_matrix = np.eye(3)
    formal.pixel_to_map_enu = np.eye(3)
    formal.drone_displacement_m = np.zeros(2)
    accumulated = accumulator.process(formal)
    assert list(accumulated.buffer_tracks) == [1]

    degraded = _frame(0.1, [20, 20, 40, 40])
    degraded.formal_analytics_eligible = False
    degraded.flight_phase = "unsupported_pose"
    degraded.geo_reference_quality = {"status": "degraded"}
    degraded.homography_matrix = np.eye(3)
    degraded.pixel_to_map_enu = np.eye(3)
    degraded.drone_displacement_m = np.zeros(2)
    degraded = tracker.process(degraded)
    accumulated = accumulator.process(degraded)

    assert degraded.id_list == [1]  # image association remains renderable/continuous
    assert degraded.association_id_list == [1]
    assert degraded.tracking_diagnostics["terminated_track_ids"] == [1]
    assert accumulated.buffer_tracks == {}


def test_candidate_tail_keeps_image_history_across_geo_quality_break():
    tracker = _TrackingPipeline(_config())
    formal = _frame(0.0, [20, 20, 40, 40])
    formal.pixel_to_map_enu = np.eye(3)
    tracker.process(formal)

    degraded = _frame(0.1, [21, 20, 41, 40])
    degraded.formal_analytics_eligible = False
    degraded.geo_reference_quality = {
        "status": "degraded",
        "reasons": ["visual_warp_not_verified"],
    }
    degraded.pixel_to_map_enu = np.eye(3)

    result = tracker.process(degraded)

    assert result.id_list == [1]
    trajectory = result.candidate_trajectories[0]["trajectory_px"]
    assert len(trajectory) == 2
    np.testing.assert_allclose(trajectory[0], [30.0, 40.0])
    np.testing.assert_allclose(trajectory[1], [30.87, 40.0], atol=0.02)


def test_display_trace_uses_box_center_while_business_geometry_uses_ground_contact():
    BaseTrack._count = 0
    tracker = _TrackingPipeline(_config())
    frame = _frame(0.0, [20, 10, 40, 50])
    frame.formal_analytics_eligible = False
    frame.geo_reference_quality = {"status": "degraded"}

    result = tracker.process(frame)

    candidate = result.candidate_trajectories[0]
    assert candidate["trajectory_px"] == [[30.0, 50.0]]
    assert candidate["trajectory_display_px"] == [[30.0, 30.0]]


def test_target_outside_published_map_coverage_never_enters_formal_buffer():
    BaseTrack._count = 0
    tracker = _TrackingPipeline(_config())
    accumulator = TrackerInfoUpdateNode(_config())
    frame = _frame(0.0, [20, 20, 40, 40])
    frame.pixel_to_map_enu = np.eye(3)
    frame.homography_matrix = np.eye(3)
    frame.drone_displacement_m = np.zeros(2)
    frame.geo_reference_quality = {
        "status": "verified",
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
    assert frame.buffer_tracks == {}
    assert frame.candidate_trajectories == [{
        "track_id": 1,
        "association_id": 1,
        "tracking_method": "motion_compensated_image_v2",
        "tracking_quality": "degraded",
        "quality_reasons": ["target_outside_map_coverage"],
        "flight_phase": "telemetry_unavailable",
        "flight_segment_id": None,
        "trajectory_px": [[30.0, 40.0]],
        "trajectory_display_px": [[30.0, 30.0]],
        "trajectory_enu_m": [[30.0, 40.0]],
        "trajectory_timestamps_sec": [0.0],
        "trajectory_frame_nums": [0],
        "point_quality_lineage": [{
            "timestamp_sec": 0.0,
            "frame_num": 0,
            "flight_phase": "telemetry_unavailable",
            "flight_segment_id": None,
            "geo_reference_quality": "verified",
            "tracking_quality": "degraded",
        }],
    }]


def test_degraded_candidate_history_is_bounded_and_never_marked_formal():
    BaseTrack._count = 0
    tracker = _TrackingPipeline(_config())
    frames = []
    for index in range(35):
        frame = _frame(index * 0.1, [20 + index, 20, 40 + index, 40])
        frame.formal_analytics_eligible = False
        frame.flight_phase = "unsupported_pose"
        frame.geo_reference_quality = {
            "status": "degraded",
            "reasons": ["flight_pose_not_eligible"],
        }
        frame.pixel_to_map_enu = np.eye(3)
        frames.append(tracker.process(frame))

    candidate = frames[-1].candidate_trajectories[0]
    assert candidate["track_id"] == 1
    assert candidate["tracking_quality"] == "degraded"
    assert candidate["quality_reasons"] == ["flight_pose_not_eligible"]
    assert len(candidate["trajectory_px"]) == 30
    assert len(candidate["trajectory_display_px"]) == 30
    assert len(candidate["trajectory_enu_m"]) == 30
    assert frames[-1].formal_track_ids == []


def test_candidate_display_history_warps_old_points_into_current_frame():
    BaseTrack._count = 0
    tracker = _TrackingPipeline(_config())

    first = _frame(0.0, [20, 20, 40, 40])
    first.formal_analytics_eligible = False
    first.geo_reference_quality = {"status": "degraded"}
    tracker.process(first)

    warp = np.array([
        [1.0, 0.0, -20.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
    ])
    second = _frame(0.1, [5, 20, 25, 40], warp=warp)
    second.formal_analytics_eligible = False
    second.geo_reference_quality = {"status": "degraded"}

    result = tracker.process(second)

    candidate = result.candidate_trajectories[0]
    assert np.allclose(candidate["trajectory_px"][0], [30.0, 40.0])
    assert np.allclose(
        candidate["trajectory_display_px"],
        [[10.0, 30.0], [candidate["trajectory_px"][1][0], 30.0]],
    )


def test_candidate_keeps_source_pixels_and_reprojects_world_history_for_display():
    BaseTrack._count = 0
    tracker = _TrackingPipeline(_config())

    first = _frame(0.0, [20, 20, 40, 40])
    first.formal_analytics_eligible = False
    first.geo_reference_quality = {"status": "degraded"}
    first.pixel_to_map_enu = np.eye(3)
    tracker.process(first)

    current_h = np.array([
        [1.0, 0.0, 20.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
    ])
    current_warp = np.linalg.inv(current_h)
    second = _frame(0.1, [0, 20, 20, 40], warp=current_warp)
    second.formal_analytics_eligible = False
    second.geo_reference_quality = {"status": "degraded"}
    second.pixel_to_map_enu = current_h

    candidate = tracker.process(second).candidate_trajectories[0]

    assert candidate["trajectory_px"] == [[30.0, 40.0], [10.0, 40.0]]
    assert candidate["trajectory_enu_m"] == [[30.0, 40.0], [30.0, 40.0]]
    assert candidate["trajectory_display_px"] == [[10.0, 30.0], [10.0, 30.0]]
    assert candidate["trajectory_timestamps_sec"] == [0.0, 0.1]
    assert candidate["trajectory_frame_nums"] == [0, 1]
    assert len(candidate["point_quality_lineage"]) == 2


def test_short_telemetry_gap_bridges_candidate_id_but_recovery_gets_new_formal_id():
    BaseTrack._count = 0
    tracker = _TrackingPipeline(_config())

    formal = tracker.process(_frame(0.0, [20, 20, 40, 40]))
    missing = _frame(0.1, [20, 20, 40, 40])
    missing.formal_analytics_eligible = False
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
    assert missing.tracking_diagnostics["termination_reason"] == "telemetry_gap"
    assert recovered.id_list == [1]
    assert recovered.formal_track_ids == [1]
    assert recovered.formal_track_id_by_association == {1: 2}


def test_quality_recovery_creates_new_formal_segment_in_same_image_family():
    tracker = _TrackingPipeline(_config())
    accumulator = TrackerInfoUpdateNode(_config())

    first = _frame(0.0, [20, 20, 40, 40])
    first.homography_matrix = np.eye(3)
    first.pixel_to_map_enu = np.eye(3)
    first.drone_displacement_m = np.zeros(2)
    accumulator.process(tracker.process(first))

    degraded = _frame(0.1, [20, 20, 40, 40])
    degraded.formal_analytics_eligible = False
    degraded.flight_phase = "telemetry_unavailable"
    degraded.geo_reference_quality = {
        "status": "degraded",
        "reasons": ["telemetry_unavailable"],
    }
    degraded.homography_matrix = np.eye(3)
    degraded.pixel_to_map_enu = np.eye(3)
    degraded.drone_displacement_m = np.zeros(2)
    accumulator.process(tracker.process(degraded))

    recovered = _frame(0.2, [20, 20, 40, 40])
    recovered.homography_matrix = np.eye(3)
    recovered.pixel_to_map_enu = np.eye(3)
    recovered.drone_displacement_m = np.zeros(2)
    result = accumulator.process(tracker.process(recovered))

    assert result.id_list == [1]
    assert list(result.buffer_tracks) == [2]
    formal_track = result.buffer_tracks[2]
    assert formal_track.association_id == 1
    assert formal_track.track_family_id == "association:1"
    assert formal_track.previous_track_id == 1


def test_telemetry_gap_never_resets_image_association_tracker():
    BaseTrack._count = 0
    tracker = _TrackingPipeline(_config())
    tracker.process(_frame(0.0, [20, 20, 40, 40]))

    ids = []
    for timestamp in (0.1, 0.4, 0.61):
        frame = _frame(timestamp, [20, 20, 40, 40])
        frame.formal_analytics_eligible = False
        frame.flight_phase = "telemetry_unavailable"
        frame.geo_reference_quality = {
            "status": "degraded",
            "reasons": ["telemetry_unavailable"],
        }
        result = tracker.process(frame)
        ids.append(result.id_list[0])

    assert ids == [1, 1, 1]
    assert result.formal_track_ids == []


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
        frame.pixel_to_map_enu = np.eye(3)
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
