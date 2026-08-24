import numpy as np
import pytest

from elements.FrameElement import FrameElement
from elements.TrackElement import TrackElement
from nodes.DirectionFlowNode import DirectionFlowNode
from nodes.SpeedEstimationNode import SpeedEstimationNode


def _frame_with_track(track: TrackElement) -> FrameElement:
    frame = FrameElement(
        source="test",
        frame=np.zeros((80, 120, 3), dtype=np.uint8),
        timestamp=0.2,
        frame_num=2,
        roads_info={},
    )
    frame.buffer_tracks = {track.id: track}
    frame.homography_matrix = np.eye(3)
    frame.drone_displacement_m = np.zeros(2)
    frame.geo_analytics_eligible = True
    return frame


def test_hover_cruise_speed_requires_per_frame_world_facts():
    track = TrackElement(id=1, timestamp_first=0.0)
    track.position_history = [
        (10.0, 20.0, 0.0),
        (11.0, 20.0, 0.1),
        (12.0, 20.0, 0.2),
    ]
    frame = _frame_with_track(track)
    node = SpeedEstimationNode(
        {
            "tracking_profile": "hover_cruise_v1",
            "speed_estimation": {"enabled": True},
        }
    )

    result = node.process(frame)

    assert result.buffer_tracks[1].velocity_ms is None
    assert result.buffer_tracks[1].speed_kmh is None
    assert result.buffer_tracks[1].avg_speed_kmh is None


def test_hover_cruise_speed_uses_world_history_independent_of_current_h():
    track = TrackElement(id=1, timestamp_first=0.0)
    track.position_history = [
        (10.0, 20.0, 0.0),
        (80.0, 20.0, 0.1),
        (15.0, 20.0, 0.2),
    ]
    track.position_history_enu_m = [
        (0.0, 0.0, 0.0),
        (0.5, 0.0, 0.1),
        (1.0, 0.0, 0.2),
    ]
    track.trajectory_output_eligible = True
    frame = _frame_with_track(track)
    frame.homography_matrix = np.array(
        [[100.0, 0.0, 9000.0], [0.0, 100.0, -8000.0], [0.0, 0.0, 1.0]]
    )
    node = SpeedEstimationNode(
        {
            "tracking_profile": "hover_cruise_v1",
            "speed_estimation": {"enabled": True, "smoothing_window": 1},
        }
    )

    result = node.process(frame)

    np.testing.assert_allclose(result.buffer_tracks[1].velocity_ms, [5.0, 0.0])
    assert result.buffer_tracks[1].speed_kmh == pytest.approx(18.0)


def test_hover_cruise_speed_rejects_single_frame_world_position_outlier():
    track = TrackElement(id=1, timestamp_first=0.0)
    track.position_history_enu_m = [
        (0.0, 0.0, 0.0),
        (0.1, 0.0, 0.1),
        (0.2, 0.0, 0.2),
        (10.3, 0.0, 0.3),
        (0.4, 0.0, 0.4),
        (0.5, 0.0, 0.5),
    ]
    track.trajectory_output_eligible = True
    frame = _frame_with_track(track)
    node = SpeedEstimationNode(
        {
            "tracking_profile": "hover_cruise_v1",
            "speed_estimation": {
                "enabled": True,
                "smoothing_window": 1,
                "max_segment_speed_ms": 45.0,
            },
        }
    )

    result = node.process(frame)

    np.testing.assert_allclose(result.buffer_tracks[1].velocity_ms, [1.0, 0.0])
    assert result.buffer_tracks[1].speed_kmh == pytest.approx(3.6)


def test_hover_only_legacy_does_not_invent_speed_from_pixel_history():
    track = TrackElement(id=1, timestamp_first=0.0)
    track.position_history = [
        (10.0, 20.0, 0.0),
        (11.0, 20.0, 0.1),
        (12.0, 20.0, 0.2),
    ]
    frame = _frame_with_track(track)
    node = SpeedEstimationNode(
        {
            "tracking_profile": "hover_only_legacy",
            "speed_estimation": {"enabled": True, "smoothing_window": 1},
        }
    )

    result = node.process(frame)

    assert result.buffer_tracks[1].velocity_ms is None
    assert result.buffer_tracks[1].speed_kmh is None
    assert result.buffer_tracks[1].avg_speed_kmh is None


def test_direction_statistics_keep_unknown_speed_null():
    frame = FrameElement(
        source="test",
        frame=np.zeros((80, 120, 3), dtype=np.uint8),
        timestamp=0.2,
        frame_num=2,
        roads_info={},
    )
    frame.geo_reference_quality = {"status": "verified"}
    frame.geo_analytics_eligible = True
    frame.buffer_tracks = {}
    node = DirectionFlowNode({"direction_flow": {"enabled": True}})

    result = node.process(frame)

    for direction in ("straight", "left_turn", "right_turn", "u_turn"):
        assert result.direction_stats[direction]["avg_speed_kmh"] is None


def test_candidate_track_cannot_enter_speed_direction_or_queue_business_outputs():
    candidate = TrackElement(id=9, timestamp_first=0.0)
    candidate.position_history_enu_m = [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.1),
        (2.0, 0.0, 0.2),
    ]
    candidate.trajectory_output_eligible = False
    frame = _frame_with_track(candidate)
    frame.active_tracks = {9: candidate}
    frame.mature_tracks = {}

    speed = SpeedEstimationNode(
        {
            "tracking_profile": "hover_cruise_v1",
            "speed_estimation": {"enabled": True, "smoothing_window": 1},
        }
    ).process(frame)
    result = DirectionFlowNode(
        {"direction_flow": {"enabled": True, "queue_speed_threshold_kmh": 5.0}}
    ).process(speed)

    assert candidate.velocity_ms is None
    assert candidate.speed_kmh is None
    assert candidate.avg_speed_kmh is None
    assert result.queue_count == 0
    assert all(
        result.direction_stats[direction]["count"] == 0
        for direction in ("straight", "left_turn", "right_turn", "u_turn")
    )
    assert result.direction_stats["unknown"]["count"] == 0
