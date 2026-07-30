"""道路拥堵程度的计算模块（统计计算）

改进点（审查报告 T-201）:
  道路数动态化 — 从 roads_info 获取实际道路数，不再硬编码 5 条。
"""
from collections import deque

import numpy as np

from elements.FrameElement import FrameElement
from elements.VideoEndBreakElement import VideoEndBreakElement
from utils_local.utils import profile_time


class CalcStatisticsNode:
    """道路拥堵程度的计算模块（统计计算）"""

    def __init__(self, config: dict) -> None:
        config_general = config["general"]

        self.time_buffer_analytics = config_general[
            "buffer_analytics"
        ]  # 分析缓冲区的时间大小（分钟）
        self.min_time_life_track = config_general[
            "min_time_life_track"
        ]  # 跟踪的最小生存时间（秒）
        self.count_cars_buffer_frames = config_general["count_cars_buffer_frames"]
        self.cars_buffer = deque(maxlen=self.count_cars_buffer_frames)  # 创建值缓冲区

    @profile_time
    def process(self, frame_element: FrameElement) -> FrameElement:
        # 如果输入是VideoEndBreakElement而不是FrameElement，则退出处理
        if isinstance(frame_element, VideoEndBreakElement):
            return frame_element
        assert isinstance(
            frame_element, FrameElement
        ), f"CalcStatisticsNode | 输入元素格式错误 {type(frame_element)}"

        quality_is_explicit = (
            getattr(frame_element, "geo_reference_quality", None) is not None
        )
        road_eligible = bool(
            getattr(frame_element, "road_analytics_eligible", False)
        ) if quality_is_explicit else True
        buffer_tracks = frame_element.buffer_tracks or {}
        self.cars_buffer.append(len(frame_element.buffer_tracks or {}))

        info_dictionary = {
            "cars_amount": round(np.mean(self.cars_buffer)),
            "trajectory_output_eligible": bool(
                getattr(frame_element, "trajectory_output_eligible", False)
            ),
            "geo_analytics_eligible": bool(
                getattr(frame_element, "geo_analytics_eligible", False)
            ),
            "road_analytics_eligible": road_eligible,
            "tcc_analytics_eligible": bool(
                getattr(frame_element, "tcc_analytics_eligible", False)
            ),
            "formal_analytics_eligible": road_eligible,
            "quality_reasons": (
                (getattr(frame_element, "geo_reference_quality", None) or {}).get(
                    "reasons", []
                )
            ),
        }

        # T-201: 动态道路数 — 从 roads_info 的 key 获取实际道路ID列表
        # Legacy road-region statistics are computed from their own ``roads_info``
        # facts.  The lane/link matcher must not suppress unrelated aggregates.
        road_ids = (
            sorted(frame_element.roads_info.keys()) if frame_element.roads_info else []
        )
        roads_activity = {rid: 0 for rid in road_ids}

        # 计算已经存在较长时间且有来源道路值的车辆数量
        for track_element in buffer_tracks.values():
            if (
                track_element.timestamp_last - track_element.timestamp_init_road
                > self.min_time_life_track
                and track_element.start_road is not None
            ):
                key = track_element.start_road
                if key in roads_activity:
                    roads_activity[key] += 1

        # 根据已知的缓冲区大小将值转换为车辆/分钟
        for key in roads_activity:
            roads_activity[key] /= self.time_buffer_analytics

        info_dictionary["roads_activity"] = roads_activity

        # 记录处理结果：
        frame_element.info = info_dictionary

        return frame_element
