import logging
import numpy as np

from elements.FrameElement import FrameElement
from elements.VideoEndBreakElement import VideoEndBreakElement
from utils_local.utils import profile_time
from utils_local.trajectory_classifier import classify_turning_movement
from utils_local.homography import is_valid_homography
from utils_local.motion_compensation import pixel_to_world_compensated
from utils_local.coordinates import enu_to_gcj02

logger = logging.getLogger(__name__)


class TrajectoryNode:
    """轨迹还原节点：为完成的轨迹分类转向行为并丰富轨迹数据。

    依赖 TrackerInfoUpdateNode 发射的 completed_tracks，
    在轨迹完成时补充 turn_behavior 等字段。
    """

    def __init__(self, config: dict) -> None:
        cfg = config.get("trajectory", {})
        self.enabled = cfg.get("enabled", True)
        self.min_track_duration_sec = cfg.get("min_track_duration_sec", 2.0)
        self.turn_thresholds = cfg.get("turn_angle_thresholds", {
            "straight": 30,
            "left_turn": [30, 150],
            "right_turn": [-150, -30],
            "u_turn": [150, 180],
        })
        # 环形交叉路口中心坐标（可选，从配置或道路多边形计算）
        self.roundabout_center: tuple | None = None

    @profile_time
    def process(self, frame_element: FrameElement) -> FrameElement:
        if isinstance(frame_element, VideoEndBreakElement):
            return frame_element

        if not self.enabled:
            return frame_element

        completed = frame_element.completed_tracks or []
        if not completed:
            return frame_element

        # 世界坐标转换所需数据
        H = frame_element.homography_matrix
        has_H = is_valid_homography(H)
        drone_disp = getattr(frame_element, "drone_displacement_m", None)
        anchor_gcj02 = getattr(frame_element, "anchor_gcj02", None)
        can_convert_world = has_H and drone_disp is not None

        for ct in completed:
            trajectory_px = ct.get("trajectory_px", [])
            trajectory_timestamps = ct.get("trajectory_timestamps_sec", [])

            # 转向行为分类
            if not ct.get("turn_behavior"):
                ct["turn_behavior"] = classify_turning_movement(
                    trajectory_px,
                    roundabout_center=self.roundabout_center,
                    thresholds=self.turn_thresholds,
                )

            # 补充轨迹长度信息
            ct["trajectory_length"] = len(trajectory_px)

            # 简化轨迹点（降采样以减少Kafka消息体积）
            if len(trajectory_px) > 50:
                step = len(trajectory_px) // 50
                indices = list(range(0, len(trajectory_px), step))
                ct["trajectory_px"] = [trajectory_px[index] for index in indices]
                for key in (
                    "trajectory_bbox_center_px",
                    "ground_contact_points_px",
                    "trajectory_enu_m",
                    "trajectory_gcj02",
                    "trajectory_timestamps_sec",
                    "trajectory_frame_nums",
                    "point_quality_lineage",
                ):
                    values = ct.get(key)
                    if isinstance(values, list) and len(values) == len(trajectory_px):
                        ct[key] = [values[index] for index in indices]
                if len(trajectory_timestamps) == len(trajectory_px):
                    ct["trajectory_time_offsets_sec"] = [
                        round(value - trajectory_timestamps[0], 3)
                        for value in ct["trajectory_timestamps_sec"]
                    ]

            # Canonical world points were accumulated with each frame's transform.
            # Only use the old final-frame reprojection as a non-runtime fallback.
            if can_convert_world and not ct.get("trajectory_enu_m"):
                pts_px = np.array(
                    ct.get("ground_contact_points_px") or ct["trajectory_px"]
                )
                pts_world = pixel_to_world_compensated(pts_px, H, drone_disp)
                ct["trajectory_enu_m"] = [
                    [round(float(p[0]), 2), round(float(p[1]), 2)]
                    for p in pts_world
                ]

            if ct.get("trajectory_enu_m") and anchor_gcj02:
                ct["anchor_gcj02"] = [
                    round(anchor_gcj02[0], 6), round(anchor_gcj02[1], 6)
                ]
                if len(ct.get("trajectory_gcj02") or []) != len(
                    ct["trajectory_enu_m"]
                ):
                    ct["trajectory_gcj02"] = [
                        [round(lon, 8), round(lat, 8)]
                        for lon, lat in (
                            enu_to_gcj02(point[0], point[1], anchor_gcj02)
                            for point in ct["trajectory_enu_m"]
                        )
                    ]

        frame_element.completed_tracks = completed
        return frame_element
