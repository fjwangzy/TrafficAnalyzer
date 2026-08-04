from types import SimpleNamespace

import numpy as np

from elements.FrameElement import FrameElement
from nodes.CalcStatisticsNode import CalcStatisticsNode


def _node() -> CalcStatisticsNode:
    return CalcStatisticsNode(
        {
            "general": {
                "buffer_analytics": 1,
                "min_time_life_track": 2,
                "count_cars_buffer_frames": 3,
            }
        }
    )


def _frame(*, road_eligible: bool) -> FrameElement:
    frame = FrameElement(
        "fixture.mp4", np.zeros((8, 8, 3), dtype=np.uint8), 10.0, 10, {}
    )
    frame.geo_reference_quality = {
        "status": "degraded",
        "reasons": ["lane_verified_map_required"],
    }
    frame.trajectory_output_eligible = True
    frame.geo_analytics_eligible = False
    frame.road_analytics_eligible = road_eligible
    frame.tcc_analytics_eligible = False
    frame.formal_analytics_eligible = road_eligible
    frame.roads_info = {1: {}, 2: {}}
    frame.buffer_tracks = {
        1: SimpleNamespace(
            timestamp_last=10.0,
            timestamp_init_road=0.0,
            start_road=1,
        ),
        2: SimpleNamespace(
            timestamp_last=10.0,
            timestamp_init_road=0.0,
            start_road=None,
        ),
    }
    return frame


def test_missing_road_context_keeps_generic_vehicle_count():
    result = _node().process(_frame(road_eligible=False))

    assert result.info["cars_amount"] == 2
    assert result.info["roads_activity"] == {1: 1.0, 2: 0.0}
    assert result.info["trajectory_output_eligible"] is True
    assert result.info["road_analytics_eligible"] is False


def test_road_context_only_controls_lane_link_matching_capability():
    node = _node()
    roadless = node.process(_frame(road_eligible=False))
    with_road = node.process(_frame(road_eligible=True))

    assert roadless.info["cars_amount"] == with_road.info["cars_amount"] == 2
    assert roadless.info["roads_activity"] == with_road.info["roads_activity"]
    assert roadless.info["formal_analytics_eligible"] is False
    assert with_road.info["formal_analytics_eligible"] is True


def test_flow_window_expires_without_re_registering_or_demoting_active_track():
    node = CalcStatisticsNode(
        {
            "general": {
                "buffer_analytics": 0.5,
                "min_time_life_track": 3,
                "count_cars_buffer_frames": 1,
            }
        }
    )
    mature = SimpleNamespace(
        timestamp_last=3.1,
        timestamp_init_road=0.0,
        start_road=1,
        trajectory_output_eligible=True,
    )
    candidate = SimpleNamespace(
        timestamp_last=3.1,
        timestamp_init_road=0.0,
        start_road=1,
        trajectory_output_eligible=False,
    )

    def process(timestamp):
        frame = FrameElement(
            "fixture.mp4",
            np.zeros((8, 8, 3), dtype=np.uint8),
            timestamp,
            round(timestamp * 10),
            {1: {}},
        )
        mature.timestamp_last = timestamp
        candidate.timestamp_last = timestamp
        frame.buffer_tracks = {1: mature, 2: candidate}
        frame.active_tracks = frame.buffer_tracks
        frame.mature_tracks = {1: mature}
        return node.process(frame)

    qualified = process(3.1)
    assert qualified.info["cars_amount"] == 1
    assert qualified.info["roads_activity"] == {1: 2.0}

    expired = process(33.2)
    assert expired.info["cars_amount"] == 1
    assert expired.info["roads_activity"] == {1: 0.0}
    assert list(expired.mature_tracks) == [1]

    still_expired = process(35.0)
    assert still_expired.info["roads_activity"] == {1: 0.0}
