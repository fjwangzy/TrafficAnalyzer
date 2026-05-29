import math
import numpy as np
import logging

from elements.FrameElement import FrameElement
from elements.VideoEndBreakElement import VideoEndBreakElement
from utils_local.utils import profile_time
from utils_local.homography import pixel_to_world, is_valid_homography

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

        for track_id, track in frame_element.buffer_tracks.items():
            # 裁剪position_history到history_frames窗口
            if len(track.position_history) > self.history_frames:
                track.position_history = track.position_history[-self.history_frames:]

            if len(track.position_history) < 3:
                continue

            p_old = track.position_history[0]  # (cx, cy, timestamp)
            p_new = track.position_history[-1]
            dt = p_new[2] - p_old[2]
            if dt < 0.05:
                continue

            if has_H:
                # 世界坐标位移（米）
                pts_px = np.array([[p_old[0], p_old[1]], [p_new[0], p_new[1]]])
                pts_world = pixel_to_world(pts_px, H)
                dist_m = float(np.linalg.norm(pts_world[1] - pts_world[0]))
                track.speed_kmh = (dist_m / dt) * 3.6
            else:
                # 像素位移回退
                dist_px = np.sqrt((p_new[0] - p_old[0]) ** 2 + (p_new[1] - p_old[1]) ** 2)
                if dist_px < self.min_displacement_px:
                    track.speed_kmh = 0.0
                else:
                    track.speed_kmh = (dist_px / dt) * 3.6  # 像素/秒 * 3.6（非真实km/h）

            # EMA平滑
            track.avg_speed_kmh = alpha * track.speed_kmh + (1 - alpha) * track.avg_speed_kmh
            track.max_speed_kmh = max(track.max_speed_kmh, track.speed_kmh)

            # 更新当前运动方向角度
            dx = p_new[0] - p_old[0]
            dy = p_new[1] - p_old[1]
            if abs(dx) > 0.5 or abs(dy) > 0.5:
                track.heading_angle = math.degrees(math.atan2(dy, dx))

        return frame_element
