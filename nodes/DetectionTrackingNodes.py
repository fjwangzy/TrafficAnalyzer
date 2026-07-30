from ultralytics import YOLO
import torch
import numpy as np
import time
import hashlib
from pathlib import Path

from utils_local.utils import profile_time
from elements.FrameElement import FrameElement
from elements.VideoEndBreakElement import VideoEndBreakElement
from byte_tracker.byte_tracker_model import BYTETracker as ByteTracker
from utils_local.detection_geometry import (
    configure_safe_mps_box_clipping,
    extract_valid_detections,
)
from utils_local.adaptive_imgsz import AdaptiveImageSizePolicy


def build_yolo_model_id(weight_path: str | Path) -> str:
    """Return the immutable model identity stored with every produced track."""
    path = Path(weight_path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return f"{path.name}@{digest.hexdigest()[:12]}"


class DetectionTrackingNodes:
    """检测模型推理+跟踪算法模块"""

    def __init__(self, config) -> None:
        config_yolo = config["detection_node"]

        # 设备选择: auto → 自动检测 (cuda>mps>cpu) | 也可通过config显式指定
        device_cfg = config_yolo.get("device", "auto")
        if device_cfg == "auto":
            if torch.cuda.is_available():
                device = torch.device("cuda")
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                device = torch.device("mps")
            else:
                device = torch.device("cpu")
        else:
            device = torch.device(device_cfg)
        self.device = device
        print(f'检测将在 {device} 上进行')

        weight_path = config_yolo["weight_pth"]
        self.model = YOLO(weight_path, task='detect')
        self.safe_mps_box_clipping = configure_safe_mps_box_clipping(self.device)
        self.yolo_model_id = build_yolo_model_id(weight_path)
        self.classes = self.model.names
        self.conf = config_yolo["confidence"]
        self.iou = config_yolo["iou"]
        self.imgsz = config_yolo["imgsz"]
        self.imgsz_policy = AdaptiveImageSizePolicy(
            config_yolo.get("adaptive_imgsz"),
            fallback_imgsz=self.imgsz,
        )
        self.half = bool(config_yolo.get("half", False)) and self.device.type in {"mps", "cuda"}
        self.classes_to_detect = config_yolo["classes_to_detect"]

        config_bytetrack= config["tracking_node"]

        # ByteTrack 参数
        first_track_thresh = config_bytetrack["first_track_thresh"]
        second_track_thresh = config_bytetrack["second_track_thresh"]
        match_thresh = config_bytetrack["match_thresh"]
        track_buffer = config_bytetrack["track_buffer"]
        fps = 30  # 设置为30，以便track_buffer以帧为单位
        self.tracker = ByteTracker(
            fps, first_track_thresh, second_track_thresh, match_thresh, track_buffer, 1
        )

    @profile_time
    def process(self, frame_element: FrameElement) -> FrameElement:
        # 如果输入是VideoEndBreakElement而不是FrameElement，则退出处理
        if isinstance(frame_element, VideoEndBreakElement):
            return frame_element
        assert isinstance(
            frame_element, FrameElement
        ), f"DetectionTrackingNodes | 输入元素格式错误 {type(frame_element)}"

        # 去掉不必要的 copy，因为检测过程只读
        frame = frame_element.frame

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

        t_detect_start = time.time()
        outputs = self.model.predict(frame, imgsz=effective_imgsz, conf=self.conf, verbose=False,
                                     iou=self.iou, classes=self.classes_to_detect,
                                     device=self.device, half=self.half)
        t_detect_end = time.time()

        # 记录推理耗时（毫秒），供Kafka发送到前端展示
        frame_element.inference_ms = round((t_detect_end - t_detect_start) * 1000, 1)

        detections = extract_valid_detections(
            outputs[0].boxes,
            class_names=self.classes,
            frame_shape=frame.shape,
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

        # 准备输入到跟踪器的数据
        detections_list = np.asarray(
            [
                [*box, confidence, class_id]
                for box, confidence, class_id in zip(
                    detections.xyxy,
                    detections.confidences,
                    detections.class_ids,
                    strict=True,
                )
            ],
            dtype=np.float32,
        ).reshape((-1, 6))

        # 如果没有检测结果，则发送空数组
        if len(detections_list) == 0:
            detections_list = np.empty((0, 6))

        track_list = self.tracker.update(torch.tensor(detections_list), xyxy=True)

        # 获取id列表
        frame_element.id_list = [int(t.track_id) for t in track_list]

        # 获取box列表
        frame_element.tracked_xyxy = [list(t.tlbr.astype(int)) for t in track_list]

        # 获取物体类名称
        frame_element.tracked_cls = [self.classes[int(t.class_name)] for t in track_list]

        # 获取YOLO原始检测类别ID（保留原始class_id，用于motor/non_motor分类）
        frame_element.tracked_cls_ids = [int(t.class_name) for t in track_list]

        # 获取置信度分数
        frame_element.tracked_conf = [t.score for t in track_list]
        frame_element.yolo_model_id = self.yolo_model_id
        frame_element.inference_context = {
            "metric_scope": "yolo_predict_single_processed_frame",
            "device": str(self.device),
            "precision": "fp16" if self.half else "fp32",
            "model": self.yolo_model_id,
            "effective_imgsz": effective_imgsz,
            "agl_tier": adaptive_diagnostics["tier"],
        }

        return frame_element

    def _get_results_dor_tracker(self, results) -> np.ndarray:
        # 将数据转换为跟踪器所需的正确格式
        detections_list = []
        for result in results[0]:
            class_id = result.boxes.cls.cpu().numpy().astype(int)
            # 跟踪与检测相同的类
            if class_id[0] in self.classes_to_detect:

                bbox = result.boxes.xyxy.cpu().numpy()
                confidence = result.boxes.conf.cpu().numpy()

                # 保留YOLO原始class_id，用于下游motor/non_motor分类
                # ByteTrack内部仍将所有目标视为同一类进行IoU匹配
                class_id_value = class_id[0]

                merged_detection = [
                    bbox[0][0],
                    bbox[0][1],
                    bbox[0][2],
                    bbox[0][3],
                    confidence[0],
                    class_id_value,
                ]

                detections_list.append(merged_detection)

        return np.array(detections_list)
