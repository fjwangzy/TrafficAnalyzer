from pathlib import Path
import os
import logging
import cv2
import time

from elements.FrameElement import FrameElement
from elements.VideoEndBreakElement import VideoEndBreakElement

logger = logging.getLogger(__name__)


class VideoSaverNode:
    """视频流保存模块，支持持续保存主视频以及保存冲突事件截图"""

    def __init__(self, config: dict) -> None:
        self.fourcc = cv2.VideoWriter_fourcc("m", "p", "4", "v")
        self.fps = config["fps"]
        self.out_folder = config["out_folder"]
        self._cv2_writer = None

        # ── 冲突截图参数 ──
        self.save_conflict_clips = config.get("save_conflict_clips", False)
        self._last_snapshot_time = 0.0
        self._snapshot_cooldown_sec = 3.0  # 同一冲突截图间隔，避免重复保存

    def process(self, frame_element: FrameElement, save_video: bool = True) -> None:
        if isinstance(frame_element, VideoEndBreakElement):
            if self._cv2_writer is not None:
                self._cv2_writer.release()
                print(f"主视频已保存到文件夹 {self.out_folder}")
            return
        
        assert isinstance(
            frame_element, FrameElement
        ), f"VideoSaverNode | 输入元素格式不正确 {type(frame_element)}"

        source = frame_element.source
        frame = frame_element.frame_result

        if frame is not None:
            # 1. 保存主视频逻辑
            if save_video:
                if self._cv2_writer is None:
                    out_file_name = source
                    self._cv2_writer = self._init_cv2_writer(
                        frame_width=frame.shape[1],
                        frame_height=frame.shape[0],
                        out_file_name=out_file_name,
                        fps=self.fps,
                    )
                self._cv2_writer.write(frame)

            # 2. 保存冲突截图逻辑
            if self.save_conflict_clips:
                conflict_events = getattr(frame_element, "conflict_events", None)
                if conflict_events:
                    now = time.time()
                    # 冷却期内不重复保存
                    if now - self._last_snapshot_time < self._snapshot_cooldown_sec:
                        return

                    # 找到最严重的冲突事件
                    best_event = None
                    for event in conflict_events:
                        sev = event.get("severity")
                        if sev == "critical":
                            best_event = event
                            break
                        if sev == "warning" and best_event is None:
                            best_event = event

                    if best_event is not None:
                        # Keep the detector's long-standing conflict_*.jpg output.
                        # Managed event evidence is an additional content-addressed
                        # copy of this exact ShowNode result, not a replacement.
                        self._save_conflict_snapshot(frame, best_event)
                        self._last_snapshot_time = now

    def _save_conflict_snapshot(self, frame, event: dict) -> None:
        """保存一张带完整 TCC 叠加标注的冲突截图。"""
        Path(self.out_folder).mkdir(parents=True, exist_ok=True)

        timestamp_str = time.strftime("%Y%m%d_%H%M%S")
        motor_id = event.get("motor_id", "?")
        non_motor_id = event.get("non_motor_id", "?")
        severity = event.get("severity", "unknown")
        ttc = event.get("ttc_sec", 0.0)

        filename = f"conflict_{timestamp_str}_{severity}_ttc{ttc:.1f}s_m{motor_id}_nm{non_motor_id}.jpg"
        save_path = os.path.join(self.out_folder, filename)

        cv2.imwrite(save_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
        logger.info(f"冲突截图已保存: {save_path} | {severity} TTC={ttc:.1f}s")

    def _init_cv2_writer(
        self, frame_width: int, frame_height: int, out_file_name: str, fps: float
    ):
        out_file_name = os.path.basename(out_file_name)
        Path(self.out_folder).mkdir(parents=True, exist_ok=True)
        save_path = f"{self.out_folder}/{out_file_name}"
        writer = cv2.VideoWriter(
            save_path,
            cv2.VideoWriter_fourcc("m", "p", "4", "v"),
            fps,
            (frame_width, frame_height),
        )
        logger.info(f"Initialized VideoWriter for: {save_path}")
        return writer
