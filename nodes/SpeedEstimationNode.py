"""基于单应性矩阵和帧间位移计算车辆速度（km/h）。

改进点（审查报告 T-202 / S-003）:
  使用线性回归拟合 position_history 全部数据点，
  取斜率作为速度。相比首尾两点法，抗 bbox 抖动能力大幅提升。
  bbox ±3px 抖动下车速波动 <2km/h。
"""
import math
import numpy as np
import logging

from elements.FrameElement import FrameElement
from elements.VideoEndBreakElement import VideoEndBreakElement
from utils_local.utils import profile_time
from utils_local.homography import pixel_to_world, is_valid_homography, undistort_points

logger = logging.getLogger(__name__)


class SpeedEstimationNode:
    """基于单应性矩阵和帧间位移计算车辆速度（km/h）。

    使用EMA平滑消除bbox抖动噪声。无标定时回退到像素/秒。
    position_history由TrackerInfoUpdateNode填充（含时间戳），本节点裁剪到history_frames窗口。
    """

    def __init__(self, config: dict) -> None:
        cfg = config.get("speed_estimation", {})
        self.enabled = cfg.get("enabled", True)
        self.history_frames = cfg.get("history_frames", 15)
        self.smoothing_window = cfg.get("smoothing_window", 5)
        self.min_displacement_px = cfg.get("min_displacement_px", 2.0)
        self._logged_no_homography = False

    @profile_time
    def process(self, frame_element: FrameElement) -> FrameElement:
        if isinstance(frame_element, VideoEndBreakElement):
            return frame_element

        if not self.enabled:
            return frame_element

        H = frame_element.homography_matrix
        has_H = is_valid_homography(H)

        if not has_H and not self._logged_no_homography:
            logger.warning("SpeedEstimationNode: 无有效H矩阵，车速将以像素/秒为单位输出")
            self._logged_no_homography = True

        alpha = 2.0 / (self.smoothing_window + 1)

        # 运动补偿数据
        drone_vel = getattr(frame_element, "drone_velocity_ms", None)
        is_hovering = getattr(frame_element, "is_hovering", False)

        # 镜头畸变校正数据
        dist_coeffs = getattr(frame_element, "dist_coeffs", None)
        cam_intrinsics = getattr(frame_element, "camera_intrinsics", None)
        img_size = (frame_element.frame.shape[1], frame_element.frame.shape[0]) if dist_coeffs else None

        for track_id, track in frame_element.buffer_tracks.items():
            # 裁剪position_history到history_frames窗口
            if len(track.position_history) > self.history_frames:
                track.position_history = track.position_history[-self.history_frames:]

            world_history = getattr(track, "position_history_enu_m", [])
            if len(world_history) > self.history_frames:
                track.position_history_enu_m = world_history[-self.history_frames:]
                world_history = track.position_history_enu_m

            if len(track.position_history) < 3 and len(world_history) < 3:
                continue

            # T-202: 线性回归速度估算
            # 提取时间戳和坐标
            source_history = world_history if len(world_history) >= 3 else track.position_history
            t_arr = np.array([p[2] for p in source_history])
            x_arr = np.array([p[0] for p in source_history])
            y_arr = np.array([p[1] for p in source_history])

            dt_total = t_arr[-1] - t_arr[0]
            if dt_total < 0.05:
                continue

            if len(world_history) >= 3:
                pts_world = np.column_stack([x_arr, y_arr])
                t_centered = t_arr - t_arr[0]
                slope_e = np.polyfit(t_centered, pts_world[:, 0], 1)[0]
                slope_n = np.polyfit(t_centered, pts_world[:, 1], 1)[0]
                true_vel = np.array([slope_e, slope_n])
                speed_ms = float(np.linalg.norm(true_vel))
                track.velocity_ms = true_vel
                track.speed_kmh = speed_ms * 3.6
                if speed_ms > 0.5:
                    track.heading_angle = math.degrees(
                        math.atan2(true_vel[1], true_vel[0])
                    )
            elif has_H:
                # T-202: 在世界坐标系做线性回归
                # 先用当前帧H转换所有历史点到世界坐标系
                pts_px = np.column_stack([x_arr, y_arr])
                # 镜头畸变校正（如果配置了）
                if dist_coeffs and cam_intrinsics and img_size:
                    pts_px = undistort_points(pts_px, cam_intrinsics, img_size, dist_coeffs)
                pts_world = pixel_to_world(pts_px, H)

                # 对 easting 和 northing 分别做线性回归
                t_centered = t_arr - t_arr[0]  # 避免数值精度问题
                # np.polyfit(t, x, 1) → [slope, intercept]
                slope_e = np.polyfit(t_centered, pts_world[:, 0], 1)[0]  # easting velocity (m/s)
                slope_n = np.polyfit(t_centered, pts_world[:, 1], 1)[0]  # northing velocity (m/s)

                apparent_vel = np.array([slope_e, slope_n])  # m/s, 无人机相对速度

                # Legacy fallback: all points share the current camera pose.
                if drone_vel is not None and not is_hovering:
                    true_vel = apparent_vel - drone_vel
                    speed_ms = float(np.linalg.norm(true_vel))
                else:
                    true_vel = apparent_vel
                    speed_ms = float(np.linalg.norm(true_vel))

                track.velocity_ms = true_vel
                track.speed_kmh = speed_ms * 3.6

                # 更新heading_angle（世界坐标系方向）
                if speed_ms > 0.5:
                    track.heading_angle = math.degrees(math.atan2(true_vel[1], true_vel[0]))
            else:
                # 像素空间线性回归回退（无标定）
                t_centered = t_arr - t_arr[0]
                slope_x = np.polyfit(t_centered, x_arr, 1)[0]  # px/s
                slope_y = np.polyfit(t_centered, y_arr, 1)[0]  # px/s

                dist_px_per_sec = math.sqrt(slope_x ** 2 + slope_y ** 2)
                if dist_px_per_sec < self.min_displacement_px:
                    track.speed_kmh = 0.0
                else:
                    track.speed_kmh = dist_px_per_sec * 3.6  # 像素/秒 * 3.6（非真实km/h）

                if abs(slope_x) > 0.5 or abs(slope_y) > 0.5:
                    track.heading_angle = math.degrees(math.atan2(slope_y, slope_x))
                track.velocity_ms = None

            # EMA平滑
            track.avg_speed_kmh = alpha * track.speed_kmh + (1 - alpha) * track.avg_speed_kmh
            track.max_speed_kmh = max(track.max_speed_kmh, track.speed_kmh)

        return frame_element
