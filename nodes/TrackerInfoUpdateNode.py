import logging
import numpy as np

from elements.FrameElement import FrameElement
from elements.TrackElement import TrackElement
from elements.VideoEndBreakElement import VideoEndBreakElement
from utils_local.utils import profile_time, intersects_central_point
from utils_local.homography import pixel_to_world, is_valid_homography
from utils_local.motion_compensation import pixel_to_world_compensated

logger = logging.getLogger("buffer_tracks")

# YOLO类别→车辆分类映射（基于COCO类别ID）
MOTOR_CLASSES = {2, 3, 4, 5, 6, 7, 8, 9}  # car, motorcycle, airplane, bus, train, truck, boat, traffic light
NON_MOTOR_CLASSES = {0, 1}  # person, bicycle


def classify_vehicle(yolo_class_id: int | None) -> str:
    """根据YOLO检测类别ID分类为motor/non_motor/unknown。"""
    if yolo_class_id is None:
        return "unknown"
    if yolo_class_id in MOTOR_CLASSES:
        return "motor"
    if yolo_class_id in NON_MOTOR_CLASSES:
        return "non_motor"
    return "unknown"


class TrackerInfoUpdateNode:
    """活动跟踪更新模块"""

    def __init__(self, config: dict) -> None:
        config_general = config["general"]

        self.size_buffer_analytics = (
            config_general["buffer_analytics"] * 60
        )  # 分析缓冲区中的秒数
        # 添加最小生存时间，以便在计算统计信息时使用的是
        # 最近buffer_analytics分钟内的车辆：
        self.size_buffer_analytics += config_general["min_time_life_track"]
        self.buffer_tracks = {}  # 活动跟踪缓冲区

        # 完成轨迹发射参数
        trajectory_cfg = config.get("trajectory", {})
        self.min_track_duration = trajectory_cfg.get("min_track_duration_sec", 2.0)
        self.min_trajectory_points = 5

    @profile_time
    def process(self, frame_element: FrameElement) -> FrameElement:
        # 如果输入是VideoEndBreakElement而不是FrameElement，则退出处理
        if isinstance(frame_element, VideoEndBreakElement):
            return frame_element
        assert isinstance(
            frame_element, FrameElement
        ), f"TrackerInfoUpdateNode | 输入元素格式错误 {type(frame_element)}"

        id_list = frame_element.id_list
        tracked_cls_ids = getattr(frame_element, "tracked_cls_ids", None)

        for i, id in enumerate(id_list):
            # 更新或创建新跟踪
            if id not in self.buffer_tracks:
                # 创建新键
                self.buffer_tracks[id] = TrackElement(
                    id=id,
                    timestamp_first=frame_element.timestamp,
                )
                # 设置YOLO原始类别和车辆分类
                if tracked_cls_ids and i < len(tracked_cls_ids):
                    self.buffer_tracks[id].yolo_class_id = tracked_cls_ids[i]
                    self.buffer_tracks[id].vehicle_class = classify_vehicle(tracked_cls_ids[i])
            else:
                # 更新最后检测时间
                self.buffer_tracks[id].update(frame_element.timestamp)

            # 累积轨迹点（bbox中心像素坐标）
            bbox = frame_element.tracked_xyxy[i]
            cx = (bbox[0] + bbox[2]) / 2.0
            cy = (bbox[1] + bbox[3]) / 2.0
            self.buffer_tracks[id].trajectory_points.append((cx, cy))

            # 累积position_history（含时间戳，供SpeedEstimationNode和DirectionFlowNode使用）
            self.buffer_tracks[id].position_history.append((cx, cy, frame_element.timestamp))
            # 限制position_history大小（SpeedEstimationNode会进一步裁剪到history_frames）
            if len(self.buffer_tracks[id].position_history) > 30:
                self.buffer_tracks[id].position_history = self.buffer_tracks[id].position_history[-30:]

            # 出口道路检测：车辆从一条道路移动到另一条道路时记录exit_road
            current_road = intersects_central_point(
                tracked_xyxy=frame_element.tracked_xyxy[i],
                polygons=frame_element.roads_info,
            )
            track = self.buffer_tracks[id]
            if (current_road is not None
                    and track.start_road is not None
                    and current_road != track.start_road
                    and track.exit_road is None):
                track.exit_road = current_road

            # 寻找与道路多边形的第一次交集
            if self.buffer_tracks[id].start_road is None:
                self.buffer_tracks[id].start_road = intersects_central_point(
                    tracked_xyxy=frame_element.tracked_xyxy[i],
                    polygons=frame_element.roads_info,
                )
                # 检查函数是否最终提供了实际的道路编号：
                if self.buffer_tracks[id].start_road is not None:
                    # 然后保存该时刻：
                    self.buffer_tracks[id].timestamp_init_road = frame_element.timestamp

        # 如果id的生存时间> size_buffer_analytics，则从字典中删除旧id
        keys_to_remove = []
        for key, track_element in sorted(self.buffer_tracks.items()):  # 按键对元素进行排序
            if frame_element.timestamp - track_element.timestamp_first < self.size_buffer_analytics:
                break  # 如果time_delta大于check，则中断循环
            else:
                keys_to_remove.append(key)  # 添加要删除的键

        # 发射完成轨迹数据（供下游节点使用）
        # 运动补偿数据（用于世界坐标转换）
        H = frame_element.homography_matrix
        has_H = is_valid_homography(H)
        drone_disp = getattr(frame_element, "drone_displacement_m", None)
        world_anchor = getattr(frame_element, "world_anchor_lat_lon", None)
        can_convert_world = has_H and drone_disp is not None

        completed_tracks = []
        for key in keys_to_remove:
            track = self.buffer_tracks[key]
            duration = track.timestamp_last - track.timestamp_first
            if duration >= self.min_track_duration and len(track.trajectory_points) >= self.min_trajectory_points:
                completed_track_data = {
                    "track_id": track.id,
                    "start_road": track.start_road,
                    "exit_road": track.exit_road,
                    "turn_behavior": track.turn_behavior,
                    "vehicle_class": track.vehicle_class,
                    "yolo_class_id": track.yolo_class_id,
                    "duration_sec": round(duration, 2),
                    "avg_speed_kmh": round(track.avg_speed_kmh, 1),
                    "max_speed_kmh": round(track.max_speed_kmh, 1),
                    "trajectory_px": track.trajectory_points,
                    "timestamp_first": track.timestamp_first,
                    "timestamp_last": track.timestamp_last,
                }

                # 入口/出口点世界坐标
                if can_convert_world and track.trajectory_points:
                    entry_px = np.array([track.trajectory_points[0]])
                    exit_px = np.array([track.trajectory_points[-1]])
                    entry_world = pixel_to_world_compensated(entry_px, H, drone_disp)[0]
                    exit_world = pixel_to_world_compensated(exit_px, H, drone_disp)[0]
                    completed_track_data["entry_point_m"] = [
                        round(float(entry_world[0]), 2), round(float(entry_world[1]), 2)
                    ]
                    completed_track_data["exit_point_m"] = [
                        round(float(exit_world[0]), 2), round(float(exit_world[1]), 2)
                    ]
                    if world_anchor:
                        completed_track_data["world_anchor_lat_lon"] = [
                            round(world_anchor[0], 6), round(world_anchor[1], 6)
                        ]

                completed_tracks.append(completed_track_data)
            self.buffer_tracks.pop(key)  # 从字典中删除元素
            logger.info(f"Removed tracker with key {key}")

        # 记录处理结果：
        frame_element.buffer_tracks = self.buffer_tracks
        frame_element.completed_tracks = completed_tracks if completed_tracks else None

        return frame_element