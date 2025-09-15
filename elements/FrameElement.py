import numpy as np
import time

class FrameElement:
    # 包含有关视频流特定帧信息的类
    def __init__(
        self,
        source: str,
        frame: np.ndarray,
        timestamp: float,
        frame_num: float,
        roads_info: dict,
        frame_result: np.ndarray | None = None,
        detected_conf: list | None = None,
        detected_cls: list | None = None,
        detected_xyxy: list[list] | None = None,
        tracked_conf: list | None = None,
        tracked_cls: list | None = None,
        tracked_xyxy: list[list] | None = None,
        id_list: list | None = None,
        buffer_tracks: dict | None = None,
    ) -> None:
        self.source = source  # 视频路径或我们获取流的摄像机编号
        self.frame = frame  # BGR格式的帧
        self.timestamp = timestamp  # 自流开始以来的时间值（秒）
        self.frame_num = frame_num  # 流的帧号
        self.roads_info = roads_info  # 包含环形交叉路口相邻道路坐标的字典
        self.frame_result = frame_result  # 最终处理的帧
        self.timestamp_date = time.time()  # 处理帧时的时间（Unix格式，秒）
        # YOLO的输出结果：
        self.detected_conf = detected_conf  # 检测到的对象的置信度列表
        self.detected_cls = detected_cls  # 检测到的对象的类列表
        self.detected_xyxy = detected_xyxy  # 带xyxy框坐标的列表
        # 跟踪算法修正结果：
        self.tracked_conf = tracked_conf  # 检测到的对象的置信度列表
        self.tracked_cls = tracked_cls  # 检测到的对象的类列表
        self.tracked_xyxy = tracked_xyxy  # 带xyxy框坐标的列表    
        self.id_list = id_list  # 检测到的可跟踪对象ID列表
        # 帧的后处理：
        self.buffer_tracks = buffer_tracks  # 选定分析时间段内的活动跟踪缓冲区
        self.info = {}  # 结果统计字典（道路拥堵程度+车辆数量）
        self.send_info_of_frame_to_db = False  # 标志是否从该帧向数据库发送信息