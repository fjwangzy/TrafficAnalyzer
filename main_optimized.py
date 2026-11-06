"""检测管道统一入口 — 多进程并行 + 健康检查

唯一的管道启动脚本，整合了旧版 main_stream_optimized.py 和
main_stream_optimized_v2.py 的特性：

    进程 1 (proc_frame_reader_and_detection)
        VideoReader → DetectionNode (YOLO only)
        产出: 带检测结果的 FrameElement

    进程 2 (proc_tracker_update_and_calc)
        Homography → MotionCompensation → FlightGeoReference →
        GroundTrajectoryTracker → TrackerInfoUpdate →
        Speed → DirectionFlow → LaneDetection → LaneAnalysis → Trajectory →
        AutoLaneInference → ConflictDetection → CalcStatistics → KafkaProducer
        产出: 完整分析后的 FrameElement

    进程 3 (proc_show_node)
        ShowNode → VideoSaver / VideoServer (MJPEG)

    生产原生四进程模式另外启用 proc_pipeline_egress：
        独占Kafka与本地归档，只接收新增轨迹点、只读事实及证据文件描述。
        tracker/show两路持久确认与EOF屏障完成后才结束管道。
        Mac/MPS默认仍使用三进程；FrameElement保持唯一逐帧载体。

健壮性 (来自 v2):
    - 每个下游进程通过 get(timeout) + is_alive() 检测上游崩溃
    - daemon 标志在 start() 前统一设置
    - VideoEndBreakElement 级联终止所有进程
"""

import os
import sys
import uuid

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")  # MPS设备NMS等操作回退CPU

from time import sleep, time
from multiprocessing import Process, Queue, Event, resource_tracker, shared_memory
from queue import Empty
import signal
import numpy as np

import hydra

from nodes.VideoReader import VideoReader
from nodes.ShowNode import ShowNode
from nodes.VideoSaverNode import VideoSaverNode
from nodes.DetectionNode import DetectionNode
from nodes.DetectionTrackingNodes import DetectionTrackingNodes
from nodes.FlightGeoReferenceNode import FlightGeoReferenceNode
from nodes.GroundTrajectoryTrackerNode import GroundTrajectoryTrackerNode
from nodes.PostTrackingWorldProjectionNode import PostTrackingWorldProjectionNode
from nodes.TrackerInfoUpdateNode import TrackerInfoUpdateNode
from nodes.CalcStatisticsNode import CalcStatisticsNode
from nodes.FlaskServerVideoNode import VideoServer
from nodes.KafkaProducerNode import KafkaProducerNode
from nodes.TccEvidencePublisherNode import TccEvidencePublisherNode
from nodes.EnforcementEvidencePublisherNode import EnforcementEvidencePublisherNode
from nodes.HomographyCalibrationNode import HomographyCalibrationNode
from nodes.ImageMotionEstimationNode import ImageMotionEstimationNode
from nodes.SpeedEstimationNode import SpeedEstimationNode
from nodes.DirectionFlowNode import DirectionFlowNode
from nodes.LaneAnalysisNode import LaneAnalysisNode
from nodes.LaneChangeDetectionNode import LaneChangeDetectionNode
from nodes.EnforcementDetectionNode import EnforcementDetectionNode
from nodes.LaneDetectionNode import LaneDetectionNode
from nodes.AutoLaneInferenceNode import AutoLaneInferenceNode
from nodes.TrajectoryNode import TrajectoryNode
from nodes.ConflictDetectionNode import ConflictDetectionNode
from nodes.MotionCompensationNode import MotionCompensationNode
from nodes.GeoJsonExportNode import GeoJsonExportNode
from nodes.RoadMapMatchingNode import RoadMapMatchingNode
from elements.VideoEndBreakElement import VideoEndBreakElement
from utils_local.utils import check_and_set_env_var
from utils_local.runtime_logging import configure_runtime_logging, run_stage, stage

import logging

# 队列取数据超时(秒)：下游进程在 timeout 内未收到帧时检查上游是否存活
_QUEUE_GET_TIMEOUT = 10
_FRAME_QUEUE_MAXSIZE = max(1, int(os.environ.get("FRAME_QUEUE_MAXSIZE", "8")))


