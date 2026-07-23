import json

import numpy as np

from elements.FrameElement import FrameElement
from elements.TrackElement import TrackElement
from nodes.RoadMapMatchingNode import RoadMapMatchingNode


def test_matches_bbox_ground_contact_to_lane(monkeypatch):
    bundle = {
        "map_status": "lane_verified", "coordinate_system": "GCJ02",
        "map_version_id": "CMV-1", "inter_id": "I1", "anchor_gcj02": [117.0, 36.0],
        "visual_registration": {"homography_pixel_to_enu": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]},
        "topology": {"lane_properties": {"east-1": {"movement_key": "east:straight"}}},
        "lanes": [{
            "local_lane_id": "east-1", "source_lane_id": "L1", "link_id": "K1",
            "geometry_enu_m": {"type": "Polygon", "coordinates": [[[0, 0], [20, 0], [20, 10], [0, 10], [0, 0]]]},
        }],
    }
    monkeypatch.setenv("RUNTIME_MAP_BUNDLE_JSON", json.dumps(bundle))
    node = RoadMapMatchingNode({})
    track = TrackElement(7, 0)
    frame = FrameElement("x", np.zeros((20, 20, 3)), 1, 1, {})
    frame.id_list = [7]
    frame.tracked_xyxy = [[2, 2, 8, 8]]
    frame.buffer_tracks = {7: track}
    result = node.process(frame)
    assert track.matched_lane_key == "east-1"
    assert track.source_lane_id == "L1"
    assert track.movement_key == "east:straight"
    assert result.map_version_id == "CMV-1"


def test_selects_registration_for_exact_source_profile(monkeypatch):
    bundle = {
        "map_status": "lane_verified", "coordinate_system": "GCJ02",
        "map_version_id": "CMV-1", "inter_id": "011opaque", "anchor_gcj02": [117.0, 36.0],
        "visual_registration": {
            "source_profile_id": "SRC-A",
            "homography_pixel_to_enu": [[1, 0, 100], [0, 1, 100], [0, 0, 1]],
        },
        "visual_registrations": [
            {
                "source_profile_id": "SRC-A",
                "homography_pixel_to_enu": [[1, 0, 100], [0, 1, 100], [0, 0, 1]],
            },
            {
                "source_profile_id": "SRC-B",
                "homography_pixel_to_enu": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
            },
        ],
        "topology": {"lane_properties": {"lane-b": {"movement_key": "straight"}}},
        "lanes": [{
            "local_lane_id": "lane-b", "source_lane_id": "opaque-lane", "link_id": "opaque-link",
            "geometry_enu_m": {"type": "Polygon", "coordinates": [[[0, 0], [20, 0], [20, 10], [0, 10], [0, 0]]]},
        }],
    }
    monkeypatch.setenv("SOURCE_PROFILE_ID", "SRC-B")
    monkeypatch.setenv("RUNTIME_MAP_BUNDLE_JSON", json.dumps(bundle))
    node = RoadMapMatchingNode({})
    track = TrackElement(8, 0)
    frame = FrameElement("x", np.zeros((20, 20, 3)), 1, 1, {})
    frame.id_list = [8]
    frame.tracked_xyxy = [[2, 2, 8, 8]]
    frame.buffer_tracks = {8: track}

    node.process(frame)

    assert track.matched_lane_key == "lane-b"
