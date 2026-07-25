import unittest

import torch

from byte_tracker.byte_tracker_model import BYTETracker
from byte_tracker.utils.basetrack import BaseTrack


def _detections(rows):
    return torch.tensor(rows, dtype=torch.float32)


class ByteTrackerCoreTest(unittest.TestCase):
    def setUp(self):
        BaseTrack._count = 0

    def _tracker(self):
        return BYTETracker(
            fps=30,
            first_track_thresh=0.5,
            second_track_thresh=0.1,
            match_thresh=0.8,
            track_buffer=30,
            resize_width_height=1,
        )

    def test_high_confidence_detection_starts_track(self):
        tracker = self._tracker()

        tracks = tracker.update(_detections([[10, 20, 30, 40, 0.9, 3]]))

        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].track_id, 1)
        self.assertEqual(int(tracks[0].class_name), 3)
        self.assertAlmostEqual(float(tracks[0].score), 0.9, places=5)

    def test_low_confidence_detection_can_recover_existing_track(self):
        tracker = self._tracker()
        first = tracker.update(_detections([[10, 20, 30, 40, 0.9, 3]]))

        second = tracker.update(_detections([[11, 20, 31, 40, 0.3, 3]]))

        self.assertEqual(len(second), 1)
        self.assertEqual(second[0].track_id, first[0].track_id)
        self.assertEqual(int(second[0].class_name), 3)
        self.assertAlmostEqual(float(second[0].score), 0.3, places=5)

    def test_image_iou_preserves_ids_when_detection_order_changes(self):
        tracker = self._tracker()
        first = tracker.update(
            _detections([
                [0, 0, 20, 20, 0.9, 3],
                [100, 0, 120, 20, 0.9, 3],
            ]),
            timestamp=0.0,
        )
        first_ids = [track.track_id for track in first]

        reordered = tracker.update(
            _detections([
                [100, 0, 120, 20, 0.9, 3],
                [0, 0, 20, 20, 0.9, 3],
            ]),
            timestamp=0.1,
        )
        boxes_by_id = {track.track_id: track.tlbr for track in reordered}

        self.assertEqual(first_ids, [1, 2])
        self.assertLess(boxes_by_id[1][0], 50)
        self.assertGreater(boxes_by_id[2][0], 50)

    def test_explicit_allocator_isolated_from_global_track_counter(self):
        BaseTrack._count = 99
        assigned = iter([7001, 7002])
        tracker = BYTETracker(
            fps=30,
            first_track_thresh=0.5,
            second_track_thresh=0.1,
            match_thresh=0.8,
            track_buffer=30,
            resize_width_height=1,
            track_id_allocator=lambda: next(assigned),
        )

        tracks = tracker.update(
            _detections([
                [0, 0, 20, 20, 0.9, 3],
                [100, 0, 120, 20, 0.9, 3],
            ])
        )

        self.assertEqual([track.track_id for track in tracks], [7001, 7002])
        self.assertEqual(BaseTrack._count, 99)

    def test_cross_business_group_class_change_requires_three_frames(self):
        tracker = BYTETracker(
            fps=30,
            first_track_thresh=0.5,
            second_track_thresh=0.1,
            match_thresh=0.8,
            track_buffer=30,
            resize_width_height=1,
            class_group_resolver=lambda class_id: (
                "non_motor" if class_id == 2 else "motor"
            ),
            class_switch_confirm_frames=3,
        )
        tracker.update(_detections([[10, 20, 30, 40, 0.9, 3]]))

        first_jitter = int(
            tracker.update(_detections([[10, 20, 30, 40, 0.9, 2]]))[0].class_name
        )
        second_jitter = int(
            tracker.update(_detections([[10, 20, 30, 40, 0.9, 2]]))[0].class_name
        )
        confirmed = int(
            tracker.update(_detections([[10, 20, 30, 40, 0.9, 2]]))[0].class_name
        )

        self.assertEqual(first_jitter, 3)
        self.assertEqual(second_jitter, 3)
        self.assertEqual(confirmed, 2)

    def test_same_business_group_class_change_updates_immediately(self):
        tracker = BYTETracker(
            fps=30,
            first_track_thresh=0.5,
            second_track_thresh=0.1,
            match_thresh=0.8,
            track_buffer=30,
            resize_width_height=1,
            class_group_resolver=lambda _class_id: "motor",
            class_switch_confirm_frames=3,
        )
        tracker.update(_detections([[10, 20, 30, 40, 0.9, 3]]))

        changed = tracker.update(_detections([[10, 20, 30, 40, 0.9, 5]]))

        self.assertEqual(int(changed[0].class_name), 5)

if __name__ == "__main__":
    unittest.main()
