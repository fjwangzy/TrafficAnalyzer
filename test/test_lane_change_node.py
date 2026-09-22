import numpy as np

from elements.FrameElement import FrameElement
from elements.TrackElement import TrackElement
from nodes.LaneChangeDetectionNode import LaneChangeDetectionNode


def _frame(track: TrackElement, timestamp: float = 11.0) -> FrameElement:
    frame = FrameElement("test", np.zeros((32, 32, 3)), timestamp, timestamp * 10, {})
    frame.active_tracks = {track.id: track}
    frame.mature_tracks = {track.id: track}
    return frame


def test_detects_one_trajectory_only_lane_change_without_lane_geometry():
    track = TrackElement(7, 0.0)
    track.trajectory_output_eligible = True
    track.position_history_enu_m = [
        (0.0, 0.0, 0.0), (1.0, 0.0, 1.0), (2.0, 0.0, 2.0), (3.0, 0.0, 3.0),
        (4.0, 0.0, 4.0), (5.0, 1.0, 5.0), (6.0, 2.0, 6.0), (7.0, 3.0, 7.0),
        (8.0, 4.0, 8.0), (9.0, 4.0, 9.0), (10.0, 4.0, 10.0), (11.0, 4.0, 11.0),
    ]
    node = LaneChangeDetectionNode({"lane_change_detection": {"min_lateral_displacement_m": 2.0}})

    result = node.process(_frame(track))

    assert result.lane_change_events[0]["track_id"] == 7
    assert result.lane_change_events[0]["direction"] == "left"
    assert result.lane_change_events[0]["inference_basis"] == "trajectory_only_enu"
    assert "from_lane" not in result.lane_change_events[0]
    assert node.process(_frame(track)).lane_change_events == []


def test_does_not_call_a_normal_turn_a_lane_change():
    track = TrackElement(8, 0.0)
    track.trajectory_output_eligible = True
    track.position_history_enu_m = [
        (0.0, 0.0, 0.0), (1.0, 0.0, 1.0), (2.0, 0.0, 2.0), (3.0, 0.0, 3.0),
        (4.0, 0.0, 4.0), (5.0, 0.5, 5.0), (6.0, 1.5, 6.0), (6.5, 2.5, 7.0),
        (6.5, 3.5, 8.0), (6.5, 4.5, 9.0), (6.5, 5.5, 10.0), (6.5, 6.5, 11.0),
    ]

    result = LaneChangeDetectionNode({"lane_change_detection": {"min_lateral_displacement_m": 2.0}}).process(_frame(track))

    assert result.lane_change_events == []
