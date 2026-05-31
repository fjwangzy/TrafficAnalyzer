"""检测管道统一入口 — 多进程并行 + 健康检查

唯一的管道启动脚本，整合了旧版 main_stream_optimized.py 和
main_stream_optimized_v2.py 的特性：

    进程 1 (proc_frame_reader_and_detection)
        VideoReader → DetectionTrackingNodes (YOLO)
        产出: 带检测结果的 FrameElement

    进程 2 (proc_tracker_update_and_calc)
        Homography → MotionCompensation → TrackerInfoUpdate →
        Speed → DirectionFlow → LaneAnalysis → Trajectory →
        ConflictDetection → CalcStatistics → KafkaProducer
        产出: 完整分析后的 FrameElement

    进程 3 (proc_show_node)
        ShowNode → VideoSaver / VideoServer (MJPEG)

健壮性 (来自 v2):
    - 每个下游进程通过 get(timeout) + is_alive() 检测上游崩溃
    - daemon 标志在 start() 前统一设置
    - VideoEndBreakElement 级联终止所有进程
"""
import os
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")  # MPS设备NMS等操作回退CPU

import signal
from time import sleep, time
from multiprocessing import Process, Queue
from queue import Empty

import hydra
from tqdm import tqdm

from nodes.VideoReader import VideoReader
from nodes.ShowNode import ShowNode
from nodes.VideoSaverNode import VideoSaverNode
from nodes.DetectionTrackingNodes import DetectionTrackingNodes
from nodes.TrackerInfoUpdateNode import TrackerInfoUpdateNode
from nodes.CalcStatisticsNode import CalcStatisticsNode
from nodes.FlaskServerVideoNode import VideoServer
from nodes.KafkaProducerNode import KafkaProducerNode
from nodes.HomographyCalibrationNode import HomographyCalibrationNode
from nodes.SpeedEstimationNode import SpeedEstimationNode
from nodes.DirectionFlowNode import DirectionFlowNode
from nodes.LaneAnalysisNode import LaneAnalysisNode
from nodes.TrajectoryNode import TrajectoryNode
from nodes.ConflictDetectionNode import ConflictDetectionNode
from nodes.MotionCompensationNode import MotionCompensationNode
from elements.VideoEndBreakElement import VideoEndBreakElement
from utils_local.utils import check_and_set_env_var

PRINT_PROFILE_INFO = False

# 队列取数据超时(秒)：下游进程在 timeout 内未收到帧时检查上游是否存活
_QUEUE_GET_TIMEOUT = 10


def _is_pid_alive(pid: int) -> bool:
    """检查指定 PID 的进程是否存活。"""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def proc_frame_reader_and_detection(
    queue_out: Queue, config: dict, time_sleep_start: int,
):
    """进程 1: 视频读取 + YOLO 目标检测

    读取视频帧并执行 YOLO 推理，将带检测结果的 FrameElement 放入队列。
    队列满时阻塞等待（确保 MP4 不丢帧；RTSP 流由 reader 自适应帧率）。
    """
    sleep_message = f"系统预热中.. sleep({time_sleep_start})"
    for _ in tqdm(range(time_sleep_start), desc=sleep_message):
        sleep(1)
    video_reader = VideoReader(config["video_reader"], config.get("telemetry"))
    detection_node = DetectionTrackingNodes(config)
    for frame_element in video_reader.process():
        ts0 = time()
        frame_element = detection_node.process(frame_element)
        ts1 = time()
        queue_out.put(frame_element)  # 阻塞等待，确保不丢帧
        if PRINT_PROFILE_INFO:
            print(
                f"PROC_FRAME_READER_AND_DETECTION: {(time()-ts0) * 1000:.0f} ms: "
                + f"detection_node {(ts1-ts0) * 1000:.0f} | "
                + f"put {(time()-ts1) * 1000:.0f}"
            )
        if isinstance(frame_element, VideoEndBreakElement):
            break


