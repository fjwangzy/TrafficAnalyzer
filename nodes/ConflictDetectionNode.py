import logging
import numpy as np

from elements.FrameElement import FrameElement
from elements.VideoEndBreakElement import VideoEndBreakElement
from utils_local.utils import profile_time
from utils_local.homography import pixel_to_world, is_valid_homography

logger = logging.getLogger(__name__)


class ConflictDetectionNode:
    """机非冲突检测节点：基于TTC（碰撞时间）和距离检测机动车与非机动车的潜在冲突。

    需要单应性标定才能准确计算米级距离。无标定时跳过（避免误报）。
    当前uav_best.pt模型仅检测交通工具类(2-9)，不含person(0)/bicycle(1)，
    需要模型微调后方可启用（enabled: false by default）。
    """

    def __init__(self, config: dict) -> None:
        cfg = config.get("conflict_detection", {})
        self.enabled = cfg.get("enabled", False)
        self.proximity_threshold_m = cfg.get("proximity_threshold_m", 3.0)
        self.ttc_threshold_sec = cfg.get("ttc_threshold_sec", 2.0)
        self.severity_levels = cfg.get("severity_levels", {
            "critical": {"ttc": 1.0, "distance_m": 1.5},
            "warning": {"ttc": 2.0, "distance_m": 3.0},
            "info": {"ttc": 3.0, "distance_m": 5.0},
        })
        self._pair_cooldown: dict[tuple, float] = {}
        self.cooldown_sec = 5.0

    @profile_time
    def process(self, frame_element: FrameElement) -> FrameElement:
        if isinstance(frame_element, VideoEndBreakElement):
            return frame_element

        if not self.enabled:
            frame_element.conflict_events = []
            return frame_element

        H = frame_element.homography_matrix
        if not is_valid_homography(H):
            frame_element.conflict_events = []
            return frame_element

        # 分离机动车和非机动车轨迹
        motor_tracks = []
        non_motor_tracks = []
        for i, track_id in enumerate(frame_element.id_list):
            track = frame_element.buffer_tracks.get(track_id)
            if not track:
                continue
            bbox = frame_element.tracked_xyxy[i]
            cx = (bbox[0] + bbox[2]) / 2.0
            cy = (bbox[1] + bbox[3]) / 2.0
            entry = {
                "track_id": track_id,
                "center_px": (cx, cy),
                "speed_kmh": track.avg_speed_kmh,
                "vehicle_class": track.vehicle_class,
            }
            if track.vehicle_class == "motor":
                motor_tracks.append(entry)
            elif track.vehicle_class == "non_motor":
                non_motor_tracks.append(entry)

        # 冲突检测
        conflict_events = []
        current_time = frame_element.timestamp

        # 清理过期的冷却记录
        expired_keys = [
            k for k, ts in self._pair_cooldown.items()
            if current_time - ts > self.cooldown_sec * 2
        ]
        for k in expired_keys:
            del self._pair_cooldown[k]

        for motor in motor_tracks:
            for non_motor in non_motor_tracks:
                pair_key = (
                    min(motor["track_id"], non_motor["track_id"]),
                    max(motor["track_id"], non_motor["track_id"]),
                )
                # 冷却检查
                if pair_key in self._pair_cooldown:
                    if current_time - self._pair_cooldown[pair_key] < self.cooldown_sec:
                        continue

                # 计算世界坐标距离
                pts = pixel_to_world(
                    np.array([motor["center_px"], non_motor["center_px"]]), H
                )
                dist_m = float(np.linalg.norm(pts[0] - pts[1]))

                if dist_m > self.proximity_threshold_m:
                    continue

                # 计算TTC
                speed_ms = motor["speed_kmh"] / 3.6
                ttc = dist_m / speed_ms if speed_ms > 0.5 else None

                severity = self._classify_severity(dist_m, ttc)
                if severity:
                    conflict_events.append({
                        "motor_id": motor["track_id"],
                        "non_motor_id": non_motor["track_id"],
                        "distance_m": round(dist_m, 2),
                        "ttc_sec": round(ttc, 2) if ttc else None,
                        "severity": severity,
                        "motor_speed_kmh": round(motor["speed_kmh"], 1),
                    })
                    self._pair_cooldown[pair_key] = current_time

        frame_element.conflict_events = conflict_events
        return frame_element

    def _classify_severity(self, dist_m: float, ttc: float | None) -> str | None:
        """根据距离和TTC分类冲突严重度。"""
        for level in ["critical", "warning", "info"]:
            cfg = self.severity_levels.get(level, {})
            dist_thresh = cfg.get("distance_m", float("inf"))
            ttc_thresh = cfg.get("ttc", float("inf"))

            if dist_m < dist_thresh:
                return level
            if ttc is not None and ttc < ttc_thresh:
                return level

        return None