def _setup_logging_in_subprocess():
    # Platform is the single rotating-file owner for all workers of a pipeline.
    configure_runtime_logging()


def _run_worker(function, *args):
    _setup_logging_in_subprocess()
    logger = logging.getLogger("pipeline.worker")
    logger.info("WORKER_START name=%s", function.__name__)
    four_process = os.environ.get("PIPELINE_EGRESS_ENABLED", "false").lower() == "true"
    if four_process:

        def interrupted(signum, _frame):
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            raise SystemExit(128 + signum)

        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGINT, interrupted)
    try:
        function(*args)
    except BaseException:
        if four_process:
            from services.PipelineEgress import preserve_client_pending

            preserve_client_pending()
        logger.exception("WORKER_FAILED name=%s", function.__name__)
        # An abort must not hang in multiprocessing's feeder finalizer after its
        # consumer died. Unconfirmed data is not declared delivered; the writer
        # journal and incomplete marker remain for diagnosis/recovery.
        for value in args:
            cancel = getattr(value, "cancel_join_thread", None)
            if callable(cancel):
                cancel()
        raise
    finally:
        logger.info("WORKER_EXIT name=%s", function.__name__)


def _is_pid_alive(pid: int) -> bool:
    """检查指定 PID 的进程是否存活。"""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _terminate_tracker_with_incomplete(kafka_producer_node, signum: int) -> None:
    """Durably expose an interrupted replay before the tracker exits."""

    try:
        signal_name = signal.Signals(signum).name.lower()
        kafka_producer_node.mark_replay_mission_incomplete(
            failure_reason=f"signal_{signal_name}"
        )
    finally:
        raise SystemExit(128 + signum)


def _close_shared_memory_consumer(shm: shared_memory.SharedMemory) -> None:
    """Close a POSIX shared-memory handle without claiming unlink ownership.

    The reader creates each segment, the tracker reads it, and the show worker is
    the single owner that unlinks it after rendering. Multiprocessing children
    share their parent's resource tracker, whose registry is a set rather than
    a handle reference count. Only unlink may unregister the segment; doing so
    on every reader/tracker close races the show worker and causes KeyError.
    """
    shm.close()


