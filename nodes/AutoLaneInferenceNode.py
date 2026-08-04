"""自动车道推断节点 — 从已完成轨迹中自动发现车道。

无需人工标注的 ROI 线或车道多边形，通过分析车辆轨迹的空间聚类
自动推断车道中心线，并计算各车道的交通指标。

管道位置: TrajectoryNode → **AutoLaneInferenceNode** → CalcStatisticsNode

依赖字段:
    读取: completed_tracks, buffer_tracks, homography_matrix
    写入: inferred_lanes (FrameElement.inferred_lanes)
"""

import logging
from collections import defaultdict

import numpy as np

from elements.FrameElement import FrameElement
from elements.VideoEndBreakElement import VideoEndBreakElement
from utils_local.track_lifecycle import mature_tracks_of
from utils_local.utils import profile_time
from utils_local.homography import pixel_to_world, is_valid_homography
from utils_local.auto_lane_inference import (
    InferredLane,
    cluster_trajectories_spatial,
    merge_similar_clusters,
    fit_centerline,
    compute_entry_exit_headings,
    generate_lane_label,
    match_active_track_to_lane,
    compute_flow_per_min,
    compute_headway,
    circular_mean_deg,
)
from utils_local.trajectory_classifier import classify_direction

logger = logging.getLogger(__name__)


