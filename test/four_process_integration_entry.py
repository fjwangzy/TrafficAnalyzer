"""Synthetic authoritative tracking fixture, not a detector/NPU accuracy test."""

import os
import numpy as np
from omegaconf import OmegaConf
import main_optimized as pipeline
from elements.FrameElement import FrameElement
from elements.VideoEndBreakElement import VideoEndBreakElement


class SyntheticReader:
    def __init__(self, *args):
        pass

    def process(self):
        background = np.random.default_rng(72).integers(
            0, 255, (240, 320, 3), dtype=np.uint8
        )
        for i in range(300):
            yield FrameElement(
                "synthetic-contract-fixture", background.copy(), i / 10, i + 1, {}
            )
        yield VideoEndBreakElement("synthetic-contract-fixture", 30.0)


class SyntheticDetector:
    def __init__(self, *args):
        pass

    def process(self, frame):
        if not isinstance(frame, VideoEndBreakElement):
            x = 20 + 2 * max(0, frame.frame_num - 201)
            frame.detected_xyxy = [[x, 40, x + 20, 60]]
            frame.detected_cls_ids = [3]
            frame.detected_cls = ["car"]
            frame.detected_conf = [0.99]
        return frame


class SyntheticReference:
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
            frame.flight_segment_id = "synthetic"
        return frame


if __name__ == "__main__":
    assert os.environ["DB_NAME"] == "ycx_native_validation"
    assert os.environ["TRAJECTORY_STORAGE_PROFILE"] == "replay_v2"
    os.environ["VIDEO_SRC"] = "synthetic-contract-fixture"
    os.environ["PIPELINE_EGRESS_ENABLED"] = "true"
    os.environ["HISTORY_SAMPLING_ENABLED"] = "true"
    pipeline.VideoReader = SyntheticReader
    pipeline.DetectionNode = SyntheticDetector
    pipeline.FlightGeoReferenceNode = SyntheticReference
    config = OmegaConf.load("/native/app/configs/app_config.yaml")
    if os.environ.get("VERIFY_NO_KAFKA") == "1":
        config.pipeline.send_info_kafka = False
    config.pipeline.egress_enabled = True
    config.history_sampling.enabled = True
    config.pipeline.show_in_web = True
    config.pipeline.save_video = False
    config.video_saver_node.save_conflict_clips = False
    config.show_node.imshow = False
    config.telemetry.enabled = False
    config.hydra.run.dir = "/tmp"
    pipeline.main.__wrapped__(config)
