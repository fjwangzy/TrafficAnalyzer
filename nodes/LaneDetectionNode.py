"""LaneDetectionNode — 使用 YOLO 分割模型检测车道标线/路面区域。

当无人工标注车道数据 (lane_polygons) 时，使用 weights/lane_detect.pt
YOLO 分割模型从图像中检测车道标线和路面区域，生成稳定的车道多边形，
供下游 LaneAnalysisNode 进行车辆分配和指标统计。

与 AutoLaneInferenceNode（基于轨迹聚类）相比，模型检测的车道基于
图像视觉特征，位置固定不随车流变化，统计更稳定可靠。

管道位置: SpeedEstimationNode → **LaneDetectionNode** → LaneAnalysisNode
优先级: 人工标注 (manual) > 模型检测 (model) > 轨迹推断 (auto)

依赖字段:
    读取: frame, lane_polygons (检查是否有人工标注)
    写入: lane_polygons, detected_lane_polygons, lane_source
"""

import logging
import time as _time

import cv2
import numpy as np
import torch
from shapely.geometry import Polygon
from ultralytics import YOLO

from elements.FrameElement import FrameElement
from elements.VideoEndBreakElement import VideoEndBreakElement
from utils_local.utils import profile_time

logger = logging.getLogger(__name__)


class LaneDetectionNode:
    """使用 YOLO 分割模型从图像中检测车道，生成稳定车道多边形。

    工作模式：
    - first_frame_only=True（默认）: 仅在首帧运行模型，后续帧复用结果。
      适合固定摄像头场景，车道位置不变，最大化性能。
    - first_frame_only=False: 每 detect_interval 帧运行一次。
      适合无人机/移动摄像头场景，车道位置可能随视角变化。

    车道区域生成策略：
    - pavement 类 (路面区域): 直接使用分割 mask 作为车道多边形
    - lane 类 (车道标线): 对 mask 做形态学膨胀，扩展为车道区域
    - 膨胀核大小由 buffer_pixels 配置（默认 50px）
    """

    def __init__(self, config: dict) -> None:
        cfg = config.get("lane_detection", {})
        self.enabled = cfg.get("enabled", True)
        self.model_path = cfg.get("model_path", "weights/lane_detect.pt")
        self.confidence = cfg.get("confidence", 0.25)
        self.iou = cfg.get("iou", 0.7)
        self.imgsz = cfg.get("imgsz", 640)
        self.buffer_pixels = cfg.get("buffer_pixels", 50)
        self.detect_interval = cfg.get("detect_interval", 300)
        self.first_frame_only = cfg.get("first_frame_only", True)
        self.min_polygon_area = cfg.get("min_polygon_area", 200)
        self.max_polygon_points = cfg.get("max_polygon_points", 40)

        if not self.enabled:
            return

        # 设备选择: auto → 自动检测 (cuda > mps > cpu)
        device_cfg = cfg.get("device", "auto")
        if device_cfg == "auto":
            if torch.cuda.is_available():
                device = "cuda"
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                device = "mps"
            else:
                device = "cpu"
        else:
            device = device_cfg
        self.device = device

        # 加载 YOLO 分割模型
        self.model = YOLO(self.model_path, task="segment")
        self.names = self.model.names  # {0: 'lane', 1: 'pavement'}
        logger.info(
            f"LaneDetectionNode: model={self.model_path} device={device} "
            f"classes={self.names}"
        )

        # 类别 ID 查找
        self.lane_cls_id = None
        self.pavement_cls_id = None
        for cid, name in self.names.items():
            if name == "lane":
                self.lane_cls_id = cid
            elif name == "pavement":
                self.pavement_cls_id = cid

        # 状态
        self._detected_polygons: dict | None = None
        self._frame_counter: int = 0
        self._inference_ms: float = 0.0
        self._debug_save_mask: bool = True  # 首帧保存调试图像

    @profile_time
    def process(self, frame_element: FrameElement) -> FrameElement:
        if isinstance(frame_element, VideoEndBreakElement):
            return frame_element

        if not self.enabled:
            return frame_element

        # 优先级1: 有人工标注 → 跳过模型检测，标记来源
        if getattr(frame_element, "lane_polygons", None):
            frame_element.lane_source = "manual"
            return frame_element

        # 优先级2: 已有模型检测结果（首帧模式 或 未到检测间隔）
        if self._detected_polygons is not None:
            if self.first_frame_only:
                frame_element.lane_polygons = self._detected_polygons
                frame_element.detected_lane_polygons = self._detected_polygons
                frame_element.lane_source = "model"
                return frame_element

            # 周期检测模式: 检查是否到达检测间隔
            self._frame_counter += 1
            if self._frame_counter % self.detect_interval != 0:
                frame_element.lane_polygons = self._detected_polygons
                frame_element.detected_lane_polygons = self._detected_polygons
                frame_element.lane_source = "model"
                return frame_element

        # 运行模型推理
        polygons = self._detect_lanes(frame_element.frame)
        frame_element.inference_ms = (
            getattr(frame_element, "inference_ms", 0) + self._inference_ms
        )

        if polygons:
            self._detected_polygons = polygons
            frame_element.lane_polygons = polygons
            frame_element.detected_lane_polygons = polygons
            frame_element.lane_source = "model"
            logger.info(
                f"LaneDetectionNode: detected {len(polygons)} lane polygons "
                f"(inference={self._inference_ms:.1f}ms)"
            )
        else:
            # 模型未检测到任何车道 → 回退到自动推断
            frame_element.lane_source = None
            logger.info("LaneDetectionNode: no lane polygons detected, fallback to auto")

        return frame_element

    def _detect_lanes(self, frame: np.ndarray) -> dict:
        """运行 YOLO 分割模型，提取车道多边形。

        优先使用 pavement 类（路面区域），若无则使用 lane 类（车道标线）
        并做形态学膨胀扩展为车道区域。

        Returns:
            {lane_id: shapely.Polygon} 或空字典
        """
        t0 = _time.time()

        results = self.model.predict(
            frame,
            imgsz=self.imgsz,
            conf=self.confidence,
            iou=self.iou,
            device=self.device,
            verbose=False,
        )

        self._inference_ms = round((_time.time() - t0) * 1000, 1)

        result = results[0]
        masks = result.masks
        if masks is None or masks.data is None:
            # 详细诊断: 输出模型原始输出信息
            n_boxes = len(result.boxes) if result.boxes is not None else 0
            logger.debug(
                f"LaneDetectionNode: model returned no masks "
                f"(boxes={n_boxes}, conf_threshold={self.confidence}, "
                f"imgsz={self.imgsz}, device={self.device})"
            )
            # 调试: 即使无 mask 也保存原帧，方便确认视频内容
            if getattr(self, "_debug_save_mask", True):
                self._debug_save_mask = False
                import os
                os.makedirs("logs", exist_ok=True)
                cv2.imwrite("logs/lane_detection_debug.png", frame)
                logger.info("LaneDetectionNode: saved raw frame (no masks) to logs/lane_detection_debug.png")
            return {}

        h_orig, w_orig = frame.shape[:2]
        mask_data = masks.data.cpu().numpy()
        cls_ids = result.boxes.cls.cpu().int().tolist()
        confs = result.boxes.conf.cpu().tolist()

        logger.debug(
            f"LaneDetectionNode: raw model output — "
            f"masks={len(mask_data)}, classes={cls_ids}, "
            f"confs={[round(c, 3) for c in confs]}, "
            f"frame_size={w_orig}x{h_orig}"
        )

        # 调试: 保存模型分割结果可视化图像
        if getattr(self, "_debug_save_mask", True):
            self._debug_save_mask = False  # 仅首帧保存
            self._save_debug_visual(frame, mask_data, cls_ids, confs, h_orig, w_orig)

        # 按类别分组 mask
        pavement_polygons = []
        lane_marking_masks = []

        for i in range(len(mask_data)):
            cls_id = cls_ids[i]
            single_mask = (mask_data[i] > 0.5).astype(np.uint8)

            # 将 mask 从推理尺寸缩放回原始帧尺寸
            if single_mask.shape != (h_orig, w_orig):
                single_mask = cv2.resize(
                    single_mask, (w_orig, h_orig), interpolation=cv2.INTER_NEAREST
                )

            if cls_id == self.pavement_cls_id:
                # pavement 类: 直接提取多边形
                poly = self._mask_to_polygon(single_mask, h_orig, w_orig)
                if poly is not None:
                    pavement_polygons.append(poly)
            elif cls_id == self.lane_cls_id:
                # lane 类: 收集标线 mask，稍后合并膨胀
                lane_marking_masks.append(single_mask)

        # 策略选择:
        # 1. 有 pavement → 使用 pavement 多边形作为车道区域
        # 2. 仅有 lane markings → 合并所有标线 mask，做形态学膨胀生成车道区域
        polygons = {}
        lane_id = 0

        if pavement_polygons:
            for poly in pavement_polygons:
                lane_id += 1
                polygons[f"lane_{lane_id}"] = poly
            logger.debug(
                f"LaneDetectionNode: using {len(pavement_polygons)} pavement polygons"
            )
        elif lane_marking_masks:
            # 合并所有车道标线 mask
            combined_mask = np.zeros((h_orig, w_orig), dtype=np.uint8)
            for m in lane_marking_masks:
                combined_mask = cv2.bitwise_or(combined_mask, m)

            # 形态学膨胀: 将细线扩展为车道区域
            buffer_px = self.buffer_pixels
            kernel_size = buffer_px * 2 + 1
            kernel = cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE, (kernel_size, kernel_size)
            )
            expanded_mask = cv2.dilate(combined_mask, kernel, iterations=1)

            # 从膨胀后的 mask 提取多边形
            expanded_polys = self._mask_to_polygons(expanded_mask, h_orig, w_orig)
            for poly in expanded_polys:
                lane_id += 1
                polygons[f"lane_{lane_id}"] = poly
            logger.debug(
                f"LaneDetectionNode: expanded {len(lane_marking_masks)} lane markings "
                f"→ {len(expanded_polys)} lane regions (buffer={buffer_px}px)"
            )

        return polygons

    def _mask_to_polygon(
        self, mask: np.ndarray, h: int, w: int
    ) -> Polygon | None:
        """将二值 mask 转换为单个 Shapely Polygon（取最大轮廓）。

        Args:
            mask: (H, W) uint8 二值 mask (0/1)
            h, w: 原始帧尺寸

        Returns:
            Shapely Polygon 或 None
        """
        mask_uint8 = (mask * 255).astype(np.uint8) if mask.max() <= 1 else mask
        contours, _ = cv2.findContours(
            mask_uint8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        if not contours:
            return None

        # 取面积最大的轮廓
        largest = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(largest)
        if area < self.min_polygon_area:
            return None

        return self._contour_to_polygon(largest)

    def _mask_to_polygons(
        self, mask: np.ndarray, h: int, w: int
    ) -> list[Polygon]:
        """将二值 mask 转换为多个 Shapely Polygon。

        提取所有轮廓，过滤面积过小的，转为多边形列表。

        Args:
            mask: (H, W) uint8 二值 mask
            h, w: 原始帧尺寸

        Returns:
            Shapely Polygon 列表
        """
        mask_uint8 = (mask * 255).astype(np.uint8) if mask.max() <= 1 else mask
        contours, _ = cv2.findContours(
            mask_uint8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        if not contours:
            return []

        polygons = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < self.min_polygon_area:
                continue

            poly = self._contour_to_polygon(contour)
            if poly is not None:
                polygons.append(poly)

        # 按面积降序排列（大车道优先）
        polygons.sort(key=lambda p: p.area, reverse=True)
        return polygons

    def _contour_to_polygon(self, contour: np.ndarray) -> Polygon | None:
        """将 OpenCV 轮廓转换为简化的 Shapely Polygon。

        使用 Douglas-Peucker 算法简化轮廓点，保留形状特征。
        如果简化后点数仍过多，使用凸包。

        Args:
            contour: OpenCV 轮廓 (N, 1, 2)

        Returns:
            Shapely Polygon 或 None
        """
        # Douglas-Peucker 简化
        epsilon = 0.02 * cv2.arcLength(contour, True)
        simplified = cv2.approxPolyDP(contour, epsilon, True)
        points = simplified.reshape(-1, 2)

        # 点数过多时使用凸包
        if len(points) > self.max_polygon_points:
            hull = cv2.convexHull(contour)
            points = hull.reshape(-1, 2)

        if len(points) < 3:
            return None

        poly = Polygon(points)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_empty or not isinstance(poly, Polygon):
            return None

        return poly

    def _save_debug_visual(
        self, frame: np.ndarray, mask_data: np.ndarray,
        cls_ids: list, confs: list, h: int, w: int
    ) -> None:
        """保存模型分割结果可视化图像，用于调试。

        输出到 logs/lane_detection_debug.png，叠加半透明 mask 和类别标注。
        """
        import os
        os.makedirs("logs", exist_ok=True)

        # 创建彩色叠加层
        overlay = frame.copy()
        colors = {0: (0, 255, 0), 1: (255, 128, 0)}  # lane=绿, pavement=橙

        for i in range(len(mask_data)):
            cls_id = cls_ids[i]
            conf = confs[i]
            color = colors.get(cls_id, (128, 128, 128))
            label = self.names.get(cls_id, f"cls_{cls_id}")

            # 将 mask 缩放到原始帧尺寸
            single_mask = (mask_data[i] > 0.5).astype(np.uint8)
            if single_mask.shape != (h, w):
                single_mask = cv2.resize(
                    single_mask, (w, h), interpolation=cv2.INTER_NEAREST
                )

            # 绘制半透明 mask
            mask_3ch = np.stack([single_mask] * 3, axis=-1)
            overlay = np.where(
                mask_3ch > 0,
                (overlay * 0.5 + np.array(color) * 0.5).astype(np.uint8),
                overlay
            )

            # 在 mask 中心标注类别和置信度
            ys, xs = np.where(single_mask > 0)
            if len(xs) > 0 and len(ys) > 0:
                cx, cy = int(xs.mean()), int(ys.mean())
                cv2.putText(
                    overlay, f"{label}:{conf:.2f}", (cx, cy),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.5, color, 3
                )

        out_path = "logs/lane_detection_debug.png"
        cv2.imwrite(out_path, overlay)
        logger.info(f"LaneDetectionNode: debug visualization saved to {out_path}")
