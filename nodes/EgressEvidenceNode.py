"""Image-owner evidence stage: save exact pixels and hand off descriptors only."""

import os
from elements.VideoEndBreakElement import VideoEndBreakElement
from services.PipelineEgress import annotation_snapshot
from utils_local.event_evidence import (
    save_conflict_evidence_files,
    save_event_evidence_files,
)


class EgressEvidenceNode:
    def __init__(self, config, client):
        self.config = config
        self.client = client
        self.enabled = bool(config["pipeline"]["send_info_kafka"])
        self.root = os.environ.get("SURVEY_STORAGE_DIR", ".runtime/survey")
        self.quality = int(
            config.get("video_saver_node", {}).get("conflict_jpeg_quality", 95)
        )

    def capture_annotation(self, frame):
        if self.enabled and getattr(frame, "annotation_snapshot_requested", False):
            frame.annotation_snapshot = annotation_snapshot(
                frame, self.config, self.root
            )

    def process(self, frame, original_frame=None):
        if isinstance(frame, VideoEndBreakElement):
            self.client.send("eof", frame)
            self.client.wait()
            return frame
        if original_frame is not None:
            frame.frame = original_frame
        result = {
            "frame_seq": frame.egress_frame_seq,
            "ok": True,
            "tcc": [],
            "enforcement": [],
            "annotation": frame.annotation_snapshot,
        }
        try:
            if self.enabled and getattr(frame, "conflict_events", None):
                result["tcc"] = save_conflict_evidence_files(
                    frame,
                    storage_root=self.root,
                    max_width=None,
                    jpeg_quality=self.quality,
                )
                result["ok"] = result["ok"] and len(result["tcc"]) == 2
            if self.enabled and getattr(frame, "enforcement_clues", None):
                result["enforcement"] = save_event_evidence_files(
                    frame,
                    ("enforcement_original_frame", "enforcement_detector_frame"),
                    storage_root=self.root,
                    jpeg_quality=self.quality,
                )
                result["ok"] = result["ok"] and len(result["enforcement"]) == 2
        except (OSError, ValueError) as error:
            result.update(ok=False, error=type(error).__name__)
        self.client.send("render", result)
        return frame
