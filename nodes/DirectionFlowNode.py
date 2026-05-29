import logging

from elements.FrameElement import FrameElement
from elements.VideoEndBreakElement import VideoEndBreakElement
from utils_local.utils import profile_time
from utils_local.trajectory_classifier import compute_heading, classify_direction

logger = logging.getLogger(__name__)


class DirectionFlowNode:
    """方向流量统计节点：左转/直行/右转/掉头，无需车道多边形标注。

    始终运行（零标注），通过车辆轨迹的运动方向变化自动分类。
    """

    def __init__(self, config: dict) -> None:
        cfg = config.get("direction_flow", {})
        self.enabled = cfg.get("enabled", True)
        self.min_track_duration_sec = cfg.get("min_track_duration_sec", 2.0)
        self.min_position_points = cfg.get("min_position_points", 8)
        self.heading_window = cfg.get("heading_window", 5)
        self.queue_speed_threshold_kmh = cfg.get("queue_speed_threshold_kmh", 5.0)
        self.turn_thresholds = cfg.get("turn_thresholds", {
            "straight": 25,
            "turn": 120,
        })
        # 方向级车头时距跟踪
        self._last_passage_time: dict[str, float] = {}
        self._headway_accumulator: dict[str, list[float]] = {
            "straight": [], "left_turn": [], "right_turn": [],
        }
        self._headway_window_sec = 300  # 5分钟滑动窗口

    @profile_time
    def process(self, frame_element: FrameElement) -> FrameElement:
        if isinstance(frame_element, VideoEndBreakElement):
            return frame_element

        if not self.enabled:
            return frame_element

        buffer_tracks = frame_element.buffer_tracks
        if not buffer_tracks:
            frame_element.direction_stats = self._empty_stats()
            frame_element.queue_count = 0
            return frame_element

        # 1. 对每条活跃轨迹计算当前方向
        direction_counts = {"straight": 0, "left_turn": 0, "right_turn": 0, "u_turn": 0, "unknown": 0}
        direction_speeds: dict[str, list[float]] = {d: [] for d in direction_counts}
        queue_count = 0

        for track_id, track in buffer_tracks.items():
            # 排队检测：速度 < 阈值
            if track.speed_kmh < self.queue_speed_threshold_kmh and track.speed_kmh >= 0:
                queue_count += 1
                continue

            # 方向分类：需要足够的轨迹点
            if len(track.position_history) < self.min_position_points:
                direction_counts["unknown"] += 1
                continue

            # 计算入口方向（轨迹前半段）和出口方向（轨迹后半段）
            mid = len(track.position_history) // 2
            entry_heading = compute_heading(
                track.position_history[: mid + 1], self.heading_window
            )
            exit_heading = compute_heading(
                track.position_history[mid:], self.heading_window
            )

            if entry_heading is None or exit_heading is None:
                direction_counts["unknown"] += 1
                continue

            direction = classify_direction(entry_heading, exit_heading, self.turn_thresholds)
            direction_counts[direction] += 1
            direction_speeds[direction].append(track.speed_kmh)

            # 记录到TrackElement供下游使用
            track.direction_class = direction

        # 2. 车头时距（同方向连续完成轨迹的时间差）
        completed = frame_element.completed_tracks or []
        for ct in completed:
            direction = ct.get("turn_behavior", "unknown")
            if direction not in self._headway_accumulator:
                continue
            if direction in self._last_passage_time:
                headway = ct["timestamp_last"] - self._last_passage_time[direction]
                if 0 < headway < 60:
                    self._headway_accumulator[direction].append(headway)
            self._last_passage_time[direction] = ct["timestamp_last"]

        # 清理超出窗口的旧数据
        for d in self._headway_accumulator:
            acc = self._headway_accumulator[d]
            if len(acc) > 100:
                self._headway_accumulator[d] = acc[-100:]

        # 3. 汇总输出
        direction_stats = {}
        for d in ["straight", "left_turn", "right_turn", "u_turn"]:
            speeds = direction_speeds[d]
            headways = self._headway_accumulator.get(d, [])
            direction_stats[d] = {
                "count": direction_counts[d],
                "avg_speed_kmh": round(sum(speeds) / len(speeds), 1) if speeds else 0,
                "avg_headway_sec": round(sum(headways) / len(headways), 2) if headways else None,
                "min_headway_sec": round(min(headways), 2) if headways else None,
            }
        direction_stats["unknown"] = {"count": direction_counts["unknown"]}

        frame_element.direction_stats = direction_stats
        frame_element.queue_count = queue_count
        return frame_element

    def _empty_stats(self) -> dict:
        stats = {}
        for d in ["straight", "left_turn", "right_turn", "u_turn"]:
            stats[d] = {
                "count": 0, "avg_speed_kmh": 0,
                "avg_headway_sec": None, "min_headway_sec": None,
            }
        stats["unknown"] = {"count": 0}
        return stats
