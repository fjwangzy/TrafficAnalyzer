from pathlib import Path
import os
import logging
import cv2

from elements.FrameElement import FrameElement
from elements.VideoEndBreakElement import VideoEndBreakElement

logger = logging.getLogger(__name__)


class VideoSaverNode:
    """视频流保存模块"""

    def __init__(self, config: dict) -> None:
        self.fourcc = cv2.VideoWriter_fourcc("m", "p", "4", "v")
        self.fps = config["fps"]
        self.out_folder = config["out_folder"]
        self._cv2_writer = None

    def process(self, frame_element: FrameElement) -> None:
        # 如果是VideoEndBreakElement而不是FrameElement则退出处理
        if isinstance(frame_element, VideoEndBreakElement):
            self._cv2_writer.release()
            print(f"视频已保存到文件夹 {self.out_folder}")
            return
        assert isinstance(
            frame_element, FrameElement
        ), f"VideoSaverNode | 输入元素格式不正确 {type(frame_element)}"

        source = frame_element.source
        frame = frame_element.frame_result

        if frame is not None:
            out_file_name = source

            if self._cv2_writer is None:
                self._init_cv2_writer(
                    frame_width=frame.shape[1],
                    frame_height=frame.shape[0],
                    out_file_name=out_file_name,
                    fps=self.fps,
                )

            self._cv2_writer.write(frame)

    def _init_cv2_writer(
        self, frame_width: int, frame_height: int, out_file_name: str, fps: float
    ) -> None:
        """初始化cv2.VideoWriter以适当分辨率写入文件：

        Args:
            frame_width (int): 要写入视频的帧宽度。
            frame_height (int): 要写入视频的帧高度。
            out_file_name (str): 处理视频的来源
                (用于形成要写入视频的名称)。
            fps (float): 要写入视频的每秒帧数。
        """
        out_file_name = os.path.basename(out_file_name)
        Path(self.out_folder).mkdir(parents=True, exist_ok=True)
        save_path = f"{self.out_folder}/{out_file_name}"
        self._cv2_writer = cv2.VideoWriter(
            save_path,
            cv2.VideoWriter_fourcc("m", "p", "4", "v"),
            fps,
            (frame_width, frame_height),
        )
        logger.info(f"Saving out video in {save_path}")