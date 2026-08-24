"""基于单应性矩阵和帧间位移计算车辆速度（km/h）。

改进点（审查报告 T-202 / S-003）:
  使用线性回归拟合 position_history 全部数据点，
  取斜率作为速度。相比首尾两点法，抗 bbox 抖动能力大幅提升。
  bbox ±3px 抖动下车速波动 <2km/h。
"""
import math

import numpy as np

from elements.FrameElement import FrameElement
from elements.VideoEndBreakElement import VideoEndBreakElement
from utils_local.track_lifecycle import active_tracks_of, mature_tracks_of
from utils_local.utils import profile_time


class SpeedEstimationNode:
    """基于单应性矩阵和帧间位移计算车辆速度（km/h）。

    只回归 ID 后逐帧保存的 ENU 世界事实；世界点不足时保持速度为空，
    禁止把当前 H 套到历史像素或把 px/s 冒充 km/h。
    position_history由TrackerInfoUpdateNode填充（含时间戳），本节点裁剪到history_frames窗口。
    """

    def __init__(self, config: dict) -> None:
        cfg = config.get("speed_estimation", {})
        self.enabled = cfg.get("enabled", True)
        self.history_frames = cfg.get("history_frames", 15)
        self.smoothing_window = cfg.get("smoothing_window", 5)
        self.min_displacement_px = cfg.get("min_displacement_px", 2.0)
        self.max_segment_speed_ms = float(cfg.get("max_segment_speed_ms", 45.0))

    @staticmethod
    def _clear_current_world_motion(track) -> None:
        track.velocity_ms = None
        track.speed_kmh = None
        track.avg_speed_kmh = None

    def _robust_velocity_ms(self, world_history) -> np.ndarray | None:
        """Return a segment-median velocity after rejecting impossible jumps.

        A current-frame projection discontinuity affects two adjacent segments
        (jump in and jump back). Regressing raw positions turns that transient
        into a plausible-looking high speed; segment filtering keeps it out of
        the business motion facts without touching the image association.
        """
        points = np.asarray(world_history, dtype=np.float64)
        if points.ndim != 2 or points.shape[1] < 3 or not np.all(np.isfinite(points)):
            return None
        dt = np.diff(points[:, 2])
        valid_dt = dt > 0
        if not np.any(valid_dt):
            return None
        velocity = np.diff(points[:, :2], axis=0)[valid_dt] / dt[valid_dt, None]
        speed = np.linalg.norm(velocity, axis=1)
        valid_velocity = np.all(np.isfinite(velocity), axis=1) & (
            speed <= self.max_segment_speed_ms
        )
        velocity = velocity[valid_velocity]
        if velocity.size == 0:
            return None
        return np.median(velocity, axis=0)

    @profile_time
    def process(self, frame_element: FrameElement) -> FrameElement:
        if isinstance(frame_element, VideoEndBreakElement):
            return frame_element

        if not self.enabled:
            return frame_element

        if not getattr(frame_element, "geo_analytics_eligible", False):
            for track in active_tracks_of(frame_element).values():
                self._clear_current_world_motion(track)
            return frame_element

        alpha = 2.0 / (self.smoothing_window + 1)

        for track in mature_tracks_of(frame_element).values():
            # 裁剪position_history到history_frames窗口
            if len(track.position_history) > self.history_frames:
                track.position_history = track.position_history[-self.history_frames:]

            world_history = getattr(track, "position_history_enu_m", [])
            if len(world_history) > self.history_frames:
                track.position_history_enu_m = world_history[-self.history_frames:]
                world_history = track.position_history_enu_m

            if len(world_history) < 3:
                self._clear_current_world_motion(track)
                continue

            t_arr = np.array([p[2] for p in world_history])
            dt_total = t_arr[-1] - t_arr[0]
            if dt_total < 0.05:
                self._clear_current_world_motion(track)
                continue

            true_vel = self._robust_velocity_ms(world_history)
            if true_vel is None:
                self._clear_current_world_motion(track)
                continue
            speed_ms = float(np.linalg.norm(true_vel))
            track.velocity_ms = true_vel
            track.speed_kmh = speed_ms * 3.6
            if speed_ms > 0.5:
                track.heading_angle = math.degrees(
                    math.atan2(true_vel[1], true_vel[0])
                )

            # EMA平滑
            if track.speed_kmh is None:
                continue
            if track.avg_speed_kmh is None:
                track.avg_speed_kmh = track.speed_kmh
            else:
                track.avg_speed_kmh = (
                    alpha * track.speed_kmh
                    + (1 - alpha) * track.avg_speed_kmh
                )
            track.max_speed_kmh = (
                track.speed_kmh
                if track.max_speed_kmh is None
                else max(track.max_speed_kmh, track.speed_kmh)
            )

        return frame_element