class AutoLaneInferenceNode:
    """从轨迹数据自动推断车道中心线和交通指标。

    核心算法：
    1. 维护已完成轨迹的滚动缓冲区
    2. 按方向类别分桶 → 桶内空间聚类 → 每个簇 = 一条车道
    3. 拟合中心线 + 自动生成标签
    4. 将活跃轨迹匹配到推断车道
    5. 计算各车道实时交通指标
    """

    def __init__(self, config: dict) -> None:
        cfg = config.get("auto_lane", {})
        self.enabled = cfg.get("enabled", True)
        self.window_sec = cfg.get("window_sec", 180)        # 轨迹缓冲窗口(秒)
        self.min_tracks_per_lane = cfg.get("min_tracks_per_lane", 3)
        self.entry_exit_threshold_px = cfg.get("entry_exit_threshold_px", 120.0)
        self.centerline_samples = cfg.get("centerline_samples", 20)
        self.queue_speed_threshold_kmh = cfg.get("queue_speed_threshold_kmh", 5.0)
        self.flow_window_sec = cfg.get("flow_window_sec", 300)  # 流量计算窗口(秒)
        self.min_track_points = cfg.get("min_track_points", 8)
        self.recluster_interval_sec = cfg.get("recluster_interval_sec", 5.0)

        # 状态
        self._completed_buffer: list[dict] = []  # 滚动缓冲区
        self._inferred_lanes: dict[str, InferredLane] = {}
        self._last_cluster_time: float = 0
        self._lane_completion_times: dict[str, list[float]] = defaultdict(list)
        self._lane_id_counter: int = 0

    @profile_time
    def process(self, frame_element: FrameElement) -> FrameElement:
        if isinstance(frame_element, VideoEndBreakElement):
            return frame_element

        if getattr(frame_element, "runtime_map_bundle", None):
            frame_element.inferred_lanes = None
            frame_element.lane_source = "channelized_map"
            return frame_element

        if not self.enabled:
            return frame_element

        # 向下兼容：如果有车道标注数据（人工或模型检测），跳过自动推断
        lane_polygons = getattr(frame_element, "lane_polygons", None)
        lane_source = getattr(frame_element, "lane_source", None)
        if lane_polygons or lane_source in ("manual", "model"):
            return frame_element

        current_time = frame_element.timestamp

        # 1. 收集新的已完成轨迹到缓冲区
        self._collect_completed(frame_element)

        # 2. 清理过期轨迹
        cutoff = current_time - self.window_sec
        self._completed_buffer = [
            t for t in self._completed_buffer if t.get("_ts", 0) > cutoff
        ]

        # 3. 重新聚类（按间隔，非每帧）
        if current_time - self._last_cluster_time >= self.recluster_interval_sec:
            self._recluster_lanes(current_time)
            self._last_cluster_time = current_time

        # 4. 匹配活跃轨迹到推断车道
        self._match_active_tracks(frame_element)

        # 5. 计算各车道统计
        self._compute_lane_stats(frame_element, current_time)

        # 输出到 FrameElement
        frame_element.inferred_lanes = self._inferred_lanes if self._inferred_lanes else None
        return frame_element

    def _collect_completed(self, frame_element: FrameElement) -> None:
        """从 completed_tracks 收集新的已完成轨迹。"""
        completed = getattr(frame_element, "completed_tracks", None)
        if not completed:
            return

        for ct in completed:
            trajectory_px = ct.get("trajectory_px", [])
            if len(trajectory_px) < self.min_track_points:
                continue

            direction = ct.get("turn_behavior")
            if not direction or direction == "unknown":
                # 尝试从轨迹重新计算方向（使用 heading delta，非中心向量）
                entry_h, exit_h = compute_entry_exit_headings(trajectory_px)
                if entry_h is not None and exit_h is not None:
                    direction = classify_direction(entry_h, exit_h, {
                        "straight": 25, "turn": 120,
                    })
                else:
                    continue

            enriched = {
                "trajectory_px": trajectory_px,
                "direction_class": direction,
                "avg_speed_kmh": ct.get("avg_speed_kmh", 0),
                "start_road": ct.get("start_road"),
                "exit_road": ct.get("exit_road"),
                "track_id": ct.get("track_id"),
                "timestamp_last": ct.get("timestamp_last", 0),
                "_ts": ct.get("timestamp_last", 0),  # 内部排序用
            }
            self._completed_buffer.append(enriched)

    def _recluster_lanes(self, current_time: float) -> None:
        """重新聚类轨迹并更新推断车道。"""
        if len(self._completed_buffer) < self.min_tracks_per_lane:
            return

        # 按方向类别分桶
        direction_buckets = defaultdict(list)
        for track in self._completed_buffer:
            direction_buckets[track["direction_class"]].append(track)

        # 在每个桶内做空间聚类
        all_clusters = []
        for direction_class, bucket in direction_buckets.items():
            if len(bucket) < self.min_tracks_per_lane:
                continue

            clusters = cluster_trajectories_spatial(
                bucket, self.entry_exit_threshold_px
            )
            for cluster in clusters:
                if len(cluster) >= self.min_tracks_per_lane:
                    all_clusters.append((direction_class, cluster))

        # 合并空间邻近且方向相同的聚类（减少碎片化）
        # 使用 3.5x 阈值：标准十字路口平行多车道间距可达 150-350px
        all_clusters = merge_similar_clusters(
            all_clusters, merge_threshold_px=self.entry_exit_threshold_px * 3.5
        )

        # 为每个聚类构建 InferredLane
        new_lanes = {}
        self._lane_id_counter = 0

        for direction_class, cluster in all_clusters:
            self._lane_id_counter += 1
            lane_id = f"auto_{self._lane_id_counter}"

            # 拟合中心线
            centerline = fit_centerline(cluster, self.centerline_samples)
            if np.all(centerline == 0):
                continue

            # 计算入口/出口朝向
            entry_headings = []
            exit_headings = []
            for t in cluster:
                eh, xh = compute_entry_exit_headings(t["trajectory_px"])
                if eh is not None:
                    entry_headings.append(eh)
                if xh is not None:
                    exit_headings.append(xh)

            avg_entry_h = circular_mean_deg(entry_headings) if entry_headings else 0
            avg_exit_h = circular_mean_deg(exit_headings) if exit_headings else 0

            # 生成标签
            label = generate_lane_label(avg_entry_h, avg_exit_h, direction_class)

            # 入口/出口中心
            entry_points = np.array([t["trajectory_px"][0] for t in cluster])
            exit_points = np.array([t["trajectory_px"][-1] for t in cluster])

            lane = InferredLane(
                lane_id=lane_id,
                label=label,
                direction_class=direction_class,
                entry_heading_deg=round(avg_entry_h, 1),
                exit_heading_deg=round(avg_exit_h, 1),
                centerline_px=centerline.tolist(),
                entry_center_px=tuple(np.mean(entry_points, axis=0).tolist()),
                exit_center_px=tuple(np.mean(exit_points, axis=0).tolist()),
                track_ids=[t.get("track_id") for t in cluster],
            )
            new_lanes[lane_id] = lane

        # 保留旧车道的完成时间记录（用于流量计算连续性）
        old_lane_track_ids = {}
        for old_id, old_lane in self._inferred_lanes.items():
            old_lane_track_ids[old_id] = set(old_lane.track_ids)

        # 将旧的完成时间映射到新车道（通过轨迹ID重叠匹配）
        new_lane_completion_times = defaultdict(list)
        for new_id, new_lane in new_lanes.items():
            new_track_ids = set(new_lane.track_ids)
            best_old_id = None
            best_overlap = 0
            for old_id, old_ids in old_lane_track_ids.items():
                overlap = len(new_track_ids & old_ids)
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_old_id = old_id
            if best_old_id and best_old_id in self._lane_completion_times:
                new_lane_completion_times[new_id] = self._lane_completion_times[best_old_id]

        self._lane_completion_times = new_lane_completion_times
        self._inferred_lanes = new_lanes

        # 更新每个车道的完成时间列表
        for track in self._completed_buffer:
            for lane_id, lane in self._inferred_lanes.items():
                if track.get("track_id") in lane.track_ids:
                    ts = track.get("_ts", 0)
                    times = self._lane_completion_times[lane_id]
                    if ts not in times:
                        times.append(ts)
                    # 保持排序和窗口大小
                    times.sort()
                    if len(times) > 200:
                        self._lane_completion_times[lane_id] = times[-200:]
                    break

        logger.debug(
            f"AutoLaneInference: {len(new_lanes)} lanes from "
            f"{len(self._completed_buffer)} tracks"
        )

    def _match_active_tracks(self, frame_element: FrameElement) -> None:
        """将活跃跟踪匹配到推断车道。"""
        if not self._inferred_lanes:
            return

        mature_tracks = mature_tracks_of(frame_element)
        if not mature_tracks:
            return

        for track_id, track in mature_tracks.items():
            # 需要足够的轨迹点才能匹配
            if len(track.trajectory_points) < 3:
                continue

            # 获取最近的bbox
            bbox = None
            if frame_element.tracked_xyxy and frame_element.id_list:
                try:
                    idx = frame_element.id_list.index(track_id)
                    bbox = frame_element.tracked_xyxy[idx]
                except (ValueError, IndexError):
                    continue

            if bbox is None:
                continue

            lane_id = match_active_track_to_lane(
                bbox, track.heading_angle, self._inferred_lanes
            )
            if lane_id:
                track.current_lane = lane_id

    def _compute_lane_stats(
        self, frame_element: FrameElement, current_time: float
    ) -> None:
        """计算各车道实时统计。"""
        if not self._inferred_lanes:
            return

        mature_tracks = mature_tracks_of(frame_element)

        for lane_id, lane in self._inferred_lanes.items():
            # 找到当前在此车道的活跃轨迹
            active_in_lane = []
            for track_id, track in mature_tracks.items():
                if track.current_lane == lane_id:
                    active_in_lane.append(track)

            lane.count = len(active_in_lane)

            # 平均车速
            if active_in_lane:
                speeds = [
                    t.avg_speed_kmh
                    for t in active_in_lane
                    if t.avg_speed_kmh is not None and t.avg_speed_kmh > 0
                ]
                lane.avg_speed_kmh = round(sum(speeds) / len(speeds), 1) if speeds else 0
            else:
                lane.avg_speed_kmh = 0

            # 排队检测
            stopped = [
                t
                for t in active_in_lane
                if t.avg_speed_kmh is not None
                and 0 <= t.avg_speed_kmh < self.queue_speed_threshold_kmh
            ]
            lane.stopped_count = len(stopped)

            # 排队长度（基于像素距离，有H时转世界坐标）
            lane.queue_length_m = self._compute_queue_length(stopped, frame_element)

            # 流量（辆/分钟）
            completion_times = self._lane_completion_times.get(lane_id, [])
            lane.flow_per_min = round(
                compute_flow_per_min(completion_times, self.flow_window_sec, current_time), 1
            )

            # 车头时距
            avg_headway, _ = compute_headway(completion_times, self.flow_window_sec, current_time)
            lane.avg_headway_sec = avg_headway

    def _compute_queue_length(
        self, stopped_tracks: list, frame_element: FrameElement
    ) -> float:
        """计算排队长度。"""
        if len(stopped_tracks) < 2:
            return 0.0

        # 获取停止车辆的bbox中心
        centers = []
        for track in stopped_tracks:
            if track.trajectory_points:
                last_pt = track.trajectory_points[-1]
                centers.append(np.array(last_pt))

        if len(centers) < 2:
            return 0.0

        # 计算最大像素距离
        max_dist_px = 0.0
        for i in range(len(centers)):
            for j in range(i + 1, len(centers)):
                dist = float(np.linalg.norm(centers[i] - centers[j]))
                max_dist_px = max(max_dist_px, dist)

        # 如果有H矩阵，转换为世界坐标
        H = frame_element.homography_matrix
        if is_valid_homography(H) and centers:
            pts_px = np.array(centers, dtype=np.float64)
            pts_world = pixel_to_world(pts_px, H)
            max_dist_m = 0.0
            for i in range(len(pts_world)):
                for j in range(i + 1, len(pts_world)):
                    dist = float(np.linalg.norm(pts_world[i] - pts_world[j]))
                    max_dist_m = max(max_dist_m, dist)
            return round(max_dist_m, 1)

        return round(max_dist_px, 1)  # 回退到像素距离
