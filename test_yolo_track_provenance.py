import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from elements.FrameElement import FrameElement
from nodes.DetectionTrackingNodes import build_yolo_model_id
from nodes.TrackerInfoUpdateNode import TrackerInfoUpdateNode


class YoloTrackProvenanceTest(unittest.TestCase):
    def test_model_identifier_uses_weight_name_and_content_digest(self):
        with TemporaryDirectory() as directory:
            weight = Path(directory) / "traffic.pt"
            weight.write_bytes(b"stable-weight-content")

            model_id = build_yolo_model_id(weight)

        self.assertEqual(model_id, "traffic.pt@3d1ed41c9c48")

    def test_completed_track_retains_raw_yolo_class_and_mapping_provenance(self):
        node = TrackerInfoUpdateNode({
            "general": {"buffer_analytics": 0, "min_time_life_track": 5},
            "trajectory": {"min_track_duration_sec": 2},
            "vehicle_classification": {"mapping_version": "visdrone-business/v1"},
        })
        frame = np.zeros((100, 100, 3), dtype=np.uint8)

        for second in range(5):
            item = FrameElement("video", frame, float(second), second + 1, {})
            item.id_list = [17]
            item.tracked_xyxy = [[10 + second, 10, 20 + second, 20]]
            item.tracked_cls_ids = [3]
            item.tracked_cls = ["car"]
            item.yolo_model_id = "yolo11s-visdrone.pt@0123456789ab"
            node.process(item)

        retired = FrameElement("video", frame, 10.0, 11, {})
        retired.id_list = []
        retired.tracked_xyxy = []
        retired.tracked_cls_ids = []
        retired.tracked_cls = []
        retired.yolo_model_id = "yolo11s-visdrone.pt@0123456789ab"

        node.process(retired)

        self.assertEqual(len(retired.completed_tracks), 1)
        track = retired.completed_tracks[0]
        self.assertEqual(track["vehicle_class"], "motor")
        self.assertEqual(track["yolo_class_id"], 3)
        self.assertEqual(track["yolo_class_name"], "car")
        self.assertEqual(track["yolo_model_id"], "yolo11s-visdrone.pt@0123456789ab")
        self.assertEqual(track["class_mapping_version"], "visdrone-business/v1")


if __name__ == "__main__":
    unittest.main()
