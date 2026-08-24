import os
import time
import logging
import threading
from typing import Generator
import cv2

from elements.FrameElement import FrameElement
from elements.VideoEndBreakElement import VideoEndBreakElement

logger = logging.getLogger(__name__)


class _LatestFrameStream:
    """Continuously drain a realtime decoder into one bounded latest-frame slot."""

    def __init__(self, stream) -> None:
        self.stream = stream
        self._condition = threading.Condition()
        self._latest = None
        self._sequence = 0
        self._stopped = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while True:
            ok, frame = self.stream.read()
            captured_at = time.time()
            with self._condition:
                if not ok:
                    self._stopped = True
                    self._condition.notify_all()
                    return
                self._sequence += 1
                self._latest = (self._sequence, captured_at, frame)
                self._condition.notify_all()

    def read_latest(self, previous_sequence: int) -> tuple[bool, object, int, float, int]:
        self.start()
        with self._condition:
            self._condition.wait_for(
                lambda: self._sequence > previous_sequence or self._stopped
            )
            if self._latest is None or self._sequence <= previous_sequence:
                return False, None, previous_sequence, time.time(), 0
            sequence, captured_at, frame = self._latest
            dropped = max(sequence - previous_sequence - 1, 0)
            return True, frame, sequence, captured_at, dropped