def proc_frame_reader_and_detection(
    queue_out: Queue,
    config: dict,
    time_sleep_start: int,
):
    """进程 1: 视频读取 + YOLO 目标检测

    读取视频帧并执行 YOLO 推理，将带检测结果的 FrameElement 放入队列。
    队列满时阻塞等待（确保 MP4 不丢帧；RTSP 流由 reader 自适应帧率）。
    """
    _setup_logging_in_subprocess()
    logging.getLogger("pipeline.reader").info("WARMUP wait_sec=%s", time_sleep_start)
    sleep(time_sleep_start)
    video_reader = run_stage(
        "init.video_reader",
        VideoReader,
        config["video_reader"],
        config.get("telemetry"),
    )
    detection_node = (
        run_stage("init.legacy_detection", DetectionTrackingNodes, config)
        if config.get("tracking_profile", "hover_cruise_v1") == "hover_only_legacy"
        else run_stage("init.detection", DetectionNode, config)
    )
    stop_requested = False
    last_timestamp = 0.0
    def request_stop(_signum, _frame):
        nonlocal stop_requested
        stop_requested = True
    if hasattr(signal, 'SIGUSR1'):
        signal.signal(signal.SIGUSR1, request_stop)
    try:
        frames = iter(video_reader.process())
        while True:
            if stop_requested:
                eof = VideoEndBreakElement(config['video_reader'].get('video_source', 'manual_stop'), last_timestamp)
                eof.termination_reason = 'manual_stop'
                run_stage('queue.detect.put', queue_out.put, eof)
                break
            frame_element = run_stage("reader.decode", next, frames, None)
            if frame_element is None:
                break
            last_timestamp = float(frame_element.timestamp)
            shm = None
            with stage(
                "reader.detection", frame=getattr(frame_element, "frame_num", "eof")
            ):
                frame_element = detection_node.process(frame_element)

            # EOF is a control-plane sentinel, not a frame payload. Forward it
            # before shared-memory handling because VideoEndBreakElement deliberately
            # does not initialize FrameElement.frame.
            if isinstance(frame_element, VideoEndBreakElement):
                run_stage("queue.detect.put", queue_out.put, frame_element)
                break

            # ── 新增：共享内存优化，避免 4K 帧 pickle 序列化 ──
            if frame_element.frame is not None:
                with stage("reader.shared_memory", bytes=frame_element.frame.nbytes):
                    # 创建共享内存
                    shm = shared_memory.SharedMemory(
                        create=True,
                        size=frame_element.frame.nbytes,
                        name=(
                            os.environ.get(
                                "UAV_SHM_PREFIX", "uavf_" + str(os.getpid()) + "_"
                            )
                            + uuid.uuid4().hex[:12]
                        )
                        if sys.platform == "linux"
                        else None,
                    )
                    # 拷贝数据
                    buffer = np.ndarray(
                        frame_element.frame.shape,
                        dtype=frame_element.frame.dtype,
                        buffer=shm.buf,
                    )
                    buffer[:] = frame_element.frame[:]
                    # 记录元数据
                    frame_element.shm_name = shm.name
                    frame_element.shm_shape = frame_element.frame.shape
                    frame_element.shm_dtype = str(frame_element.frame.dtype)
                    # 清空真实的 frame 引用，防止被序列化
                    frame_element.frame = None

            run_stage("queue.detect.put", queue_out.put, frame_element)
            if shm is not None:
                if os.name == "nt":
                    # Windows requires one live handle until the downstream process attaches.
                    if not hasattr(proc_frame_reader_and_detection, "shm_pool"):
                        proc_frame_reader_and_detection.shm_pool = []
                    proc_frame_reader_and_detection.shm_pool.append(shm)
                    if (
                        len(proc_frame_reader_and_detection.shm_pool)
                        > _FRAME_QUEUE_MAXSIZE + 2
                    ):
                        proc_frame_reader_and_detection.shm_pool.pop(0).close()
                else:
                    # POSIX keeps the named segment alive until ShowNode unlinks it. Closing
                    # the creator handle prevents a 4K-frame leak that exhausts /dev/shm.
                    _close_shared_memory_consumer(shm)
    finally:
        close = getattr(detection_node, "close", None)
        if close is not None:
            close()


