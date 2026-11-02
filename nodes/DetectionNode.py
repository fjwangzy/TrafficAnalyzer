from __future__ import annotations

import hashlib
import logging
import os
from types import SimpleNamespace
import time
from pathlib import Path

import torch
from ultralytics import YOLO

from elements.FrameElement import FrameElement
from elements.VideoEndBreakElement import VideoEndBreakElement
from utils_local.detection_geometry import (
    configure_safe_mps_box_clipping,
    extract_valid_detections,
)
from utils_local.adaptive_imgsz import AdaptiveImageSizePolicy
from utils_local.utils import profile_time

logger = logging.getLogger(__name__)


def build_yolo_model_id(weight_path: str | Path) -> str:
    """Return the immutable model identity stored with every produced track."""
    path = Path(weight_path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return f"{path.name}@{digest.hexdigest()[:12]}"


class DetectionNode:
    """YOLO-only inference boundary.

    Association intentionally happens in process 2 after FlightGeoReferenceNode,
    where the tracker can compensate camera motion and enforce source-time gates.
    """

    def __init__(self, config: dict) -> None:
        cfg = config["detection_node"]
        requested = cfg.get("device", "auto")
        self.ascend = requested == "ascend"
        if self.ascend:
            device = SimpleNamespace(type="ascend")
        elif requested == "auto":
            if torch.cuda.is_available():
                device = torch.device("cuda")
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                device = torch.device("mps")
            else:
                device = torch.device("cpu")
        else:
            device = torch.device(requested)
        self.device = device
        logger.info("DETECTOR_DEVICE device=%s", device.type)

        weight_path = cfg["weight_pth"]
        if self.ascend:
            from utils_local.ascend_detector import AscendDetector, sha256
            manifest_path = os.environ.get("ASCEND_MODEL_MANIFEST", "")
            if not manifest_path:
                raise ValueError("ASCEND_MODEL_MANIFEST is required for Ascend")
            source_hash = sha256(weight_path)
            self.model = AscendDetector(manifest_path, int(os.environ.get("ASCEND_DEVICE_ID", "0")))
            if source_hash != self.model.manifest["source_sha256"]:
                self.model.close()
                raise ValueError("Ascend model does not match the configured source weights")
            self.safe_mps_box_clipping = False
        else:
            self.model = YOLO(weight_path, task="detect")
            self.safe_mps_box_clipping = configure_safe_mps_box_clipping(self.device)
        self.yolo_model_id = build_yolo_model_id(weight_path)
        self.classes = self.model.names
        self.conf = cfg["confidence"]
        self.iou = cfg["iou"]
        self.imgsz = cfg["imgsz"]
        self.imgsz_policy = AdaptiveImageSizePolicy(
            cfg.get("adaptive_imgsz"),
            fallback_imgsz=self.imgsz,
        )
        self.half = bool(cfg.get("half", False)) and self.device.type in {"mps", "cuda"}
        self.classes_to_detect = cfg["classes_to_detect"]

    @profile_time
    def process(self, frame_element: FrameElement) -> FrameElement:
        if isinstance(frame_element, VideoEndBreakElement):
            if getattr(self, "ascend", False):
                self.model.close()
            return frame_element
        assert isinstance(frame_element, FrameElement), (
            f"DetectionNode | 输入元素格式错误 {type(frame_element)}"
        )

        policy = getattr(self, "imgsz_policy", None)
        if policy is not None:
            size_decision = policy.select(
                frame_element.telemetry,
                source_timestamp_sec=float(frame_element.timestamp),
            )
            effective_imgsz = size_decision.imgsz
            adaptive_diagnostics = size_decision.diagnostics
        else:
            effective_imgsz = self.imgsz
            adaptive_diagnostics = {
                "enabled": False,
                "effective_imgsz": self.imgsz,
                "tier": "fixed",
                "status": "disabled",
                "switch_reason": "configured_fallback",
                "switch_count": 0,
            }

        started_at = time.time()
        outputs = self.model.predict(
            frame_element.frame,
            imgsz=effective_imgsz,
            conf=self.conf,
            verbose=False,
            iou=self.iou,
            classes=self.classes_to_detect,
            device=self.device,
            half=self.half,
            agnostic_nms=False,
        )
        frame_element.inference_ms = round((time.time() - started_at) * 1000, 1)
        detections = extract_valid_detections(
            outputs[0].boxes,
            class_names=self.classes,
            frame_shape=frame_element.frame.shape,
        )
        frame_element.detected_conf = detections.confidences
        frame_element.detected_cls_ids = detections.class_ids
        frame_element.detected_cls = detections.class_names
        frame_element.detected_xyxy = detections.xyxy
        frame_element.detection_diagnostics = {
            **detections.diagnostics,
            "safe_mps_box_clipping": self.safe_mps_box_clipping,
            "adaptive_imgsz": adaptive_diagnostics,
        }
        frame_element.yolo_model_id = self.yolo_model_id
        frame_element.inference_context = {
            "metric_scope": "yolo_predict_single_processed_frame",
            "device": "ascend" if getattr(self, "ascend", False) else str(self.device),
            "precision": "fp16" if self.half else "fp32",
            "model": self.yolo_model_id,
            "effective_imgsz": effective_imgsz,
            "agl_tier": adaptive_diagnostics["tier"],
        }
        return frame_element

    def close(self):
        if getattr(self, "ascend", False):
            self.model.close()
