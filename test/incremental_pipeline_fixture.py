"""Explicit CPU-only synthetic input for the real main_optimized four workers.

No detector/NPU accuracy or production FPS claim. Production entry remains unchanged.
"""

import multiprocessing
import os
from pathlib import Path
import time
import numpy as np
from omegaconf import OmegaConf
import main_optimized as pipeline
from elements.FrameElement import FrameElement
from elements.VideoEndBreakElement import VideoEndBreakElement


class Reader:
    def __init__(self, *args):
        pass

    def process(self):
        background = np.random.default_rng(29).integers(
            0, 255, (120, 160, 3), dtype=np.uint8
        )
        for i in range(600):
            time.sleep(0.01)
            yield FrameElement(
                "incremental-fixture", background.copy(), i / 10, i + 1, {}
            )
        yield VideoEndBreakElement("incremental-fixture", 60.0)


class Detector:
    def __init__(self, *args):
        pass

    def process(self, frame):
        if not isinstance(frame, VideoEndBreakElement):
            i = frame.frame_num
            boxes = (
                [[20 + (i % 50) * 0.02, 30, 40 + (i % 50) * 0.02, 50]]
                if i < 80 or i >= 180
                else []
            )
            frame.detected_xyxy = boxes
            frame.detected_cls_ids = [3] * len(boxes)
            frame.detected_cls = ["car"] * len(boxes)
            frame.detected_conf = [0.99] * len(boxes)
        return frame


class Reference:
    def __init__(self, *args):
        pass

    def process(self, frame):
        if not isinstance(frame, VideoEndBreakElement):
            frame.pixel_to_world_enu = frame.homography_matrix = np.diag(
                [0.1, 0.1, 1.0]
            )
            frame.drone_displacement_m = np.zeros(2)
            frame.anchor_gcj02 = (117.0, 36.0)
            frame.geo_reference_quality = {
                "status": "verified",
                "geo_status": "verified",
                "reasons": [],
            }
            frame.geo_analytics_eligible = True
            frame.road_analytics_eligible = False
            frame.tcc_analytics_eligible = False
            frame.formal_analytics_eligible = False
            frame.flight_phase = "hover"
            frame.flight_segment_id = "fixture"
        return frame


# Re-imported by spawned test workers too; never modifies normal application entry.
pipeline.VideoReader = Reader
pipeline.DetectionNode = Detector
pipeline.FlightGeoReferenceNode = Reference

if __name__ == "__main__":
    assert os.environ.get("TRAFFIC_SYNTHETIC_VALIDATION") == "1"
    assert os.environ["DB_NAME"] == "road9"
    # This fixture has no MPS/CANN calls. Fork also matches production's worker path.
    multiprocessing.set_start_method("fork", force=True)
    config = OmegaConf.load(
        Path(__file__).resolve().parents[1] / "configs/app_config.yaml"
    )
    config.pipeline.egress_enabled = True
    config.pipeline.send_info_kafka = os.environ.get("TRAFFIC_FIXTURE_NO_KAFKA") != "1"
    config.pipeline.show_in_web = True
    config.pipeline.save_video = False
    config.history_sampling.enabled = True
    config.show_node.imshow = False
    config.video_saver_node.save_conflict_clips = False
    config.telemetry.enabled = False
    config.detection_node.weight_pth = "fixture-no-appearance-model.pt"
    config.hydra.run.dir = os.environ["TRAFFIC_FIXTURE_DIR"]
    pipeline.main.__wrapped__(config)