def proc_tracker_update_and_calc(
    queue_in: Queue,
    queue_out: Queue,
    config: dict,
    reader_pid: int,
    egress_queue=None,
    egress_acks=None,
    egress_pid=None,
):
    """进程 2: 追踪更新 + 全链路分析 + Kafka 发送

    从队列读取检测后的帧，依次执行单应性校正、运动补偿、轨迹更新、
    速度估算、方向流分析、车道分析、轨迹预测、冲突检测、统计计算，
    最后可选发送到 Kafka。

    健康检查：通过 get(timeout) + _is_pid_alive(reader_pid) 检测读取进程崩溃。
    """
    _setup_logging_in_subprocess()
    four_process = egress_queue is not None
    homography_node = run_stage("init.homography", HomographyCalibrationNode, config)
    motion_compensation_node = run_stage(
        "init.motion_compensation", MotionCompensationNode, config
    )
    cruise_tracking = (
        config.get("tracking_profile", "hover_cruise_v1") == "hover_cruise_v1"
    )
    image_motion_node = (
        run_stage("init.image_motion", ImageMotionEstimationNode, config)
        if cruise_tracking
        else None
    )
    flight_geo_reference_node = (
        run_stage("init.geo_reference", FlightGeoReferenceNode, config)
        if cruise_tracking
        else None
    )
    ground_trajectory_tracker_node = (
        run_stage("init.image_tracker", GroundTrajectoryTrackerNode, config)
        if cruise_tracking
        else None
    )
    post_tracking_world_projection_node = (
        run_stage("init.world_projection", PostTrackingWorldProjectionNode, config)
        if cruise_tracking
        else None
    )
    tracker_info_update_node = run_stage(
        "init.tracker_info", TrackerInfoUpdateNode, config
    )
    speed_node = run_stage("init.speed", SpeedEstimationNode, config)
    direction_flow_node = run_stage("init.direction", DirectionFlowNode, config)
    road_features = os.environ.get("ROAD_FEATURES_ENABLED", "true").lower() != "false"
    lane_detection_node = (
        run_stage("init.lane_detection", LaneDetectionNode, config)
        if road_features
        else None
    )
    lane_analysis_node = (
        run_stage("init.lane_analysis", LaneAnalysisNode, config)
        if road_features
        else None
    )
    trajectory_node = run_stage("init.trajectory", TrajectoryNode, config)
    lane_change_node = run_stage("init.lane_change", LaneChangeDetectionNode, config)
    enforcement_node = run_stage("init.enforcement", EnforcementDetectionNode, config)
    road_map_matching_node = run_stage("init.map_matching", RoadMapMatchingNode, config)
    auto_lane_node = (
        run_stage("init.auto_lane", AutoLaneInferenceNode, config)
        if road_features
        else None
    )
    conflict_node = run_stage("init.conflict", ConflictDetectionNode, config)
    calc_statistics_node = run_stage("init.statistics", CalcStatisticsNode, config)
    geojson_export_node = (
        None if four_process else run_stage("init.geojson", GeoJsonExportNode, config)
    )
    send_info_kafka = config["pipeline"]["send_info_kafka"]
    four_process = egress_queue is not None
    if four_process:
        from services.PipelineEgress import (
            EgressClient,
            SnapshotScheduler,
            pipeline_egress_root,
        )

        kafka_producer_node = EgressClient(
            "tracker",
            egress_queue,
            egress_acks,
            timeout=float(config["pipeline"].get("egress_timeout_sec", 10.0)),
            alive=lambda: _is_pid_alive(egress_pid),
            failure_spool=pipeline_egress_root(),
            optimized_views=bool(
                config["pipeline"].get("transport_views_optimized", True)
            ),
            bounded_history=cruise_tracking and not road_features,
            history_tail_points=int(config['pipeline'].get('online_history_tail_points',128)),
        )
        snapshot_scheduler = SnapshotScheduler(config) if send_info_kafka else None
    elif send_info_kafka:
        kafka_producer_node = run_stage("init.kafka", KafkaProducerNode, config)
    if send_info_kafka or four_process:

        def tracker_interrupted(signum, _frame):
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            _terminate_tracker_with_incomplete(kafka_producer_node, signum)

        signal.signal(signal.SIGTERM, tracker_interrupted)
        signal.signal(signal.SIGINT, tracker_interrupted)
    while True:
        with stage("queue.detect.get"):
            try:
                frame_element = queue_in.get(timeout=_QUEUE_GET_TIMEOUT)
            except Empty:
                if not _is_pid_alive(reader_pid):
                    logging.getLogger("pipeline.tracker").error(
                        "Reader process died pid=%s", reader_pid
                    )
                    if send_info_kafka or four_process:
                        kafka_producer_node.mark_replay_mission_incomplete(
                            failure_reason="reader_process_died"
                        )
                    break
                continue

        # ── 新增：附加共享内存 ──
        _shm_tracker = None
        if hasattr(frame_element, "shm_name") and frame_element.shm_name:
            try:
                _shm_tracker = shared_memory.SharedMemory(name=frame_element.shm_name)
                frame_element.frame = np.ndarray(
                    frame_element.shm_shape,
                    dtype=np.dtype(frame_element.shm_dtype),
                    buffer=_shm_tracker.buf,
                )
            except Exception:
                logging.getLogger("pipeline.tracker").exception(
                    "Shared memory attach failed"
                )
                frame_element.frame = None
        if cruise_tracking:
            frame_element = run_stage(
                "tracker.image_motion", image_motion_node.process, frame_element
            )
            # ByteTrack is a pure image-space association stage.  It deliberately
            # runs before every H/ENU/map operation so projection error cannot
            # change identities.
            frame_element = run_stage(
                "tracker.association",
                ground_trajectory_tracker_node.process,
                frame_element,
            )
        frame_element = run_stage(
            "tracker.homography", homography_node.process, frame_element
        )
        frame_element = run_stage(
            "tracker.motion_compensation",
            motion_compensation_node.process,
            frame_element,
        )
        if cruise_tracking:
            frame_element = run_stage(
                "tracker.geo_reference",
                flight_geo_reference_node.process,
                frame_element,
            )
            frame_element = run_stage(
                "tracker.world_projection",
                post_tracking_world_projection_node.process,
                frame_element,
            )
        frame_element = run_stage(
            "tracker.info", tracker_info_update_node.process, frame_element
        )
        frame_element = run_stage("tracker.speed", speed_node.process, frame_element)
        frame_element = run_stage(
            "tracker.direction", direction_flow_node.process, frame_element
        )
        if lane_detection_node is not None:
            frame_element = run_stage(
                "tracker.lane_detection", lane_detection_node.process, frame_element
            )
        frame_element = run_stage(
            "tracker.trajectory", trajectory_node.process, frame_element
        )
        frame_element = run_stage(
            "tracker.lane_change", lane_change_node.process, frame_element
        )
        frame_element = run_stage(
            "tracker.map_matching", road_map_matching_node.process, frame_element
        )
        frame_element = run_stage(
            "tracker.enforcement", enforcement_node.process, frame_element
        )
        if lane_analysis_node is not None:
            frame_element = run_stage(
                "tracker.lane_analysis", lane_analysis_node.process, frame_element
            )
        if auto_lane_node is not None:
            frame_element = run_stage(
                "tracker.auto_lane", auto_lane_node.process, frame_element
            )
        frame_element = run_stage(
            "tracker.conflict", conflict_node.process, frame_element
        )
        frame_element = run_stage(
            "tracker.statistics", calc_statistics_node.process, frame_element
        )
        if isinstance(frame_element, VideoEndBreakElement):
            projection_flush = (
                post_tracking_world_projection_node.last_flush_result
                if post_tracking_world_projection_node is not None
                else None
            ) or {}
            termination_reason = getattr(frame_element, "termination_reason", None) or projection_flush.get(
                "termination_reason", "natural_eof"
            )
            flush_frame = tracker_info_update_node.flush(
                timestamp=frame_element.timestamp,
                reason=termination_reason,
                terminated_track_ids=projection_flush.get("terminated_track_ids"),
            )
            if flush_frame is not None:
                if four_process:
                    kafka_producer_node.closed(flush_frame.completed_tracks)
                else:
                    geojson_export_node.process(flush_frame)
                    if send_info_kafka:
                        kafka_producer_node.publish_completed_tracks(flush_frame)
            if send_info_kafka and not four_process:
                kafka_producer_node.seal_replay_mission(
                    frame_element,
                    termination_reason=termination_reason,
                )
        display_frame = frame_element
        if four_process:
            if isinstance(frame_element, VideoEndBreakElement):
                kafka_producer_node.finish(frame_element)
            else:
                if snapshot_scheduler is not None:
                    snapshot_scheduler.apply(frame_element)
                display_frame = run_stage(
                    "tracker.egress_delta", kafka_producer_node.frame, frame_element
                )
        else:
            frame_element = run_stage(
                "tracker.geojson", geojson_export_node.process, frame_element
            )
            if send_info_kafka:
                frame_element = run_stage(
                    "tracker.kafka_archive", kafka_producer_node.process, frame_element
                )
            # Analysis, archive and Kafka above keep the complete history. The
            # asynchronous Queue feeder must only see an owned display view:
            # otherwise every frame re-pickles all past points while the tracker
            # continues mutating them, and transfer cost grows with run length.
            from services.PipelineEgress import freeze_display_frame

            display_frame = run_stage(
                "tracker.render_snapshot", freeze_display_frame, frame_element
            )

        # 传给进程 3 前，再次断开 frame 引用。
        if _shm_tracker is not None:
            frame_element.frame = None

        run_stage("queue.track.put", queue_out.put, display_frame)
        if _shm_tracker is not None:
            if os.name == "nt":
                if not hasattr(proc_tracker_update_and_calc, "shm_pool"):
                    proc_tracker_update_and_calc.shm_pool = []
                proc_tracker_update_and_calc.shm_pool.append(_shm_tracker)
                if (
                    len(proc_tracker_update_and_calc.shm_pool)
                    > _FRAME_QUEUE_MAXSIZE + 2
                ):
                    proc_tracker_update_and_calc.shm_pool.pop(0).close()
            else:
                _close_shared_memory_consumer(_shm_tracker)
        if isinstance(frame_element, VideoEndBreakElement):
            break


