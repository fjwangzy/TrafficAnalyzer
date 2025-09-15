import logging

from elements.FrameElement import FrameElement
from elements.TrackElement import TrackElement
from elements.VideoEndBreakElement import VideoEndBreakElement
from utils_local.utils import profile_time, intersects_central_point

logger = logging.getLogger("buffer_tracks")


class TrackerInfoUpdateNode:
    """活动跟踪更新模块"""

    def __init__(self, config: dict) -> None:
        config_general = config["general"]

        self.size_buffer_analytics = (
            config_general["buffer_analytics"] * 60
        )  # 分析缓冲区中的秒数
        # 添加最小生存时间，以便在计算统计信息时使用的是
        # 最近buffer_analytics分钟内的车辆：
        self.size_buffer_analytics += config_general["min_time_life_track"]
        self.buffer_tracks = {}  # 活动跟踪缓冲区

    @profile_time 
    def process(self, frame_element: FrameElement) -> FrameElement:
        # 如果输入是VideoEndBreakElement而不是FrameElement，则退出处理
        if isinstance(frame_element, VideoEndBreakElement):
            return frame_element
        assert isinstance(
            frame_element, FrameElement
        ), f"TrackerInfoUpdateNode | 输入元素格式错误 {type(frame_element)}"

        id_list = frame_element.id_list

        for i, id in enumerate(id_list):
            # 更新或创建新跟踪
            if id not in self.buffer_tracks:
                # 创建新键
                self.buffer_tracks[id] = TrackElement(
                    id=id,
                    timestamp_first=frame_element.timestamp,
                )
            else:
                # 更新最后检测时间
                self.buffer_tracks[id].update(frame_element.timestamp)

            # 寻找与道路多边形的第一次交集
            if self.buffer_tracks[id].start_road is None:
                self.buffer_tracks[id].start_road = intersects_central_point(
                    tracked_xyxy=frame_element.tracked_xyxy[i],
                    polygons=frame_element.roads_info,
                )
                # 检查函数是否最终提供了实际的道路编号：
                if self.buffer_tracks[id].start_road is not None:
                    # 然后保存该时刻：
                    self.buffer_tracks[id].timestamp_init_road = frame_element.timestamp

        # 如果id的生存时间> size_buffer_analytics，则从字典中删除旧id
        keys_to_remove = []
        for key, track_element in sorted(self.buffer_tracks.items()):  # 按键对元素进行排序
            if frame_element.timestamp - track_element.timestamp_first < self.size_buffer_analytics:
                break  # 如果time_delta大于check，则中断循环
            else:
                keys_to_remove.append(key)  # 添加要删除的键

        for key in keys_to_remove:
            self.buffer_tracks.pop(key)  # 从字典中删除元素
            logger.info(f"Removed tracker with key {key}")

        # 记录处理结果：
        frame_element.buffer_tracks = self.buffer_tracks

        return frame_element