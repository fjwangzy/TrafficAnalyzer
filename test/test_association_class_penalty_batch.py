"""Exact class penalties and full tracking output under mixed classes/occlusion."""

from types import SimpleNamespace

import numpy as np
import pytest

from byte_tracker.byte_tracker_model import BYTETracker
from byte_tracker.utils import matching


def original_distance(self, tracks, detections):
    costs = matching.iou_distance(tracks, detections)
    classes = np.asarray([int(d.class_name) for d in detections], dtype=np.int64)
    groups = [d.class_group for d in detections]
    for row, track in enumerate(tracks):
        penalty = np.where(
            np.asarray([track.class_group is not None and group is not None and track.class_group != group for group in groups], dtype=bool),
            .16, np.where(classes != int(track.class_name), .08, 0.),
        )
        costs[row] = np.minimum(1., costs[row] + penalty)
    return costs


@pytest.mark.parametrize("n,m", [(0, 5), (5, 0), (1, 1), (67, 71), (486, 300)])
def test_distance_is_elementwise_identical(n, m):
    rng = np.random.default_rng(31)
    def make(count):
        rows = []
        for _ in range(count):
            x, y = rng.uniform(0, 20, 2)
            rows.append(SimpleNamespace(tlbr=np.array([x, y, x + 5, y + 5]), class_name=int(rng.integers(0, 7)), class_group=[None, "motor", "non_motor"][int(rng.integers(0, 3))]))
        return rows
    tracks, detections = make(n), make(m)
    np.testing.assert_array_equal(
        BYTETracker._association_distance(SimpleNamespace(frame_id=1), tracks, detections),
        original_distance(None, tracks, detections),
    )


def test_groups_are_read_once_per_object():
    reads = []
    class Track:
        tlbr = np.array([0., 0., 10., 10.])
        class_name = 3
        @property
        def class_group(self):
            reads.append(1)
            return "motor"
    BYTETracker._association_distance(SimpleNamespace(frame_id=1), [Track() for _ in range(100)], [Track() for _ in range(100)])
    assert len(reads) <= 200


def test_mixed_class_real_tracker_sequence_is_unchanged(monkeypatch):
    import json
    from elements.FrameElement import FrameElement
    from nodes.GroundTrajectoryTrackerNode import GroundTrajectoryTrackerNode

    def replay():
        node = GroundTrajectoryTrackerNode({"tracking_node": {"first_track_thresh": .05, "second_track_thresh": .01, "match_thresh": .8, "track_buffer": 30, "max_lost_sec": 2.}})
        outputs = []
        for i in range(80):
            visible = [j for j in range(80) if not (j % 7 == 0 and 25 <= i < 32)]
            boxes = [[10+(j%10)*24+i*.2, 10+(j//10)*24, 22+(j%10)*24+i*.2, 22+(j//10)*24] for j in visible]
            ids = [j % 7 for j in visible]
            frame = FrameElement("class-replay", None, i*.1, i+1, {}, detected_xyxy=boxes, detected_cls=[str(c) for c in ids], detected_cls_ids=ids, detected_conf=[.9 if j%3 else .03 for j in visible])
            frame.camera_motion_warp = np.eye(3)
            frame = node.process(frame)
            outputs.append(json.dumps({"ids": frame.id_list, "boxes": frame.tracked_xyxy, "classes": frame.tracked_cls, "trajectories": frame.association_trajectories, "diagnostics": frame.tracking_diagnostics}, sort_keys=True, default=lambda v: v.tolist() if isinstance(v, np.ndarray) else v.item()))
        return outputs
    candidate = replay()
    monkeypatch.setattr(BYTETracker, "_association_distance", original_distance)
    assert replay() == candidate
