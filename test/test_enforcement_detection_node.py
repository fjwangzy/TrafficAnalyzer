import numpy as np

from elements.FrameElement import FrameElement
from elements.TrackElement import TrackElement
from nodes.EnforcementDetectionNode import EnforcementDetectionNode


def test_emits_truck_restriction_candidate_from_frozen_enu_rule():
    track = TrackElement(21, 0.0)
    track.trajectory_output_eligible = True
    track.current_position_enu_m = [5.0, 5.0]
    track.yolo_class_name = "truck"
    track.vehicle_class_confidence = 0.91
    frame = FrameElement("test", np.zeros((32, 32, 3)), 10.0, 100, {})
    frame.mature_tracks = {21: track}
    node = EnforcementDetectionNode({"enforcement_detection": {
        "zones": [{
            "id": "ZONE-TRUCK", "version": "candidate-r1", "type": "truck_restriction",
            "geometry_enu_m": {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]},
        }],
        "rules": [{
            "id": "RULE-TRUCK", "version": "candidate-r1", "zone_id": "ZONE-TRUCK",
            "clue_type": "truck_restriction", "definition": {"vehicle_class": "truck"},
        }],
    }})

    result = node.process(frame)

    clue = result.enforcement_clues[0]
    assert clue["source_event_id"] == "enforcement:truck_restriction:RULE-TRUCK:21:10000"
    assert clue["track_id"] == "21"
    assert clue["vehicle_class"] == "truck"
    assert clue["clue_type"] == "truck_restriction"
    assert clue["zone_id"] == "ZONE-TRUCK"
    assert clue["rule_id"] == "RULE-TRUCK"
    assert clue["quality_status"] == "unverified"
    assert clue["matched_facts"] == {"inside_zone": True, "coordinate_system": "ENU"}


def test_speed_candidate_requires_observed_speed_above_frozen_threshold():
    track = TrackElement(22, 0.0)
    track.trajectory_output_eligible = True
    track.current_position_enu_m = [5.0, 5.0]
    track.avg_speed_kmh = 42.0
    frame = FrameElement("test", np.zeros((32, 32, 3)), 10.0, 100, {})
    frame.mature_tracks = {22: track}
    node = EnforcementDetectionNode({"enforcement_detection": {
        "zones": [{"id": "ZONE-SPEED", "geometry_enu_m": {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]}}],
        "rules": [{"id": "RULE-SPEED", "zone_id": "ZONE-SPEED", "clue_type": "speed_observation", "definition": {"max_speed_kmh": 40.0}}],
    }})

    clue = node.process(frame).enforcement_clues[0]

    assert clue["video_speed_kmh"] == 42.0
    assert clue["video_speed_method"] == "trajectory_enu"


def _parking_node():
    return EnforcementDetectionNode({
        "tracking_node": {"max_frame_gap_sec": 2.0},
        "enforcement_detection": {
            "zones": [{"id": "Z", "geometry_enu_m": {
                "type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
            }}],
            "rules": [{"id": "R", "zone_id": "Z", "clue_type": "no_parking",
                       "definition": {"min_dwell_sec": 5, "max_speed_kmh": 3}}],
        },
    })


def _parking_frame(timestamp, speed=1.0, position=(5, 5), observed=True):
    track = TrackElement(31, 0.0)
    track.trajectory_output_eligible = True
    track.current_position_enu_m = position
    track.current_observation_timestamp_sec = timestamp if observed else timestamp - 1
    track.avg_speed_kmh = speed
    frame = FrameElement("test", np.zeros((32, 32, 3)), timestamp, int(timestamp * 30), {})
    frame.mature_tracks = {31: track}
    return frame


def test_no_parking_requires_continuous_low_speed_and_emits_once():
    node = _parking_node()
    for second in range(5):
        assert not node.process(_parking_frame(second)).enforcement_clues
    assert len(node.process(_parking_frame(5)).enforcement_clues) == 1
    assert not node.process(_parking_frame(6)).enforcement_clues


def test_fast_zone_traversal_does_not_count_toward_parking_dwell():
    node = _parking_node()
    for second in range(5):
        assert not node.process(_parking_frame(second, speed=30)).enforcement_clues
    for second in range(5, 10):
        assert not node.process(_parking_frame(second)).enforcement_clues
    assert len(node.process(_parking_frame(10)).enforcement_clues) == 1


def test_parking_unknown_speed_and_missing_position_restart_dwell():
    for missing in ({"speed": None}, {"position": None}, {"observed": False}):
        node = _parking_node()
        for second in range(3):
            assert not node.process(_parking_frame(second)).enforcement_clues
        assert not node.process(_parking_frame(3, **missing)).enforcement_clues
        for second in range(4, 9):
            assert not node.process(_parking_frame(second)).enforcement_clues
        assert len(node.process(_parking_frame(9)).enforcement_clues) == 1


def test_parking_source_time_gap_does_not_invent_continuous_observation():
    node = _parking_node()
    assert not node.process(_parking_frame(0)).enforcement_clues
    assert not node.process(_parking_frame(20)).enforcement_clues


def test_unknown_vehicle_label_does_not_become_a_confirmed_non_truck():
    node = EnforcementDetectionNode({"enforcement_detection": {
        "zones": [{"id": "Z", "geometry_enu_m": {
            "type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
        }}],
        "rules": [{"id": "R", "zone_id": "Z", "clue_type": "speed_observation",
                   "definition": {"max_speed_kmh": 40}}],
    }})
    frame = _parking_frame(0, speed=42)
    frame.mature_tracks[31].yolo_class_name = "unknown"
    assert node.process(frame).enforcement_clues[0]["vehicle_class"] == "unknown"


def test_gcj02_null_current_projection_does_not_reuse_last_valid_position():
    node = EnforcementDetectionNode({"enforcement_detection": {
        "zones": [{"id": "Z", "coordinate_system": "GCJ02", "geometry": {
            "type": "Polygon", "coordinates": [[[116, 36], [118, 36], [118, 38], [116, 38], [116, 36]]],
        }}],
        "rules": [{"id": "R", "zone_id": "Z", "clue_type": "speed_observation",
                   "definition": {"max_speed_kmh": 40}}],
    }})
    frame = _parking_frame(0, speed=42)
    frame.mature_tracks[31].trajectory_gcj02 = [[117, 37], None]
    assert not node.process(frame).enforcement_clues
    frame.mature_tracks[31].trajectory_gcj02 = [[117, 37]]
    assert node.process(frame).enforcement_clues[0]["matched_facts"]["coordinate_system"] == "GCJ02"
