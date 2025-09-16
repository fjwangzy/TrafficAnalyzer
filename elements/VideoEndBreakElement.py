from elements.FrameElement import FrameElement


class VideoEndBreakElement(FrameElement):
    """视频流中断元素"""

    def __init__(self, video_source, timestamp) -> None:
        """视频流结束元素。用于在帧结束时能够停止
        main_optimized.py 中的所有活动进程。

        Args:
            video_source (_type_): 图像源的 GUID
                （如果读取流，则为摄像机编号；否则为文件名）；
            timestamp (_type_): 读取图像的时间，以秒为单位。
        """
        self.video_source = video_source
        self.timestamp = timestamp