def _requires_render_output(config: dict) -> bool:
    return bool(
        config["pipeline"]["save_video"]
        or config["video_saver_node"].get("save_conflict_clips", False)
        or config["pipeline"]["show_in_web"]
        or config["show_node"].get("imshow", False)
    )


def proc_show_node(
    queue_in: Queue,
    config: dict,
    tracker_pid: int,
    egress_queue=None,
    egress_acks=None,
    egress_pid=None,
):
    """进程 3: 可视化渲染 + TCC 证据发布 + 视频保存 + MJPEG 串流

    健康检查：通过 get(timeout) + _is_pid_alive(tracker_pid) 检测追踪进程崩溃。
    """
    _setup_logging_in_subprocess()
    save_video = config["pipeline"]["save_video"]
    save_conflict_clips = config["video_saver_node"].get("save_conflict_clips", False)
    show_in_web = config["pipeline"]["show_in_web"]
    send_info_kafka = config["pipeline"]["send_info_kafka"]
    render_output = _requires_render_output(config)
    if render_output or send_info_kafka:
        show_node = run_stage("init.show", ShowNode, config)
    if save_video or save_conflict_clips:
        video_saver_node = run_stage(
            "init.video_saver", VideoSaverNode, config["video_saver_node"]
        )
    four_process = egress_queue is not None
    if four_process:
        from services.PipelineEgress import EgressClient, pipeline_egress_root
        from nodes.EgressEvidenceNode import EgressEvidenceNode

        image_egress = EgressClient(
            "show",
            egress_queue,
            egress_acks,
            timeout=float(config["pipeline"].get("egress_timeout_sec", 10.0)),
            alive=lambda: _is_pid_alive(egress_pid),
            failure_spool=pipeline_egress_root(),
        )
        egress_evidence_node = EgressEvidenceNode(config, image_egress)
    if send_info_kafka and not four_process:
        tcc_evidence_publisher_node = run_stage(
            "init.tcc_evidence", TccEvidencePublisherNode, config
        )
        enforcement_evidence_publisher_node = (
            run_stage(
                "init.enforcement_evidence", EnforcementEvidencePublisherNode, config
            )
            if "kafka_producer_node" in config
            else None
        )
    if show_in_web:
        video_server_node = run_stage("init.mjpeg", VideoServer, config)
    while True:
        with stage("queue.track.get"):
            try:
                frame_element = queue_in.get(timeout=_QUEUE_GET_TIMEOUT)
            except Empty:
                if not _is_pid_alive(tracker_pid):
                    logging.getLogger("pipeline.show").error(
                        "Tracker process died pid=%s", tracker_pid
                    )
                    break
                continue

        pending_tcc = bool(
            not isinstance(frame_element, VideoEndBreakElement)
            and getattr(
                frame_element,
                "conflict_events" if four_process else "pending_tcc_envelopes",
                None,
            )
        )
        pending_enforcement = bool(
            not isinstance(frame_element, VideoEndBreakElement)
            and getattr(
                frame_element,
                "enforcement_clues"
                if four_process
                else "pending_enforcement_envelopes",
                None,
            )
        )
        pending_tcc = pending_tcc and (send_info_kafka or not four_process)
        pending_enforcement = pending_enforcement and (
            send_info_kafka or not four_process
        )
        needs_render = render_output or pending_tcc or pending_enforcement
        needs_pixels = needs_render or bool(
            getattr(frame_element, "annotation_snapshot_requested", False)
        )
        original_tcc_frame = None

        # 只有确实需要预览/保存时才渲染 4K 标注。批量数据回放仍消费并释放
        # shared memory，但跳过成本很高的框、标签和轨迹绘制。
        _shm_show = None
        if hasattr(frame_element, "shm_name") and frame_element.shm_name:
            try:
                _shm_show = shared_memory.SharedMemory(name=frame_element.shm_name)
                if needs_pixels:
                    # 直接使用原图进行渲染（就地修改），从而节约内存和拷贝
                    frame_element.frame = np.ndarray(
                        frame_element.shm_shape,
                        dtype=np.dtype(frame_element.shm_dtype),
                        buffer=_shm_show.buf,
                    )
            except Exception:
                logging.getLogger("pipeline.show").exception(
                    "Shared memory attach failed"
                )
                frame_element.frame = None
        if four_process:
            egress_evidence_node.capture_annotation(frame_element)
        if (pending_tcc or pending_enforcement) and frame_element.frame is not None:
            # ShowNode renders in place. Preserve the exact unannotated source before
            # rendering so the evidence pair is raw input + the real detector output.
            original_tcc_frame = frame_element.frame.copy()
        if needs_render:
            frame_element = run_stage("show.render", show_node.process, frame_element)
        if save_video or save_conflict_clips:
            run_stage(
                "show.video_save",
                video_saver_node.process,
                frame_element,
                save_video=save_video,
            )
        if four_process:
            frame_element = run_stage(
                "show.egress_evidence",
                egress_evidence_node.process,
                frame_element,
                original_tcc_frame,
            )
        if send_info_kafka and not four_process:
            if pending_tcc and original_tcc_frame is not None:
                frame_element.frame = original_tcc_frame
            frame_element = run_stage(
                "show.tcc_evidence", tcc_evidence_publisher_node.process, frame_element
            )
            if enforcement_evidence_publisher_node is not None:
                frame_element = run_stage(
                    "show.enforcement_evidence",
                    enforcement_evidence_publisher_node.process,
                    frame_element,
                )
        if show_in_web:
            run_stage("show.mjpeg_encode", video_server_node.process, frame_element)

        # ── 新增：渲染结束，销毁共享内存 ──
        if _shm_show is not None:
            _shm_show.close()
            try:
                _shm_show.unlink()
            except Exception:
                pass
            frame_element.frame = None
        if isinstance(frame_element, VideoEndBreakElement):
            break


