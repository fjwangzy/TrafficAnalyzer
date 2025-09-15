import os
import json
import time
import logging
from typing import Generator
import cv2

from elements.FrameElement import FrameElement
from elements.VideoEndBreakElement import VideoEndBreakElement

logger = logging.getLogger(__name__)


class VideoReader:
    """视频流帧读取模块"""

    def __init__(self, config: dict) -> None:
        self.video_pth = config["src"]
        self.video_source = f"Processing of {self.video_pth}"
        assert (
            os.path.isfile(self.video_pth)
            or type(self.video_pth) == int
            or "://" in self.video_pth
        ), f"VideoReader| 文件 {self.video_pth} 未找到"

        self.stream = cv2.VideoCapture(self.video_pth)

        self.skip_secs = config["skip_secs"]
        self.last_frame_timestamp = -1  # 初始化时特意设置为负值（临时解决方案）
        self.first_timestamp = 0  # 流第一帧时刻的时间值

        self.break_element_sent = False  # 是否已发送视频流中断元素

        # 设置处理摄像机视频时的宽度和高度（输入为int类型的摄像机编号）
        if type(self.video_pth) == int:
            self.stream.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
            self.stream.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

        # 从JSON文件读取数据（道路入口和出口坐标信息）
        with open(config["roads_info"], "r") as file:
            data_json = json.load(file)

        # 将道路坐标数据转换为int格式
        self.roads_info = {
            key: [int(value) for value in values] for key, values in data_json.items()
        }

    def process(self) -> Generator[FrameElement, None, None]:
        # 当前视频的帧号
        frame_number = 0

        while True:
            ret, frame = self.stream.read()
            if not ret:
                logger.warning("无法接收帧（流结束？）。退出...")
                if not self.break_element_sent:
                    self.break_element_sent = True
                    # 发送VideoEndBreakElement以指示流结束
                    yield VideoEndBreakElement(self.video_pth, self.last_frame_timestamp)
                break

            # 计算时间戳（如果从视频或摄像机提取，从0秒开始）
            if type(self.video_pth) == int or "://" in self.video_pth:
                # 从摄像机：
                if frame_number == 0:
                    self.first_timestamp = time.time()
                timestamp = time.time() - self.first_timestamp
            else:
                # 从视频：
                timestamp = self.stream.get(cv2.CAP_PROP_POS_MSEC) / 1000

            # 根据配置跳过一些帧
            if abs(self.last_frame_timestamp - timestamp) < self.skip_secs:
                continue

            self.last_frame_timestamp = timestamp

            frame_number += 1

            yield FrameElement(self.video_source, frame, timestamp, frame_number, self.roads_info)