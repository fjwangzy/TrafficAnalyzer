from ultralytics import YOLO
import torch
import numpy as np
import time

from utils_local.utils import profile_time
from elements.FrameElement import FrameElement
from elements.VideoEndBreakElement import VideoEndBreakElement
from byte_tracker.byte_tracker_model import BYTETracker as ByteTracker


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

        self.model = YOLO(config_yolo["weight_pth"], task='detect')
        self.classes = self.model.names
        self.conf = config_yolo["confidence"]
        self.iou = config_yolo["iou"]
        self.imgsz = config_yolo["imgsz"]
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

        frame = frame_element.frame.copy()

        t_detect_start = time.time()
        outputs = self.model.predict(frame, imgsz=self.imgsz, conf=self.conf, verbose=False,
                                     iou=self.iou, classes=self.classes_to_detect,
                                     device=self.device)
        t_detect_end = time.time()

        # 记录推理耗时（毫秒），供Kafka发送到前端展示
        frame_element.inference_ms = round((t_detect_end - t_detect_start) * 1000, 1)

        frame_element.detected_conf = outputs[0].boxes.conf.cpu().tolist()
        detected_cls = outputs[0].boxes.cls.cpu().int().tolist()
        frame_element.detected_cls = [self.classes[i] for i in detected_cls]
        frame_element.detected_xyxy = outputs[0].boxes.xyxy.cpu().int().tolist()

        # 准备输入到跟踪器的数据
        detections_list = self._get_results_dor_tracker(outputs)

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