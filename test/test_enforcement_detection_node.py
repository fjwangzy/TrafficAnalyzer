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
