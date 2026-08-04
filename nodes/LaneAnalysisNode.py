import logging

from elements.FrameElement import FrameElement
from elements.VideoEndBreakElement import VideoEndBreakElement
from utils_local.homography import is_valid_homography
from utils_local.lane_geometry import assign_vehicle_to_lane, compute_queue_extent
from utils_local.track_lifecycle import mature_track_for_association, mature_tracks_of
from utils_local.utils import profile_time

logger = logging.getLogger(__name__)


class LaneAnalysisNode:
    """车道级分析节点：数据驱动，有标注且点位命中时输出车道级指标。

    无配置开关：
    - lane_polygons为空 → 跳过（无车道标注数据）
    - lane_polygons非空 → 遍历车辆bbox中心点，命中则输出lane_stats
    """

    def __init__(self, config: dict) -> None:
        cfg = config.get("lane_analysis", {})
        self.queue_speed_threshold_kmh = cfg.get("queue_speed_threshold_kmh", 5.0)
        self.queue_gap_threshold_m = cfg.get("queue_gap_threshold_m", 8.0)
        self._lane_polygons: dict | None = None  # 延迟加载

    def _load_lane_polygons(self, frame_element: FrameElement) -> dict:
        """从FrameElement加载车道多边形（延迟初始化）。空则返回空dict。"""
        if self._lane_polygons is not None:
            return self._lane_polygons
        lanes = getattr(frame_element, "lane_polygons", None)
        self._lane_polygons = lanes if lanes else {}
        return self._lane_polygons

    @profile_time
    def process(self, frame_element: FrameElement) -> FrameElement:
        if isinstance(frame_element, VideoEndBreakElement):
            return frame_element

        if (
            getattr(frame_element, "geo_reference_quality", None) is not None
            and not getattr(frame_element, "road_analytics_eligible", False)
        ):
            frame_element.lane_stats = None
            frame_element.queue_count = 0
            return frame_element

        if getattr(frame_element, "runtime_map_bundle", None):
            lane_stats: dict[str, dict] = {}
            for track in mature_tracks_of(frame_element).values():
                lane_id = getattr(track, "matched_lane_key", None)
                if not lane_id:
                    continue
                stats = lane_stats.setdefault(lane_id, {
                    "count": 0, "speed_total": 0.0, "queue_length_m": 0.0, "stopped_count": 0,
                    "map_version_id": frame_element.map_version_id,
                })
                stats["count"] += 1
                stats["speed_total"] += float(track.avg_speed_kmh or 0)
                if float(track.avg_speed_kmh or 0) < self.queue_speed_threshold_kmh:
                    stats["stopped_count"] += 1
            for stats in lane_stats.values():
                stats["avg_speed_kmh"] = round(stats.pop("speed_total") / stats["count"], 1)
            frame_element.lane_stats = lane_stats or None
            frame_element.lane_source = "channelized_map"
            return frame_element

        lane_polygons = self._load_lane_polygons(frame_element)
        if not lane_polygons:
            # 无车道标注数据 → 跳过，DirectionFlowNode已处理方向流量
            return frame_element

        H = frame_element.homography_matrix
        has_H = is_valid_homography(H)
        lane_stats = {}

        for lane_id, poly in lane_polygons.items():
            # 统计命中该车道的车辆
            vehicles_in_lane = []
            for i, track_id in enumerate(frame_element.id_list):
                bbox = frame_element.tracked_xyxy[i]
                lane_hit = assign_vehicle_to_lane(bbox, {lane_id: poly})
                if lane_hit == lane_id:
                    track = mature_track_for_association(frame_element, track_id)
                    if track is None:
                        continue
                    cx = (bbox[0] + bbox[2]) / 2.0
                    cy = (bbox[1] + bbox[3]) / 2.0
                    vehicles_in_lane.append({
                        "track_id": track_id,
                        "bbox_center_px": (cx, cy),
                        "speed_kmh": (
                            track.avg_speed_kmh
                            if track and track.avg_speed_kmh is not None
                            else 0
                        ),
                    })

                    # 记录到TrackElement
                    if track:
                        track.current_lane = lane_id

            if not vehicles_in_lane:
                continue  # 该车道无车辆命中，不输出

            # 车道级流量
            count = len(vehicles_in_lane)
            avg_speed = sum(v["speed_kmh"] for v in vehicles_in_lane) / count

            # 排队检测：速度 < 阈值
            stopped = [v for v in vehicles_in_lane if v["speed_kmh"] < self.queue_speed_threshold_kmh]
            queue_length = 0.0
            if stopped:
                queue_length = compute_queue_extent(
                    stopped, H if has_H else None
                )

            lane_stats[lane_id] = {
                "count": count,
                "avg_speed_kmh": round(avg_speed, 1),
                "queue_length_m": round(queue_length, 1),
                "stopped_count": len(stopped),
            }

        frame_element.lane_stats = lane_stats if lane_stats else None
        return frame_element