def proc_pipeline_egress(queue, tracker_acks, show_acks, config, ready_event=None):
    from services.PipelineEgress import run_egress, pipeline_egress_root

    def interrupted(signum, _frame):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        raise InterruptedError("egress signal " + str(signum))

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    root = pipeline_egress_root()
    run_egress(queue, tracker_acks, show_acks, config, root, ready_event)


@hydra.main(version_base=None, config_path="configs", config_name="app_config")
def main(config) -> None:
    configure_runtime_logging()
    logging.getLogger("pipeline").info(
        "PIPELINE_START tracking_profile=%s queue_maxsize=%s transport_views_optimized=%s",
        config.get("tracking_profile"),
        _FRAME_QUEUE_MAXSIZE,
        bool(config.get("pipeline", {}).get("transport_views_optimized", True)),
    )
    time_sleep_start = 5
    shm_prefix = "uavf_" + uuid.uuid4().hex[:12] + "_"
    os.environ["UAV_SHM_PREFIX"] = shm_prefix
    os.environ["PIPELINE_EGRESS_ENABLED"] = str(
        bool(config.get("pipeline", {}).get("egress_enabled", False))
    ).lower()
    os.environ["HISTORY_SAMPLING_ENABLED"] = str(
        bool(config.get("history_sampling", {}).get("enabled", False))
    ).lower()

    if os.name == "posix":
        # Linux fork workers must inherit one tracker before creating shared frames.
        resource_tracker.ensure_running()
    queue_detect_out = Queue(maxsize=_FRAME_QUEUE_MAXSIZE)
    queue_track_out = Queue(maxsize=_FRAME_QUEUE_MAXSIZE)

    four_process = bool(config.get("pipeline", {}).get("egress_enabled", False))
    egress_args = ()
    egress_process = None
    if four_process:
        egress_queue = Queue(
            maxsize=int(config["pipeline"].get("egress_queue_maxsize", 32))
        )
        tracker_acks = Queue()
        show_acks = Queue()
        egress_ready = Event()
        egress_process = Process(
            target=_run_worker,
            args=(
                proc_pipeline_egress,
                egress_queue,
                tracker_acks,
                show_acks,
                config,
                egress_ready,
            ),
            name="proc_egress",
            daemon=True,
        )
        egress_process.start()
        log = logging.getLogger("pipeline.startup")
        begun = time()
        deadline = begun + float(
            config["pipeline"].get("egress_startup_timeout_sec", 120.0)
        )
        wait_at = begun + 5
        log.info("STAGE_BEGIN stage=init.egress_ready")
        while not egress_ready.wait(0.1):
            if egress_process.exitcode is not None:
                raise RuntimeError("archive worker failed before readiness")
            if time() > deadline:
                egress_process.terminate()
                egress_process.join(10)
                if egress_process.is_alive():
                    egress_process.kill()
                    egress_process.join(5)
                raise TimeoutError("archive startup timed out")
            if time() >= wait_at:
                log.info(
                    "STAGE_WAIT stage=init.egress_ready elapsed_ms=%.1f",
                    (time() - begun) * 1000,
                )
                wait_at = time() + 30
        log.info(
            "STAGE_END stage=init.egress_ready elapsed_ms=%.1f", (time() - begun) * 1000
        )
        egress_args = (egress_queue, tracker_acks, egress_process.pid)

    # 顺序启动进程（每个下游进程需要上游 PID 做健康检查）
    reader_process = Process(
        target=_run_worker,
        args=(
            proc_frame_reader_and_detection,
            queue_detect_out,
            config,
            time_sleep_start,
        ),
        name="proc_reader_detection",
        daemon=True,
    )
    reader_process.start()

    tracker_process = Process(
        target=_run_worker,
        args=(
            proc_tracker_update_and_calc,
            queue_detect_out,
            queue_track_out,
            config,
            reader_process.pid,
            *egress_args,
        ),
        name="proc_tracker_calc",
        daemon=True,
    )
    tracker_process.start()

    display_process = Process(
        target=_run_worker,
        args=(
            proc_show_node,
            queue_track_out,
            config,
            tracker_process.pid,
            *((egress_queue, show_acks, egress_process.pid) if four_process else ()),
        ),
        name="proc_show",
        daemon=True,
    )
    display_process.start()

    processes = (reader_process, tracker_process, display_process) + (
        (egress_process,) if four_process else ()
    )
    from utils_local.pipeline_processes import stop_workers, cleanup_frame_segments

    def shutdown(signum, _frame):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        if four_process and hasattr(signal, 'SIGUSR1'):
            os.kill(processes[0].pid, signal.SIGUSR1)
            deadline = __import__("time").monotonic() + 120
            for worker in processes:
                worker.join(timeout=max(0, deadline-__import__("time").monotonic()))
            if all(worker.exitcode == 0 for worker in processes):
                cleanup_frame_segments(shm_prefix)
                raise SystemExit(0)
        stop_workers(processes, shm_prefix, grace_sec=20.0 if four_process else 5.0)
        if four_process:
            from services.PipelineEgress import mark_failed_pipeline

            mark_failed_pipeline("signal_" + str(signum))
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    while (
        any(process.exitcode is None for process in processes)
        if four_process
        else display_process.exitcode is None
    ):
        for process in processes:
            if process.exitcode not in (None, 0):
                logging.getLogger(__name__).error(
                    "Pipeline worker %s exited with code %s",
                    process.name,
                    process.exitcode,
                )
                stop_workers(
                    processes, shm_prefix, grace_sec=20.0 if four_process else 5.0
                )
                if four_process:
                    from services.PipelineEgress import mark_failed_pipeline

                    mark_failed_pipeline("worker_failed:" + process.name)
                raise SystemExit(1)
        sleep(0.2)

    display_process.join()
    for process in processes:
        process.join(timeout=5)
    cleanup_frame_segments(shm_prefix)
    # A final worker may fail between the loop condition and the health scan.
    # In particular, a failed writer is never a successful all-workers-done EOF.
    failed = [p for p in processes if p.exitcode != 0] if four_process else []
    if failed:
        if four_process:
            from services.PipelineEgress import mark_failed_pipeline

            mark_failed_pipeline("final_worker_failed:" + failed[0].name)
        raise SystemExit(1)


if __name__ == "__main__":
    ts = time()

    # 检查并设置环境变量（如果不存在）
    check_and_set_env_var("VIDEO_SRC", "test_videos/test_video.mp4")
    check_and_set_env_var("TOPIC_NAME", "uav_statistics_1")
    check_and_set_env_var("CAMERA_ID", 1)

    main()
    logging.getLogger("pipeline").info("PIPELINE_EXIT elapsed_sec=%.1f", time() - ts)
