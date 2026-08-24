import numpy as np

from elements.FrameElement import FrameElement
from elements.TrackElement import TrackElement
from nodes.AutoLaneInferenceNode import AutoLaneInferenceNode
from utils_local.auto_lane_inference import InferredLane


def test_unknown_world_speed_is_not_treated_as_zero_or_a_stopped_vehicle():
    node = AutoLaneInferenceNode({"auto_lane": {"enabled": True}})
    lane = InferredLane(
        lane_id="lane_1",
        label="candidate",
        direction_class="straight",
        entry_heading_deg=0.0,
        exit_heading_deg=0.0,
        centerline_px=[[0.0, 0.0], [10.0, 0.0]],
        entry_center_px=(0.0, 0.0),
        exit_center_px=(10.0, 0.0),
    )
    node._inferred_lanes = {lane.lane_id: lane}

    unknown = TrackElement(id=1, timestamp_first=0.0)
    unknown.trajectory_output_eligible = True
    unknown.current_lane = lane.lane_id
    unknown.avg_speed_kmh = None
    moving = TrackElement(id=2, timestamp_first=0.0)
    moving.trajectory_output_eligible = True
    moving.current_lane = lane.lane_id
    moving.avg_speed_kmh = 18.0

    frame = FrameElement(
        "test",
        np.zeros((32, 32, 3), dtype=np.uint8),
        1.0,
        1,
        {},
        buffer_tracks={unknown.id: unknown, moving.id: moving},
    )
    node._compute_lane_stats(frame, current_time=1.0)

    assert lane.count == 2
    assert lane.avg_speed_kmh == 18.0
    assert lane.stopped_count == 0


def test_queue_length_uses_metres_only_with_a_valid_homography():
    node = AutoLaneInferenceNode({"auto_lane": {"enabled": True}})
    lane = InferredLane(
        lane_id="lane_1",
        label="北→南 直行",
        direction_class="straight",
        entry_heading_deg=90.0,
        exit_heading_deg=90.0,
        centerline_px=[[0.0, 0.0], [10.0, 0.0]],
        entry_center_px=(0.0, 0.0),
        exit_center_px=(10.0, 0.0),
    )
    node._inferred_lanes = {lane.lane_id: lane}

    tracks = {}
    for track_id, point in ((1, [0.0, 0.0]), (2, [3.0, 4.0])):
        track = TrackElement(id=track_id, timestamp_first=0.0)
        track.trajectory_output_eligible = True
        track.current_lane = lane.lane_id
        track.avg_speed_kmh = 0.0
        track.trajectory_points = [point]
        tracks[track_id] = track

    metric_frame = FrameElement(
        "metric",
        np.zeros((32, 32, 3), dtype=np.uint8),
        1.0,
        1,
        {},
        buffer_tracks=tracks,
    )
    metric_frame.homography_matrix = np.eye(3)
    node._compute_lane_stats(metric_frame, current_time=1.0)
    assert lane.queue_length_m == 5.0
    assert lane.queue_length_px is None
    assert lane.queue_length_unit == "m"
    assert lane.queue_length_method == "homography_world"

    pixel_frame = FrameElement(
        "pixel",
        np.zeros((32, 32, 3), dtype=np.uint8),
        1.0,
        1,
        {},
        buffer_tracks=tracks,
    )
    pixel_frame.homography_matrix = None
    node._compute_lane_stats(pixel_frame, current_time=1.0)
    assert lane.queue_length_m is None
    assert lane.queue_length_px == 5.0
    assert lane.queue_length_unit == "px"
    assert lane.queue_length_method == "pixel_fallback"
