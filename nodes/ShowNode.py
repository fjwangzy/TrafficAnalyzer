import cv2
import numpy as np
import supervision as sv

from utils_local.utils import profile_time, FPS_Counter
from elements.VideoEndBreakElement import VideoEndBreakElement
from elements.FrameElement import FrameElement


class ShowNode:
    """负责结果可视化的模块 — 使用 supervision 库优化展示效果"""

    def __init__(self, config) -> None:
        data_colors = config["general"]["colors_of_roads"]
        self.colors_roads = {int(key): tuple(value) for key, value in data_colors.items()}
        self.buffer_analytics_sec = (
            config["general"]["buffer_analytics"] * 60 + config["general"]["min_time_life_track"]
        )  # 缓冲区填充所需的时间，此时显示统计信息还为时过早

        config_show_node = config["show_node"]
        self.scale = config_show_node["scale"]
        self.fps_counter_N_frames_stat = config_show_node["fps_counter_N_frames_stat"]
        self.default_fps_counter = FPS_Counter(self.fps_counter_N_frames_stat)
        self.draw_fps_info = config_show_node["draw_fps_info"]
        self.show_roi = config_show_node["show_roi"]
        self.overlay_transparent_mask = config_show_node["overlay_transparent_mask"]
        self.imshow = config_show_node["imshow"]
        self.show_only_yolo_detections = config_show_node["show_only_yolo_detections"]
        self.show_track_id_different_colors = config_show_node["show_track_id_different_colors"]
        self.show_info_statistics = config_show_node["show_info_statistics"]

        self.show_number_of_road = True  # 显示道路编号

        # 交通态势可视化选项
        self.show_speed_labels = True  # 显示车速标签
        self.show_direction_stats = True  # 显示方向流量统计
        self.show_lane_polygons = True  # 显示车道多边形（有标注时）
        self.show_trace_trails = config_show_node.get("show_trace_trails", True)  # 显示轨迹尾迹

        # 方向流量颜色映射
        self.direction_colors = {
            "straight": (0, 255, 0),    # 绿色
            "left_turn": (255, 165, 0),  # 橙色
            "right_turn": (0, 165, 255), # 橙蓝
            "u_turn": (128, 0, 128),     # 紫色
            "unknown": (128, 128, 128),  # 灰色
        }

        # 字体参数：
        self.fontFace = 1
        self.fontScale = 2.0
        self.thickness = 2

        # 多边形和边界框参数：
        self.thickness_lines = 3

        # 统计屏幕参数：
        self.width_window = 700  # 屏幕宽度（像素）

        # ── supervision 标注器 ──────────────────────────────────────────────
        # 跟踪目标的圆角边框
        self.sv_box_annotator = sv.RoundBoxAnnotator(
            thickness=3,
            roundness=0.1,
        )
        # 跟踪标签（带圆角背景）
        self.sv_label_annotator = sv.LabelAnnotator(
            text_position=sv.Position.TOP_CENTER,
            text_scale=0.8,
            text_thickness=2,
            text_padding=8,
            border_radius=6,
        )
        # 轨迹尾迹标注器
        self.sv_trace_annotator = sv.TraceAnnotator(
            thickness=2,
            trace_length=30,
        )
        # 仅检测模式的标准边框
        self.sv_det_box_annotator = sv.BoxAnnotator(thickness=2)
        self.sv_det_label_annotator = sv.LabelAnnotator(
            text_position=sv.Position.TOP_CENTER,
            text_scale=0.7,
            text_thickness=1,
            text_padding=5,
            border_radius=4,
        )
        # 道路半透明遮罩标注器
        self.sv_road_mask_annotator = sv.MaskAnnotator(opacity=0.3)

        # ── 道路颜色 Palette（BGR→RGB，供 supervision 使用）───────────────
        road_hex_colors = []
        self.road_id_to_palette_idx = {}
        for idx, (road_id, bgr) in enumerate(sorted(self.colors_roads.items())):
            b, g, r = bgr
            road_hex_colors.append(sv.Color(r=r, g=g, b=b).as_hex())
            self.road_id_to_palette_idx[int(road_id)] = idx
        self.road_palette = (
            sv.ColorPalette.from_hex(road_hex_colors)
            if road_hex_colors
            else sv.ColorPalette.DEFAULT
        )

    # ── supervision 辅助方法 ───────────────────────────────────────────────

    @staticmethod
    def _build_detections(xyxy, cls_names=None, tracker_ids=None):
        """从列表构建 sv.Detections 对象。"""
        if not xyxy or len(xyxy) == 0:
            return None
        xyxy_arr = np.array(xyxy, dtype=np.float32)
        class_id = np.arange(len(xyxy), dtype=int) if cls_names else None
        conf = np.ones(len(xyxy), dtype=np.float32)
        tracker_id = np.array(tracker_ids, dtype=int) if tracker_ids else None
        data = {}
        if cls_names:
            data["class_name"] = np.array(cls_names, dtype=object)
        return sv.Detections(
            xyxy=xyxy_arr,
            confidence=conf,
            class_id=class_id,
            tracker_id=tracker_id,
            data=data,
        )

    def _configure_tracking_colors(self, detections, frame_element):
        """配置跟踪着色的 palette 和 color_lookup。

        Returns:
            (palette, color_lookup) — 供 annotator.annotate() 前设置
        """
        if self.show_track_id_different_colors:
            # 使用默认 21 色调色板，按 tracker_id 自动循环着色
            return sv.ColorPalette.DEFAULT, sv.ColorLookup.TRACK
        else:
            # 按道路颜色着色：构建 color_idx 数组映射到 road_palette
            n = len(detections)
            color_idx = np.zeros(n, dtype=int)
            buffer_tracks = frame_element.buffer_tracks or {}
            for i in range(n):
                tid = int(detections.tracker_id[i])
                track = buffer_tracks.get(tid)
                if track and track.start_road is not None:
                    road_id = int(track.start_road)
                    color_idx[i] = self.road_id_to_palette_idx.get(road_id, 0)
            return self.road_palette, color_idx

    def _make_labels(self, frame_element):
        """生成每个跟踪目标的标签字符串列表。"""
        labels = []
        buffer_tracks = frame_element.buffer_tracks or {}
        for tid, cls_name in zip(frame_element.id_list, frame_element.tracked_cls):
            label = f"#{tid} {cls_name}"
            # 叠加车速标签（km/h）
            if self.show_speed_labels and buffer_tracks:
                track = buffer_tracks.get(int(tid))
                if track and track.avg_speed_kmh > 0:
                    label += f" {track.avg_speed_kmh:.0f}km/h"
            labels.append(label)
        return labels

    def _draw_road_number(self, frame_result, road_id, points):
        """在多边形中心绘制带圆底的道路编号。"""
        moments = cv2.moments(points)
        if moments["m00"] == 0:
            return
        cx = int(moments["m10"] / moments["m00"])
        cy = int(moments["m01"] / moments["m00"])

        text = str(road_id)
        (label_width, label_height), _ = cv2.getTextSize(
            text,
            fontFace=self.fontFace,
            fontScale=self.fontScale * 1.3,
            thickness=self.thickness,
        )
        circle_radius = max(label_width, label_height) // 2
        cv2.circle(frame_result, (cx, cy), circle_radius + 6, (200, 200, 200), -1)
        cv2.putText(
            frame_result,
            text,
            (cx + 2 - label_width // 2, cy + 2 + label_height // 2),
            fontFace=self.fontFace,
            fontScale=self.fontScale * 1.3,
            thickness=self.thickness,
            color=(0, 0, 0),
        )

    # ── 主处理方法 ──────────────────────────────────────────────────────────

    @profile_time
    def process(self, frame_element: FrameElement, fps_counter=None) -> FrameElement:
        if isinstance(frame_element, VideoEndBreakElement):
            return frame_element
        assert isinstance(
            frame_element, FrameElement
        ), f"ShowNode | 输入元素格式错误 {type(frame_element)}"

        frame_result = frame_element.frame.copy()

        if self.show_only_yolo_detections:
            frame_result = self._draw_detections(frame_result, frame_element)
        else:
            frame_result = self._draw_tracked(frame_result, frame_element)

        # 绘制道路多边形
        if self.show_roi:
            frame_result = self._draw_roads(frame_result, frame_element)

        # 计算fps并绘制
        if self.draw_fps_info:
            frame_result = self._draw_fps(frame_result, fps_counter)

        # 绘制方向流量统计信息叠加层
        if self.show_direction_stats:
            direction_stats = getattr(frame_element, "direction_stats", None)
            if direction_stats:
                self._draw_direction_overlay(
                    frame_result,
                    direction_stats,
                    getattr(frame_element, "queue_count", 0),
                )

        # 绘制车道多边形（数据驱动：有标注时叠加显示）
        if self.show_lane_polygons:
            lane_polygons = getattr(frame_element, "lane_polygons", None)
            if lane_polygons:
                self._draw_lane_polygons(frame_result, lane_polygons)

        # 处理显示统计信息的单独窗口
        if self.show_info_statistics:
            frame_result = self._draw_stats_panel(frame_result, frame_element)

        frame_element.frame_result = frame_result
        frame_show = cv2.resize(frame_result.copy(), (-1, -1), fx=self.scale, fy=self.scale)

        if self.imshow:
            cv2.imshow(frame_element.source, frame_show)
            cv2.waitKey(1)

        return frame_element

    # ── 绘制子方法 ──────────────────────────────────────────────────────────

    def _draw_detections(self, frame, frame_element):
        """使用 supervision 绘制纯检测结果（无跟踪）。"""
        detections = self._build_detections(
            frame_element.detected_xyxy,
            cls_names=frame_element.detected_cls,
        )
        if detections is None:
            return frame

        labels = list(frame_element.detected_cls) if frame_element.detected_cls else None

        frame = self.sv_det_box_annotator.annotate(scene=frame, detections=detections)
        frame = self.sv_det_label_annotator.annotate(
            scene=frame, detections=detections, labels=labels
        )
        return frame

    def _draw_tracked(self, frame, frame_element):
        """使用 supervision 绘制跟踪结果（圆角边框 + 标签 + 轨迹尾迹）。"""
        if not frame_element.tracked_xyxy:
            return frame

        detections = self._build_detections(
            frame_element.tracked_xyxy,
            cls_names=frame_element.tracked_cls,
            tracker_ids=frame_element.id_list,
        )
        if detections is None:
            return frame

        # 构建标签（含车速）
        labels = self._make_labels(frame_element)

        # 配置颜色方案
        palette, color_lookup = self._configure_tracking_colors(detections, frame_element)

        # 动态设置 annotator 的 color / color_lookup
        self.sv_box_annotator.color = palette
        self.sv_box_annotator.color_lookup = color_lookup
        self.sv_label_annotator.color = palette
        self.sv_label_annotator.color_lookup = color_lookup
        self.sv_trace_annotator.color = palette
        self.sv_trace_annotator.color_lookup = color_lookup

        # 圆角边框
        frame = self.sv_box_annotator.annotate(scene=frame, detections=detections)
        # 标签（带背景色，与边框同色）
        frame = self.sv_label_annotator.annotate(
            scene=frame, detections=detections, labels=labels
        )
        # 轨迹尾迹
        if self.show_trace_trails:
            frame = self.sv_trace_annotator.annotate(scene=frame, detections=detections)

        return frame

    def _draw_roads(self, frame, frame_element):
        """绘制道路多边形区域（边框 + 半透明遮罩 + 编号）。"""
        for road_id, points in frame_element.roads_info.items():
            color = self.colors_roads[int(road_id)]
            pts = np.array(points, np.int32).reshape((-1, 1, 2))

            # 道路边框
            cv2.polylines(
                frame, [pts], isClosed=True, color=color, thickness=self.thickness_lines
            )

            # 半透明遮罩（使用 supervision MaskAnnotator）
            if self.overlay_transparent_mask:
                h, w = frame.shape[:2]
                binary_mask = np.zeros((h, w), dtype=np.uint8)
                binary_mask = cv2.fillPoly(binary_mask, pts=[pts], color=1)
                det_mask = binary_mask.astype(bool)[np.newaxis, :, :]  # (1, H, W)

                # OpenCV BGR → supervision RGB Color
                road_b, road_g, road_r = color
                road_sv_color = sv.Color(r=road_r, g=road_g, b=road_b)

                road_detections = sv.Detections(
                    xyxy=np.array([[0, 0, w, h]], dtype=np.float32),
                    mask=det_mask,
                    class_id=np.array([0], dtype=int),
                )

                # 临时设置 mask annotator 颜色
                original_color = self.sv_road_mask_annotator.color
                self.sv_road_mask_annotator.color = road_sv_color
                frame = self.sv_road_mask_annotator.annotate(
                    scene=frame, detections=road_detections
                )
                self.sv_road_mask_annotator.color = original_color

            # 道路编号
            if self.show_number_of_road:
                self._draw_road_number(frame, road_id, pts)

        return frame

    def _draw_fps(self, frame, fps_counter):
        """绘制 FPS 信息。"""
        fps_counter = fps_counter if fps_counter is not None else self.default_fps_counter
        fps_real = fps_counter.calc_FPS()

        text = f"FPS: {fps_real:.1f}"
        (label_width, label_height), _ = cv2.getTextSize(
            text, fontFace=self.fontFace, fontScale=self.fontScale, thickness=self.thickness
        )
        cv2.rectangle(frame, (0, 0), (10 + label_width, 35 + label_height), (0, 0, 0), -1)
        cv2.putText(
            img=frame,
            text=text,
            org=(10, 40),
            fontFace=self.fontFace,
            fontScale=self.fontScale,
            thickness=self.thickness,
            color=(255, 255, 255),
        )
        return frame

    def _draw_stats_panel(self, frame_result, frame_element):
        """绘制右侧统计信息面板。"""
        black_image = np.zeros((frame_result.shape[0], self.width_window, 3), dtype=np.uint8)
        data_info = frame_element.info

        text_cars = f"车辆总数: {data_info['cars_amount']}"
        y = 55
        cv2.putText(
            img=black_image, text=text_cars, org=(20, y),
            fontFace=self.fontFace, fontScale=self.fontScale * 1.5,
            thickness=self.thickness, color=(255, 255, 255),
        )
        y += cv2.getTextSize(
            text_cars, self.fontFace, self.fontScale * 1.5, self.thickness
        )[0][1] + 25

        text_info = "道路拥堵情况:"
        cv2.putText(
            img=black_image, text=text_info, org=(20, y),
            fontFace=self.fontFace, fontScale=self.fontScale * 1.5,
            thickness=self.thickness, color=(255, 255, 255),
        )
        y += cv2.getTextSize(
            text_info, self.fontFace, self.fontScale * 1.5, self.thickness
        )[0][1] + 25

        if frame_element.timestamp >= self.buffer_analytics_sec:
            for key, value in data_info["roads_activity"].items():
                text_road = f"  道路 {key}: {value:.1f} 辆/分钟"
                cv2.putText(
                    img=black_image, text=text_road, org=(20, y),
                    fontFace=self.fontFace, fontScale=self.fontScale * 1.5,
                    thickness=self.thickness, color=(255, 255, 255),
                )
                y += cv2.getTextSize(
                    text_road, self.fontFace, self.fontScale * 1.5, self.thickness
                )[0][1] + 25
        else:
            text_to_show = f"   等待 {round(self.buffer_analytics_sec - frame_element.timestamp)} 秒"
            cv2.putText(
                img=black_image, text=text_to_show, org=(20, y),
                fontFace=self.fontFace, fontScale=self.fontScale * 1.5,
                thickness=self.thickness, color=(255, 255, 255),
            )

        return np.hstack((frame_result, black_image))

    def _overlay_transparent_mask(self, img, points, mask_color=(0, 255, 255), alpha=0.3):
        """保留向后兼容（已被 _draw_roads 中 supervision MaskAnnotator 替代）。"""
        binary_mask = np.zeros((img.shape[0], img.shape[1]), dtype=np.uint8)
        binary_mask = cv2.fillPoly(binary_mask, pts=[points], color=1)
        colored_mask = (binary_mask[:, :, np.newaxis] * mask_color).astype(np.uint8)
        return cv2.addWeighted(img, 1, colored_mask, alpha, 0)

    def _draw_direction_overlay(self, frame_result, direction_stats, queue_count):
        """在画面左上角绘制方向流量统计（FPS下方）。"""
        y_offset = 75
        label_scale = self.fontScale * 0.8
        label_thickness = max(1, self.thickness - 1)

        direction_labels = {
            "straight": "S:", "left_turn": "L:",
            "right_turn": "R:", "u_turn": "U:",
        }

        cv2.rectangle(frame_result, (0, y_offset - 5), (280, y_offset + 25), (0, 0, 0), -1)
        parts = []
        for d, label in direction_labels.items():
            if d in direction_stats:
                count = direction_stats[d].get("count", 0)
                parts.append(f"{label}{count}")
        text = "  ".join(parts) + f"  Q:{queue_count}"
        cv2.putText(
            frame_result, text, (5, y_offset + 15),
            fontFace=self.fontFace, fontScale=label_scale,
            thickness=label_thickness, color=(255, 255, 255),
        )

    def _draw_lane_polygons(self, frame_result, lane_polygons):
        """绘制车道多边形（带 supervision 风格的标签背景）。"""
        lane_color = (0, 200, 200)  # 青色
        for lane_id, poly in lane_polygons.items():
            coords = np.array(poly.exterior.coords, dtype=np.int32)
            coords = coords.reshape((-1, 1, 2))

            cv2.polylines(
                frame_result, [coords], isClosed=True,
                color=lane_color, thickness=2,
            )

            # 车道 ID 标签 — 带半透明背景
            cx = int(np.mean(coords[:, 0, 0]))
            cy = int(np.mean(coords[:, 0, 1]))
            lane_text = str(lane_id)
            (tw, th), _ = cv2.getTextSize(
                lane_text, fontFace=self.fontFace,
                fontScale=self.fontScale * 0.7, thickness=1,
            )
            # 标签背景
            cv2.rectangle(
                frame_result,
                (cx - tw // 2 - 3, cy - th - 5),
                (cx + tw // 2 + 3, cy + 5),
                lane_color, -1,
            )
            cv2.putText(
                frame_result, lane_text, (cx - tw // 2, cy),
                fontFace=self.fontFace, fontScale=self.fontScale * 0.7,
                thickness=1, color=(0, 0, 0),
            )
