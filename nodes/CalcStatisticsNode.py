from collections import deque
import numpy as np

from elements.FrameElement import FrameElement
from elements.VideoEndBreakElement import VideoEndBreakElement
from utils_local.utils import profile_time


class CalcStatisticsNode:
    """道路拥堵程度计算模块（统计计算）"""

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

        buffer_tracks = frame_element.buffer_tracks
        self.cars_buffer.append(len(frame_element.id_list))

        info_dictionary = {}
        info_dictionary["cars_amount"] = round(np.mean(self.cars_buffer))
        roads_activity = {
            1: 0,
            2: 0,
            3: 0,
            4: 0,
            5: 0,
        }  # 共5条道路（初始化为0）

        # 计算已经存在较长时间且有来源道路值的车辆数量
        for _, track_element in buffer_tracks.items():
            if (
                track_element.timestamp_last - track_element.timestamp_init_road
                > self.min_time_life_track
                and track_element.start_road is not None
            ):
                key = track_element.start_road
                roads_activity[key] += 1

        # 根据已知的缓冲区大小将值转换为车辆/分钟
        for key in roads_activity:
            roads_activity[key] /= self.time_buffer_analytics

        info_dictionary['roads_activity'] = roads_activity

        # 记录处理结果：
        frame_element.info = info_dictionary

        return frame_element