def proc_tracker_update_and_calc(
    queue_in: Queue, queue_out: Queue, config: dict,
    reader_pid: int,
):
    """进程 2: 追踪更新 + 全链路分析 + Kafka 发送

    从队列读取检测后的帧，依次执行单应性校正、运动补偿、轨迹更新、
    速度估算、方向流分析、车道分析、轨迹预测、冲突检测、统计计算，
    最后可选发送到 Kafka。

    健康检查：通过 get(timeout) + _is_pid_alive(reader_pid) 检测读取进程崩溃。
    """
    homography_node = HomographyCalibrationNode(config)
    motion_compensation_node = MotionCompensationNode(config)
    tracker_info_update_node = TrackerInfoUpdateNode(config)
    speed_node = SpeedEstimationNode(config)
    direction_flow_node = DirectionFlowNode(config)
    lane_analysis_node = LaneAnalysisNode(config)
    trajectory_node = TrajectoryNode(config)
    conflict_node = ConflictDetectionNode(config)
    calc_statistics_node = CalcStatisticsNode(config)
    send_info_kafka = config["pipeline"]["send_info_kafka"]
    if send_info_kafka:
        kafka_producer_node = KafkaProducerNode(config)
    while True:
        ts0 = time()
        try:
            frame_element = queue_in.get(timeout=_QUEUE_GET_TIMEOUT)
        except Empty:
            if not _is_pid_alive(reader_pid):
                print("[proc_tracker] reader process died, stopping")
                break
            continue
        ts1 = time()
        frame_element = homography_node.process(frame_element)
        frame_element = motion_compensation_node.process(frame_element)
        frame_element = tracker_info_update_node.process(frame_element)
        frame_element = speed_node.process(frame_element)
        frame_element = direction_flow_node.process(frame_element)
        frame_element = lane_analysis_node.process(frame_element)
        frame_element = trajectory_node.process(frame_element)
        frame_element = conflict_node.process(frame_element)
        frame_element = calc_statistics_node.process(frame_element)
        if send_info_kafka:
            frame_element = kafka_producer_node.process(frame_element)
        ts2 = time()
        queue_out.put(frame_element)  # 阻塞等待，确保不丢帧
        if PRINT_PROFILE_INFO:
            print(
                f"PROC_TRACKER_UPDATE_AND_CALC: {(time()-ts0) * 1000:.0f} ms: "
                + f"get {(ts1-ts0) * 1000:.0f} | "
                + f"nodes_inference {(ts2-ts1) * 1000:.0f} | "
                + f"put {(time()-ts2) * 1000:.0f}"
            )
        if isinstance(frame_element, VideoEndBreakElement):
            break


def proc_show_node(queue_in: Queue, config: dict, tracker_pid: int):
    """进程 3: 可视化渲染 + 视频保存 + MJPEG 串流

    健康检查：通过 get(timeout) + _is_pid_alive(tracker_pid) 检测追踪进程崩溃。
    """
    show_node = ShowNode(config)
    save_video = config["pipeline"]["save_video"]
    show_in_web = config["pipeline"]["show_in_web"]
    if save_video:
        video_saver_node = VideoSaverNode(config["video_saver_node"])
    if show_in_web:
        video_server_node = VideoServer(config)
    while True:
        ts0 = time()
        try:
            frame_element = queue_in.get(timeout=_QUEUE_GET_TIMEOUT)
        except Empty:
            if not _is_pid_alive(tracker_pid):
                print("[proc_show] tracker process died, stopping")
                break
            continue
        ts1 = time()
        frame_element = show_node.process(frame_element)
        if save_video:
            video_saver_node.process(frame_element)
        if show_in_web:
            video_server_node.process(frame_element)
        ts2 = time()
        if PRINT_PROFILE_INFO:
            print(
                f"PROC_SHOW_NODE: {(time()-ts0) * 1000:.0f} ms: "
                + f"get {(ts1-ts0) * 1000:.0f} | "
                + f"show_node {(ts2-ts1) * 1000:.0f}"
            )
        if isinstance(frame_element, VideoEndBreakElement):
            break


@hydra.main(version_base=None, config_path="configs", config_name="app_config")
def main(config) -> None:
    time_sleep_start = 5

    queue_detect_out = Queue(maxsize=50)
    queue_track_out = Queue(maxsize=50)

    # 顺序启动进程（每个下游进程需要上游 PID 做健康检查）
    reader_process = Process(
        target=proc_frame_reader_and_detection,
        args=(queue_detect_out, config, time_sleep_start),
        name="proc_reader_detection",
        daemon=True,
    )
    reader_process.start()

    tracker_process = Process(
        target=proc_tracker_update_and_calc,
        args=(queue_detect_out, queue_track_out, config, reader_process.pid),
        name="proc_tracker_calc",
        daemon=True,
    )
    tracker_process.start()

    display_process = Process(
        target=proc_show_node,
        args=(queue_track_out, config, tracker_process.pid),
        name="proc_show",
        daemon=True,
    )
    display_process.start()

    # 等待显示进程完成（它是管道末端，最后退出）
    display_process.join()


if __name__ == "__main__":
    ts = time()

    # 检查并设置环境变量（如果不存在）
    check_and_set_env_var("VIDEO_SRC", "test_videos/test_video.mp4")
    check_and_set_env_var("ROADS_JSON", "configs/entry_exit_lanes.json")
    check_and_set_env_var("TOPIC_NAME", "statistics_1")
    check_and_set_env_var("CAMERA_ID", 1)

    main()
    print(f"\n total time: {(time()-ts) / 60:.2} minute")