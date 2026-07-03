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


if __name__ == "__main__":
    unittest.main()