class VideoReader:
    """视频流帧读取模块"""

    def __init__(self, config: dict, telemetry_config: dict | None = None) -> None:
        self.video_pth = config["src"]
        self.video_source = f"Processing of {self.video_pth}"
        assert (
            os.path.isfile(self.video_pth)
            or isinstance(self.video_pth, int)
            or "://" in self.video_pth
        ), f"VideoReader| 文件 {self.video_pth} 未找到"

        self.stream = cv2.VideoCapture(self.video_pth)
        self._seekable_file = not isinstance(self.video_pth, int) and "://" not in str(self.video_pth)
        self._realtime = not self._seekable_file
        self._latest_stream = None
        if self._realtime:
            self.stream.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self._latest_stream = _LatestFrameStream(self.stream)
        self._total_source_frames = (
            int(self.stream.get(cv2.CAP_PROP_FRAME_COUNT)) if self._seekable_file else 0
        )

        self.skip_secs = config["skip_secs"]
        self.frame_stride = max(int(config.get("frame_stride", 1)), 1)
        self.seek_stride_threshold = max(
            int(config.get("seek_stride_threshold", 60)), 2
        )
        self.last_frame_timestamp = -1  # 初始化时特意设置为负值（临时解决方案）
        self.first_timestamp = 0  # 流第一帧时刻的时间值
        if self.frame_stride > 1:
            logger.info(
                "VideoReader: frame_stride=%s，每 %s 帧处理 1 帧",
                self.frame_stride,
                self.frame_stride,
            )

        self.break_element_sent = False  # 是否已发送视频流中断元素

        # 遥测订阅（可选）：支持MQTT实时订阅或文件回放
        self.telemetry_subscriber = None
        if telemetry_config and telemetry_config.get("enabled", False):
            source = telemetry_config.get("source", "mqtt")
            if source == "file":
                try:
                    from services.TelemetryFileReader import TelemetryFileReader
                    file_path = telemetry_config.get("file_path", "")
                    sync_tol = telemetry_config.get("sync_tolerance_sec", 0.5)
                    time_offset = telemetry_config.get("time_offset_sec", 0.0)
                    agl_policy = telemetry_config.get("agl_policy", "legacy_height")
                    interpolation_enabled = telemetry_config.get(
                        "interpolation_enabled", True
                    )
                    max_interpolation_gap = telemetry_config.get(
                        "max_interpolation_gap_sec", sync_tol
                    )
                    self.telemetry_subscriber = TelemetryFileReader(
                        file_path,
                        sync_tol,
                        time_offset,
                        agl_policy,
                        interpolation_enabled,
                        max_interpolation_gap,
                    )
                    self.telemetry_subscriber.start()
                    logger.info(f"VideoReader: 文件遥测加载已启动 ({file_path}, offset={time_offset}s)")
                except Exception as exc:
                    raise RuntimeError("VideoReader: file telemetry initialization failed") from exc
            elif source == "srt":
                try:
                    from services.SrtTelemetryParser import SrtTelemetryParser
                    file_path = telemetry_config.get("file_path", "")
                    sync_tol = telemetry_config.get("sync_tolerance_sec", 0.5)
                    time_offset = telemetry_config.get("time_offset_sec", 0.0)
                    self.telemetry_subscriber = SrtTelemetryParser(file_path, sync_tol, time_offset)
                    self.telemetry_subscriber.start()
                    logger.info(f"VideoReader: SRT遥测加载已启动 ({file_path}, offset={time_offset}s)")
                except Exception as exc:
                    raise RuntimeError("VideoReader: SRT telemetry initialization failed") from exc
            elif source == "mqtt":
                try:
                    from services.TelemetrySubscriber import TelemetrySubscriber
                    self.telemetry_subscriber = TelemetrySubscriber(telemetry_config)
                    self.telemetry_subscriber.start()
                    logger.info("VideoReader: MQTT遥测订阅已启动")
                except Exception as exc:
                    raise RuntimeError("VideoReader: MQTT telemetry initialization failed") from exc
            else:
                raise ValueError(f"VideoReader: unsupported telemetry source: {source}")

            if source in {"file", "srt"} and not self.telemetry_subscriber.is_connected:
                raise RuntimeError(f"VideoReader: {source} telemetry contains no records")

        # 设置处理摄像机视频时的宽度和高度（输入为int类型的摄像机编号）
        if isinstance(self.video_pth, int):
            self.stream.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
            self.stream.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

        # Runtime road truth is injected only through the immutable lane_verified bundle.
        self.roads_info = {}
        self.lane_polygons: dict | None = None
        self.extended_config: dict | None = None

    def process(self) -> Generator[FrameElement, None, None]:
        # 当前视频源的原始帧号；跳帧后 FrameElement.frame_num 仍保留原始帧号
        source_frame_number = 0
        realtime_sequence = 0

        while True:
            next_frame_number = source_frame_number + 1
            if not self._realtime and (next_frame_number - 1) % self.frame_stride != 0:
                if self._seekable_file and self.frame_stride >= self.seek_stride_threshold:
                    # 文件源可直接定位到下一个抽样帧；相比逐帧 grab，H.264 4K
                    # 回放不再为所有被跳过帧执行关键帧间解码。
                    skipped = self.frame_stride - ((next_frame_number - 1) % self.frame_stride)
                    target_zero_based = source_frame_number + skipped
                    if self._total_source_frames and target_zero_based >= self._total_source_frames:
                        logger.warning("无法接收帧（流结束？）。退出...")
                        if not self.break_element_sent:
                            self.break_element_sent = True
                            yield VideoEndBreakElement(self.video_pth, self.last_frame_timestamp)
                        break
                    if self.stream.set(cv2.CAP_PROP_POS_FRAMES, target_zero_based):
                        source_frame_number += skipped
                        continue
                # 跳过帧只推进解码器，不生成像素矩阵；4K 文件回放在高 stride
                # 下因此能真正加速，同时下一次 read() 仍得到正确的源帧号与时间戳。
                if not self.stream.grab():
                    logger.warning("无法接收帧（流结束？）。退出...")
                    if not self.break_element_sent:
                        self.break_element_sent = True
                        yield VideoEndBreakElement(self.video_pth, self.last_frame_timestamp)
                    break
                source_frame_number = next_frame_number
                continue

            if self._latest_stream is not None:
                ret, frame, realtime_sequence, captured_at, dropped = (
                    self._latest_stream.read_latest(realtime_sequence)
                )
                next_frame_number = realtime_sequence
            else:
                ret, frame = self.stream.read()
                captured_at = time.time()
                dropped = 0
            if not ret:
                logger.warning("无法接收帧（流结束？）。退出...")
                if not self.break_element_sent:
                    self.break_element_sent = True
                    # 发送VideoEndBreakElement以指示流结束
                    yield VideoEndBreakElement(self.video_pth, self.last_frame_timestamp)
                break

            if self._realtime and (realtime_sequence - 1) % self.frame_stride != 0:
                source_frame_number = realtime_sequence
                continue

            source_frame_number = next_frame_number

            # 计算时间戳（如果从视频或摄像机提取，从0秒开始）
            if isinstance(self.video_pth, int) or "://" in self.video_pth:
                # 从摄像机：
                if source_frame_number == 1:
                    self.first_timestamp = captured_at
                timestamp = captured_at - self.first_timestamp
            else:
                # 从视频：
                timestamp = self.stream.get(cv2.CAP_PROP_POS_MSEC) / 1000

            # 根据配置跳过一些帧
            if abs(self.last_frame_timestamp - timestamp) < self.skip_secs:
                continue

            self.last_frame_timestamp = timestamp

            frame_element = FrameElement(
                self.video_source, frame, timestamp, source_frame_number, self.roads_info
            )
            frame_element.source_capture_time = captured_at
            frame_element.source_is_realtime = self._realtime
            frame_element.source_drop_count = dropped
            frame_element.source_drop_reason = (
                "realtime_latest_frame_superseded" if dropped else None
            )
            frame_element.source_frame_stride = self.frame_stride
            # 注入车道多边形数据（供LaneAnalysisNode数据驱动使用）
            frame_element.lane_polygons = self.lane_polygons
            # 注入遥测数据（与帧时间戳同步）
            if self.telemetry_subscriber:
                telemetry_timestamp = captured_at if self._realtime else timestamp
                frame_element.telemetry = self.telemetry_subscriber.get_nearest(
                    telemetry_timestamp
                )
            yield frame_element
