"""检测管道统一入口 — 多进程并行 + 健康检查

唯一的管道启动脚本，整合了旧版 main_stream_optimized.py 和
main_stream_optimized_v2.py 的特性：

    进程 1 (proc_frame_reader_and_detection)
        VideoReader → DetectionTrackingNodes (YOLO)
        产出: 带检测结果的 FrameElement

    进程 2 (proc_tracker_update_and_calc)
        Homography → MotionCompensation → TrackerInfoUpdate →
        Speed → DirectionFlow → LaneDetection → LaneAnalysis → Trajectory →
        AutoLaneInference → ConflictDetection → CalcStatistics → KafkaProducer
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

from time import sleep, time
from multiprocessing import Process, Queue, shared_memory, resource_tracker
from queue import Empty
import numpy as np

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
from nodes.LaneDetectionNode import LaneDetectionNode
from nodes.AutoLaneInferenceNode import AutoLaneInferenceNode
from nodes.TrajectoryNode import TrajectoryNode
from nodes.ConflictDetectionNode import ConflictDetectionNode
from nodes.MotionCompensationNode import MotionCompensationNode
from nodes.GeoJsonExportNode import GeoJsonExportNode
from elements.VideoEndBreakElement import VideoEndBreakElement
from utils_local.utils import check_and_set_env_var

import logging
import logging.config
import yaml

PRINT_PROFILE_INFO = False

# 队列取数据超时(秒)：下游进程在 timeout 内未收到帧时检查上游是否存活
_QUEUE_GET_TIMEOUT = 10
_FRAME_QUEUE_MAXSIZE = max(1, int(os.environ.get("FRAME_QUEUE_MAXSIZE", "8")))


def _can_write_log_file(filename: str) -> bool:
    """Return whether a FileHandler target can be opened for append."""
    log_path = filename if os.path.isabs(filename) else os.path.join(os.getcwd(), filename)
    log_dir = os.path.dirname(log_path) or "."
    try:
        os.makedirs(log_dir, exist_ok=True)
        with open(log_path, "a", encoding="utf-8"):
            pass
    except OSError:
        return False
    return True


def _drop_unwritable_file_handlers(cfg: dict) -> dict:
    """Remove FileHandlers that cannot write in the current process cwd."""
    handlers = cfg.get("handlers") or {}
    removed = []
    for name, handler in list(handlers.items()):
        if handler.get("class") != "logging.FileHandler":
            continue
        filename = handler.get("filename")
        if filename and _can_write_log_file(filename):
            continue
        handlers.pop(name, None)
        removed.append(name)

    if not removed:
        return cfg

    root = cfg.get("root") or {}
    root["handlers"] = [h for h in root.get("handlers", []) if h not in removed]
    for logger_cfg in (cfg.get("loggers") or {}).values():
        logger_cfg["handlers"] = [
            h for h in logger_cfg.get("handlers", []) if h not in removed
        ]
    return cfg


def _setup_logging_in_subprocess():
    """在子进程中初始化日志配置。

    Hydra 的 dictConfig 仅在主进程生效，multiprocessing 子进程
    不会继承 root logger 的 handlers，需要手动重新加载。
    """
    config_path = os.path.join(
        os.path.dirname(__file__), "configs", "hydra", "job_logging", "custom.yaml"
    )
    if os.path.exists(config_path):
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        cfg = _drop_unwritable_file_handlers(cfg)
        logging.config.dictConfig(cfg)


def _is_pid_alive(pid: int) -> bool:
    """检查指定 PID 的进程是否存活。"""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _close_shared_memory_consumer(shm: shared_memory.SharedMemory) -> None:
    """Close a POSIX shared-memory handle without claiming unlink ownership.

    The reader creates each segment, the tracker reads it, and the show worker is
    the single owner that unlinks it after rendering.  Python registers every
    opened handle with the local process resource tracker; unless the two
    non-owning processes unregister their handles, an early reader EOF can unlink
    queued frames before the slower Kafka/show stages consume them.
    """
    shm.close()
    if os.name != "nt":
        try:
            resource_tracker.unregister(shm._name, "shared_memory")
        except (KeyError, ValueError):
            pass


def proc_frame_reader_and_detection(
    queue_out: Queue, config: dict, time_sleep_start: int,
):
    """进程 1: 视频读取 + YOLO 目标检测

    读取视频帧并执行 YOLO 推理，将带检测结果的 FrameElement 放入队列。
    队列满时阻塞等待（确保 MP4 不丢帧；RTSP 流由 reader 自适应帧率）。
    """
    _setup_logging_in_subprocess()
    sleep_message = f"系统预热中.. sleep({time_sleep_start})"
    for _ in tqdm(range(time_sleep_start), desc=sleep_message):
        sleep(1)
    video_reader = VideoReader(config["video_reader"], config.get("telemetry"))
    detection_node = DetectionTrackingNodes(config)
    for frame_element in video_reader.process():
        shm = None
        ts0 = time()
        frame_element = detection_node.process(frame_element)
        ts1 = time()
        ts1 = time()

        # EOF is a control-plane sentinel, not a frame payload. Forward it
        # before shared-memory handling because VideoEndBreakElement deliberately
        # does not initialize FrameElement.frame.
        if isinstance(frame_element, VideoEndBreakElement):
            queue_out.put(frame_element)
            break
        
        # ── 新增：共享内存优化，避免 4K 帧 pickle 序列化 ──
        if frame_element.frame is not None:
            # 创建共享内存
            shm = shared_memory.SharedMemory(create=True, size=frame_element.frame.nbytes)
            # 拷贝数据
            buffer = np.ndarray(frame_element.frame.shape, dtype=frame_element.frame.dtype, buffer=shm.buf)
            buffer[:] = frame_element.frame[:]
            # 记录元数据
            frame_element.shm_name = shm.name
            frame_element.shm_shape = frame_element.frame.shape
            frame_element.shm_dtype = str(frame_element.frame.dtype)
            # 清空真实的 frame 引用，防止被序列化
            frame_element.frame = None
            
        queue_out.put(frame_element)  # 阻塞等待，确保不丢帧
        if shm is not None:
            if os.name == "nt":
                # Windows requires one live handle until the downstream process attaches.
                if not hasattr(proc_frame_reader_and_detection, "shm_pool"):
                    proc_frame_reader_and_detection.shm_pool = []
                proc_frame_reader_and_detection.shm_pool.append(shm)
                if len(proc_frame_reader_and_detection.shm_pool) > _FRAME_QUEUE_MAXSIZE + 2:
                    proc_frame_reader_and_detection.shm_pool.pop(0).close()
            else:
                # POSIX keeps the named segment alive until ShowNode unlinks it. Closing
                # the creator handle prevents a 4K-frame leak that exhausts /dev/shm.
                _close_shared_memory_consumer(shm)
        if PRINT_PROFILE_INFO:
            print(
                f"PROC_FRAME_READER_AND_DETECTION: {(time()-ts0) * 1000:.0f} ms: "
                + f"detection_node {(ts1-ts0) * 1000:.0f} | "
                + f"put {(time()-ts1) * 1000:.0f}"
            )


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
    _setup_logging_in_subprocess()
    homography_node = HomographyCalibrationNode(config)
    motion_compensation_node = MotionCompensationNode(config)
    tracker_info_update_node = TrackerInfoUpdateNode(config)
    speed_node = SpeedEstimationNode(config)
    direction_flow_node = DirectionFlowNode(config)
    lane_detection_node = LaneDetectionNode(config)
    lane_analysis_node = LaneAnalysisNode(config)
    trajectory_node = TrajectoryNode(config)
    auto_lane_node = AutoLaneInferenceNode(config)
    conflict_node = ConflictDetectionNode(config)
    calc_statistics_node = CalcStatisticsNode(config)
    geojson_export_node = GeoJsonExportNode(config)
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
        
        # ── 新增：附加共享内存 ──
        _shm_tracker = None
        if hasattr(frame_element, "shm_name") and frame_element.shm_name:
            try:
                _shm_tracker = shared_memory.SharedMemory(name=frame_element.shm_name)
                frame_element.frame = np.ndarray(
                    frame_element.shm_shape, 
                    dtype=np.dtype(frame_element.shm_dtype), 
                    buffer=_shm_tracker.buf
                )
            except Exception as e:
                print(f"[proc_tracker] Failed to attach shm: {e}")
                frame_element.frame = None
        frame_element = homography_node.process(frame_element)
        frame_element = motion_compensation_node.process(frame_element)
        frame_element = tracker_info_update_node.process(frame_element)
        frame_element = speed_node.process(frame_element)
        frame_element = direction_flow_node.process(frame_element)
        frame_element = lane_detection_node.process(frame_element)
        frame_element = lane_analysis_node.process(frame_element)
        frame_element = trajectory_node.process(frame_element)
        frame_element = auto_lane_node.process(frame_element)
        frame_element = conflict_node.process(frame_element)
        frame_element = calc_statistics_node.process(frame_element)
        frame_element = geojson_export_node.process(frame_element)
        if send_info_kafka:
            frame_element = kafka_producer_node.process(frame_element)
        ts2 = time()
        
        # 传给进程 3 前，再次断开 frame 引用。
        if _shm_tracker is not None:
            frame_element.frame = None

        queue_out.put(frame_element)  # 阻塞等待，确保不丢帧
        if _shm_tracker is not None:
            if os.name == "nt":
                if not hasattr(proc_tracker_update_and_calc, "shm_pool"):
                    proc_tracker_update_and_calc.shm_pool = []
                proc_tracker_update_and_calc.shm_pool.append(_shm_tracker)
                if len(proc_tracker_update_and_calc.shm_pool) > _FRAME_QUEUE_MAXSIZE + 2:
                    proc_tracker_update_and_calc.shm_pool.pop(0).close()
            else:
                _close_shared_memory_consumer(_shm_tracker)
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
    _setup_logging_in_subprocess()
    show_node = ShowNode(config)
    save_video = config["pipeline"]["save_video"]
    save_conflict_clips = config["video_saver_node"].get("save_conflict_clips", False)
    show_in_web = config["pipeline"]["show_in_web"]
    if save_video or save_conflict_clips:
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
        
        # ── 新增：附加共享内存供渲染 ──
        _shm_show = None
        if hasattr(frame_element, "shm_name") and frame_element.shm_name:
            try:
                _shm_show = shared_memory.SharedMemory(name=frame_element.shm_name)
                # 直接使用原图进行渲染（就地修改），从而节约内存和拷贝
                frame_element.frame = np.ndarray(
                    frame_element.shm_shape, 
                    dtype=np.dtype(frame_element.shm_dtype), 
                    buffer=_shm_show.buf
                )
            except Exception as e:
                print(f"[proc_show] Failed to attach shm: {e}")
                frame_element.frame = None
        frame_element = show_node.process(frame_element)
        if save_video or save_conflict_clips:
            video_saver_node.process(frame_element, save_video=save_video)
        if show_in_web:
            video_server_node.process(frame_element)
        ts2 = time()
        
        # ── 新增：渲染结束，销毁共享内存 ──
        if _shm_show is not None:
            _shm_show.close()
            try:
                _shm_show.unlink()
            except Exception:
                pass
            frame_element.frame = None
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

    queue_detect_out = Queue(maxsize=_FRAME_QUEUE_MAXSIZE)
    queue_track_out = Queue(maxsize=_FRAME_QUEUE_MAXSIZE)

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

    processes = (reader_process, tracker_process, display_process)
    while display_process.exitcode is None:
        for process in processes:
            if process.exitcode not in (None, 0):
                logging.getLogger(__name__).error(
                    "Pipeline worker %s exited with code %s",
                    process.name,
                    process.exitcode,
                )
                for sibling in processes:
                    if sibling.is_alive():
                        sibling.terminate()
                for sibling in processes:
                    sibling.join(timeout=5)
                raise SystemExit(1)
        sleep(0.2)

    display_process.join()
    for process in (reader_process, tracker_process):
        process.join(timeout=5)


if __name__ == "__main__":
    ts = time()

    # 检查并设置环境变量（如果不存在）
    check_and_set_env_var("VIDEO_SRC", "test_videos/test_video.mp4")
    check_and_set_env_var("TOPIC_NAME", "uav_statistics_1")
    check_and_set_env_var("CAMERA_ID", 1)

    main()
    print(f"\n total time: {(time()-ts) / 60:.2} minute")
