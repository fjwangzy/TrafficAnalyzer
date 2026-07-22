#!/usr/bin/env python3
"""管道集成测试：使用离线遥测文件验证交通态势感知全链路输出。

用法（Docker内运行）：
  python3 test_pipeline_inter_xqh.py

或直接：
  docker run --rm -v $(pwd):/app -w /app traffic_analyzer python3 test_pipeline_inter_xqh.py
"""

import os
import sys
import json
import time
import logging
import numpy as np

# 设置环境变量
os.environ["VIDEO_SRC"] = "test_videos/inter_xqh/DJI_20260403142902_0001_V小清河北路与水屯路路口.mp4"
os.environ["TOPIC_NAME"] = "uav_statistics_1"
os.environ["CAMERA_ID"] = "1"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("test_pipeline")


def build_test_config():
    """构建测试用配置字典（模拟Hydra输出）。"""
    return {
        "pipeline": {
            "save_video": False,
            "show_in_web": False,
            "send_info_kafka": False,
        },
        "general": {
            "colors_of_roads": {1: [102, 204, 255], 2: [0, 0, 170], 3: [17, 70, 10], 4: [120, 56, 126], 5: [30, 105, 215]},
            "buffer_analytics": 0.5,
            "min_time_life_track": 3,
            "count_cars_buffer_frames": 25,
        },
        "video_reader": {
            "src": os.environ["VIDEO_SRC"],
            "skip_secs": 0,
        },
        "detection_node": {
            "weight_pth": "weights/uav_best.pt",
            "classes_to_detect": [2, 3, 4, 5, 6, 7, 8, 9],
            "confidence": 0.10,
            "iou": 0.7,
            "imgsz": 640,
        },
        "tracking_node": {
            "first_track_thresh": 0.5,
            "second_track_thresh": 0.10,
            "match_thresh": 0.95,
            "track_buffer": 125,
        },
        "calibration": {
            "mode": "auto",
            "camera_intrinsics": {
                "focal_length_mm": 4.5,
                "sensor_width_mm": 6.4,
                "sensor_height_mm": 3.6,
            },
            "dist_coeffs": [],  # 空=不校正（测试时无畸变系数）
            "gcp": {
                "mode": "rigid",
                "max_residual_m": 5.0,
                "points": [],  # 空=不做 GCP 修正
            },
            "reference_points": [],
        },
        "telemetry": {
            "enabled": True,
            "source": "srt",
            "file_path": "test_videos/inter_xqh/telemetry.srt",
            "sync_tolerance_sec": 0.1,  # SRT逐帧匹配，严格同步
            # SRT时间戳从00:00:00开始，与视频帧时间完全对齐，无需偏移
            "time_offset_sec": 0.0,
        },
        "motion_compensation": {
            "enabled": True,
            "hover_threshold_ms": 1.0,
            "anchor_gcj02": None,
        },
        "speed_estimation": {
            "enabled": True,
            "history_frames": 15,
            "smoothing_window": 5,
            "min_displacement_px": 2.0,
        },
        "direction_flow": {
            "enabled": True,
            "min_track_duration_sec": 2.0,
            "min_position_points": 8,
            "heading_window": 5,
            "queue_speed_threshold_kmh": 5.0,
            "max_drone_speed_for_world_heading_ms": 5.0,
            "turn_thresholds": {"straight": 25, "turn": 120},
        },
        "lane_analysis": {
            "queue_speed_threshold_kmh": 5.0,
            "queue_gap_threshold_m": 8.0,
        },
        "trajectory": {
            "enabled": True,
            "min_track_duration_sec": 2.0,
            "turn_angle_thresholds": {
                "straight": 30,
                "left_turn": [30, 150],
                "right_turn": [-150, -30],
                "u_turn": [150, 180],
            },
        },
        "conflict_detection": {
            "enabled": True,
            "prediction_horizon_sec": 5.0,
            "critical_horizon_sec": 3.0,
            "sample_interval_sec": 0.2,
            "collision_radius_m": 2.0,
            "arrival_time_tolerance_sec": 1.0,
            "relative_speed_min_ms": 0.5,
        },
        "show_node": {
            "scale": 0.6,
            "imshow": False,
            "fps_counter_N_frames_stat": 15,
            "draw_fps_info": True,
            "show_roi": True,
            "overlay_transparent_mask": False,
            "show_only_yolo_detections": False,
            "show_track_id_different_colors": False,
            "show_info_statistics": False,
        },
        "video_saver_node": {
            "fps": 24,
            "out_folder": "test_videos/videos_out",
        },
        "kafka_producer_node": {
            "bootstrap_servers": "kafka:29092",
            "topic_name": "uav_statistics_1",
            "how_often_sec": 1,
            "camera_id": 1,
        },
        "video_server_node": {
            "index_page": "index.html",
            "host_ip": "0.0.0.0",
            "port": 8100,
            "template_folder": "../utils_local/templates",
            "output_size": [800, 470],
        },
    }


class TestResults:
    """测试结果收集器。"""
    def __init__(self):
        self.checks = []
        self.warnings = []

    def check(self, name: str, condition: bool, detail: str = ""):
        status = "PASS" if condition else "FAIL"
        self.checks.append({"name": name, "status": status, "detail": detail})
        icon = "✅" if condition else "❌"
        print(f"  {icon} {name}" + (f" — {detail}" if detail else ""))

    def warn(self, msg: str):
        self.warnings.append(msg)
        print(f"  ⚠️  {msg}")

    def summary(self):
        passed = sum(1 for c in self.checks if c["status"] == "PASS")
        failed = sum(1 for c in self.checks if c["status"] == "FAIL")
        print(f"\n{'='*60}")
        print(f"测试结果: {passed} PASS / {failed} FAIL / {len(self.warnings)} WARN")
        print(f"{'='*60}")
        return failed == 0


def main():
    config = build_test_config()
    results = TestResults()

    # ── Phase 1: 验证遥测文件加载 ──
    print("\n" + "="*60)
    print("Phase 1: SRT遥测文件加载")
    print("="*60)

    from services.SrtTelemetryParser import SrtTelemetryParser
    telemetry_path = config["telemetry"]["file_path"]
    time_offset = config["telemetry"].get("time_offset_sec", 0.0)
    tfr = SrtTelemetryParser(telemetry_path, sync_tolerance_sec=0.1, time_offset_sec=time_offset)

    results.check("遥测文件存在", os.path.isfile(telemetry_path))
    results.check("遥测记录数 > 0", tfr.buffer_count > 0, f"{tfr.buffer_count} records")
    results.check("遥测时长 > 0", tfr.duration_sec > 0, f"{tfr.duration_sec:.0f}s")

    # 验证遥测数据完整性
    sample = tfr.get_nearest(0)
    if sample:
        required_fields = ["timestamp", "latitude", "longitude", "height",
                          "gimbal_pitch", "gimbal_yaw", "attitude_head"]
        missing = [f for f in required_fields if f not in sample]
        results.check("遥测字段完整", len(missing) == 0, f"missing: {missing}" if missing else "all fields present")
        results.check("GPS有效", sample.get("latitude") is not None and sample["latitude"] != 0,
                      f"lat={sample.get('latitude')}, lon={sample.get('longitude')}")
        results.check("height > 0", sample.get("height", 0) > 0,
                      f"height={sample.get('height'):.1f}m")
        results.check("SRT特有字段focal_len", "focal_len" in sample,
                      f"focal_len={sample.get('focal_len', 'N/A')}")
    else:
        results.check("遥测样本", False, "get_nearest(0) returned None")

    # ── Phase 2: 验证视频可读 ──
    print("\n" + "="*60)
    print("Phase 2: 视频读取")
    print("="*60)

    import cv2
    video_path = config["video_reader"]["src"]
    cap = cv2.VideoCapture(video_path)
    results.check("视频可打开", cap.isOpened())

    if cap.isOpened():
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        fc = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        dur = fc / fps if fps > 0 else 0
        results.check("视频分辨率", w > 0 and h > 0, f"{w}x{h}")
        results.check("视频FPS", fps > 0, f"{fps:.1f}fps")
        results.check("视频时长", dur > 0, f"{dur:.0f}s ({dur/60:.1f}min)")

        # 检查视频和遥测时长是否匹配
        if dur > 0 and tfr.duration_sec > 0:
            ratio = tfr.duration_sec / dur
            results.check("遥测/视频时长匹配", 0.5 < ratio < 2.0,
                          f"telemetry={tfr.duration_sec:.0f}s, video={dur:.0f}s, ratio={ratio:.2f}")

        # 读几帧验证
        ret, frame = cap.read()
        results.check("首帧可读", ret, f"shape={frame.shape if ret else 'N/A'}")
        cap.release()
    else:
        results.check("视频读取", False, "Cannot open video")
        results.summary()
        return

    # ── Phase 3: 节点实例化验证 ──
    print("\n" + "="*60)
    print("Phase 3: 节点实例化")
    print("="*60)

    try:
        from nodes.HomographyCalibrationNode import HomographyCalibrationNode
        homography_node = HomographyCalibrationNode(config)
        results.check("HomographyCalibrationNode", True)
    except Exception as e:
        results.check("HomographyCalibrationNode", False, str(e))

    try:
        from nodes.MotionCompensationNode import MotionCompensationNode
        motion_comp_node = MotionCompensationNode(config)
        results.check("MotionCompensationNode", True)
    except Exception as e:
        results.check("MotionCompensationNode", False, str(e))

    try:
        from nodes.SpeedEstimationNode import SpeedEstimationNode
        speed_node = SpeedEstimationNode(config)
        results.check("SpeedEstimationNode", True)
    except Exception as e:
        results.check("SpeedEstimationNode", False, str(e))

    try:
        from nodes.DirectionFlowNode import DirectionFlowNode
        direction_node = DirectionFlowNode(config)
        results.check("DirectionFlowNode", True)
    except Exception as e:
        results.check("DirectionFlowNode", False, str(e))

    try:
        from nodes.LaneAnalysisNode import LaneAnalysisNode
        lane_node = LaneAnalysisNode(config)
        results.check("LaneAnalysisNode", True)
    except Exception as e:
        results.check("LaneAnalysisNode", False, str(e))

    try:
        from nodes.TrajectoryNode import TrajectoryNode
        trajectory_node = TrajectoryNode(config)
        results.check("TrajectoryNode", True)
    except Exception as e:
        results.check("TrajectoryNode", False, str(e))

    try:
        from nodes.ConflictDetectionNode import ConflictDetectionNode
        conflict_node = ConflictDetectionNode(config)
        results.check("ConflictDetectionNode", True)
    except Exception as e:
        results.check("ConflictDetectionNode", False, str(e))

    try:
        from nodes.CalcStatisticsNode import CalcStatisticsNode
        calc_node = CalcStatisticsNode(config)
        results.check("CalcStatisticsNode", True)
    except Exception as e:
        results.check("CalcStatisticsNode", False, str(e))

    # ── Phase 4: 遥测→单应性→运动补偿 链路验证 ──
    print("\n" + "="*60)
    print("Phase 4: 遥测→单应性→运动补偿 链路验证")
    print("="*60)

    from elements.FrameElement import FrameElement

    # 创建合成帧（黑色图像 + 模拟遥测）
    test_frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    roads_info = {"1": [100, 100, 200, 100, 200, 200, 100, 200]}

    # 先喂12帧让MotionCompensationNode建立GPS锚点（需10帧）
    print("  预热: 喂12帧建立GPS锚点...")
    for warmup_i in range(12):
        warmup_ts = warmup_i * 0.033  # 模拟30fps
        warmup_telem = tfr.get_nearest(warmup_ts)
        if warmup_telem is None:
            continue
        warmup_fe = FrameElement("test", test_frame.copy(), warmup_ts, warmup_i, roads_info)
        warmup_fe.telemetry = warmup_telem
        warmup_fe = homography_node.process(warmup_fe)
        warmup_fe = motion_comp_node.process(warmup_fe)
    print(f"  GCJ-02 锚点状态: {motion_comp_node._anchor_gcj02}")

    # 测试3个时间点的遥测
    test_timestamps = [1.0, 10.0, 50.0]
    h_matrix_ok = False
    motion_comp_ok = False

    for ts in test_timestamps:
        telemetry = tfr.get_nearest(ts)
        if telemetry is None:
            results.warn(f"t={ts}s: 无遥测数据")
            continue

        fe = FrameElement("test", test_frame.copy(), ts, int(ts * 30), roads_info)
        fe.telemetry = telemetry

        # Homography
        fe = homography_node.process(fe)
        if fe.homography_matrix is not None:
            h_matrix_ok = True
            from utils_local.homography import is_valid_homography, pixel_to_world
            valid = is_valid_homography(fe.homography_matrix)
            results.check(f"H矩阵有效 (t={ts}s)", valid,
                          f"mode={fe.calibration_mode}, det={np.linalg.det(fe.homography_matrix):.6f}")

            # 测试像素→世界坐标变换
            test_pts = np.array([[960, 540]], dtype=np.float64)  # 图像中心
            world_pts = pixel_to_world(test_pts, fe.homography_matrix)
            results.check(f"像素→世界变换 (t={ts}s)", world_pts is not None and world_pts.shape == (1, 2),
                          f"center→({world_pts[0][0]:.2f}, {world_pts[0][1]:.2f})m")
        else:
            results.warn(f"t={ts}s: H矩阵为None (calibration_mode={fe.calibration_mode})")

        # Motion Compensation
        fe = motion_comp_node.process(fe)
        if fe.drone_displacement_m is not None:
            motion_comp_ok = True
            results.check(f"运动补偿注入 (t={ts}s)", True,
                          f"disp=[{fe.drone_displacement_m[0]:.2f}, {fe.drone_displacement_m[1]:.2f}]m, "
                          f"vel=[{fe.drone_velocity_ms[0]:.2f}, {fe.drone_velocity_ms[1]:.2f}]m/s, "
                          f"hover={fe.is_hovering}")
            results.check(f"GCJ-02 锚点 (t={ts}s)", fe.anchor_gcj02 is not None,
                          f"anchor={fe.anchor_gcj02}")
        else:
            # 前10帧是锚点采集期，可能还没有位移输出
            results.warn(f"t={ts}s: drone_displacement_m=None (anchor collecting)")

    results.check("H矩阵至少一次有效", h_matrix_ok)
    results.check("运动补偿至少一次有效", motion_comp_ok)

    # ── Phase 4b: GCP 修正单元测试 ──
    print("\n" + "="*60)
    print("Phase 4b: GCP修正单元测试")
    print("="*60)

    from utils_local.gcp_refinement import GCPRefinement
    from utils_local.homography import undistort_points, build_camera_matrix

    # 创建合成GCP点：用已知H矩阵反算世界坐标，然后加偏移模拟误差
    if h_matrix_ok:
        # 从上面Phase 4获取最后fe的H矩阵
        H_test = fe.homography_matrix
        if H_test is not None:
            # 合成 4 个 GCP 点：图像四个越越
            test_pixels = np.array([
                [480, 270], [1440, 270], [1440, 810], [480, 810]
            ], dtype=np.float64)
            test_world = pixel_to_world(test_pixels, H_test)

            # 添加系统性偏移（模拟真实场景）
            bias = np.array([1.5, -0.8])  # 1.5m东向偏移, 0.8m南向偏移
            actual_world = test_world + bias

            gcp_list = []
            for i in range(4):
                gcp_list.append({
                    "pixel_x": float(test_pixels[i, 0]),
                    "pixel_y": float(test_pixels[i, 1]),
                    "world_x": float(actual_world[i, 0]),
                    "world_y": float(actual_world[i, 1]),
                    "label": f"synth-{i+1}",
                })

            # 测试残差计算
            refiner = GCPRefinement(gcp_list, mode="rigid")
            pre_report = refiner.compute_residuals(H_test)
            results.check(
                "GCP残差计算",
                pre_report["rmse_m"] > 0,
                f"RMSE={pre_report['rmse_m']:.3f}m (应接近{np.linalg.norm(bias):.2f}m)"
            )
            results.check(
                "GCP残差匹配偏移",
                abs(pre_report["rmse_m"] - np.linalg.norm(bias)) < 0.5,
                f"RMSE={pre_report['rmse_m']:.3f}m vs bias={np.linalg.norm(bias):.3f}m"
            )

            # 测试修正
            H_refined = refiner.refine(H_test)
            post_report = refiner.compute_residuals(H_refined)
            results.check(
                "GCP修正后RMSE下降",
                post_report["rmse_m"] < pre_report["rmse_m"] * 0.5,
                f"RMSE: {pre_report['rmse_m']:.3f}m → {post_report['rmse_m']:.3f}m"
            )
            results.check(
                "GCP修正后RMSE<0.1m",
                post_report["rmse_m"] < 0.1,
                f"RMSE={post_report['rmse_m']:.3f}m"
            )

            # 测试 undistort_points 不崩溃（空系数）
            pts_pass = undistort_points(
                test_pixels,
                config["calibration"]["camera_intrinsics"],
                (1920, 1080),
                dist_coeffs=None
            )
            results.check(
                "undistort_points空系数透传",
                np.allclose(pts_pass, test_pixels),
                "pass-through OK"
            )

            # 测试 build_camera_matrix
            K = build_camera_matrix(
                config["calibration"]["camera_intrinsics"],
                (1920, 1080)
            )
            results.check(
                "build_camera_matrix",
                K.shape == (3, 3) and K[0, 0] > 0,
                f"fx={K[0,0]:.1f}, fy={K[1,1]:.1f}"
            )
        else:
            results.warn("Phase 4b: H矩阵为None，跳过GCP测试")
    else:
        results.warn("Phase 4b: 无有效H矩阵，跳过GCP测试")

    # ── Phase 5: VideoReader集成（含遥测注入） ──
    print("\n" + "="*60)
    print("Phase 5: VideoReader集成测试（前20帧）")
    print("="*60)

    from nodes.VideoReader import VideoReader

    vr = VideoReader(config["video_reader"], config["telemetry"])
    telemetry_attached = False
    frame_count = 0
    max_test_frames = 20

    for fe in vr.process():
        from elements.VideoEndBreakElement import VideoEndBreakElement
        if isinstance(fe, VideoEndBreakElement):
            break

        frame_count += 1
        if frame_count <= 5:
            has_telemetry = fe.telemetry is not None
            if has_telemetry:
                telemetry_attached = True
            results.check(
                f"帧{frame_count}遥测注入",
                has_telemetry,
                f"ts={fe.timestamp:.3f}s, " +
                (f"lat={fe.telemetry.get('latitude', 'N/A')}, "
                 f"speed={fe.telemetry.get('horizontal_speed', 'N/A')}m/s")
                if has_telemetry else "no telemetry"
            )

        if frame_count >= max_test_frames:
            break

    results.check("遥测成功注入到视频帧", telemetry_attached, f"{frame_count} frames read")

    # 清理
    vr.stream.release()
    if vr.telemetry_subscriber:
        vr.telemetry_subscriber.stop()

    # ── Phase 6: 完整管道单进程测试（前100帧） ──
    print("\n" + "="*60)
    print("Phase 6: 完整管道单进程测试（前100帧，含检测+跟踪）")
    print("="*60)

    try:
        from nodes.DetectionTrackingNodes import DetectionTrackingNodes
        detection_node = DetectionTrackingNodes(config)
        results.check("DetectionTrackingNodes初始化", True)

        # 重新创建所有节点（重置状态）
        homography_node = HomographyCalibrationNode(config)
        motion_comp_node = MotionCompensationNode(config)
        from nodes.TrackerInfoUpdateNode import TrackerInfoUpdateNode
        tracker_node = TrackerInfoUpdateNode(config)
        speed_node = SpeedEstimationNode(config)
        direction_node = DirectionFlowNode(config)
        lane_node = LaneAnalysisNode(config)
        trajectory_node = TrajectoryNode(config)
        conflict_node = ConflictDetectionNode(config)
        calc_node = CalcStatisticsNode(config)
        results.check("ConflictDetectionNode启用", conflict_node.enabled is True)

        vr2 = VideoReader(config["video_reader"], config["telemetry"])
        max_frames = 100
        frame_count2 = 0
        detection_count = 0
        tracking_count = 0
        telemetry_count = 0
        h_matrix_count = 0
        motion_comp_count = 0
        completed_tracks_total = 0
        conflict_events_total = 0

        t0 = time.time()

        for fe in vr2.process():
            from elements.VideoEndBreakElement import VideoEndBreakElement
            if isinstance(fe, VideoEndBreakElement):
                break

            frame_count2 += 1

            # Detection + Tracking
            fe = detection_node.process(fe)
            if fe.tracked_xyxy and len(fe.tracked_xyxy) > 0:
                detection_count += 1
                tracking_count += len(fe.tracked_xyxy)

            if fe.telemetry:
                telemetry_count += 1

            # Homography
            fe = homography_node.process(fe)
            if fe.homography_matrix is not None:
                h_matrix_count += 1

            # Motion Compensation
            fe = motion_comp_node.process(fe)
            if fe.drone_displacement_m is not None:
                motion_comp_count += 1

            # Tracker Info Update
            fe = tracker_node.process(fe)

            # Speed Estimation
            fe = speed_node.process(fe)

            # Direction Flow
            fe = direction_node.process(fe)

            # Lane Analysis
            fe = lane_node.process(fe)

            # Trajectory
            fe = trajectory_node.process(fe)
            if fe.completed_tracks:
                completed_tracks_total += len(fe.completed_tracks)

            # Conflict Detection
            fe = conflict_node.process(fe)
            if fe.conflict_events:
                conflict_events_total += len(fe.conflict_events)

            # Calc Statistics
            fe = calc_node.process(fe)

            # 打印进度
            if frame_count2 % 20 == 0:
                elapsed = time.time() - t0
                fps_proc = frame_count2 / elapsed if elapsed > 0 else 0
                tracks = len(fe.buffer_tracks) if fe.buffer_tracks else 0
                print(f"  帧 {frame_count2}/{max_frames}: "
                      f"detections={len(fe.tracked_xyxy) if fe.tracked_xyxy else 0}, "
                      f"tracks={tracks}, "
                      f"conflicts={len(fe.conflict_events) if fe.conflict_events else 0}, "
                      f"telemetry={'Y' if fe.telemetry else 'N'}, "
                      f"H={'Y' if fe.homography_matrix is not None else 'N'}, "
                      f"disp={'Y' if fe.drone_displacement_m is not None else 'N'}, "
                      f"fps={fps_proc:.1f}")

            if frame_count2 >= max_frames:
                break

        vr2.stream.release()
        if vr2.telemetry_subscriber:
            vr2.telemetry_subscriber.stop()

        elapsed_total = time.time() - t0

        print(f"\n  处理完成: {frame_count2} 帧 in {elapsed_total:.1f}s ({frame_count2/elapsed_total:.1f} fps)")
        print(f"  检测到目标的帧数: {detection_count}/{frame_count2}")
        print(f"  累计检测目标数: {tracking_count}")
        print(f"  遥测注入帧数: {telemetry_count}/{frame_count2}")
        print(f"  H矩阵有效帧数: {h_matrix_count}/{frame_count2}")
        print(f"  运动补偿有效帧数: {motion_comp_count}/{frame_count2}")
        print(f"  完成轨迹数: {completed_tracks_total}")
        print(f"  机非冲突事件数: {conflict_events_total}")

        results.check("检测+跟踪工作正常", detection_count > 0,
                      f"{detection_count}/{frame_count2} frames with detections")
        results.check("遥测注入率 > 50%", telemetry_count > frame_count2 * 0.5,
                      f"{telemetry_count}/{frame_count2}")
        results.check("H矩阵生成", h_matrix_count > 0,
                      f"{h_matrix_count}/{frame_count2} frames")
        results.check("运动补偿生成", motion_comp_count > 0,
                      f"{motion_comp_count}/{frame_count2} frames")

        # 检查最终帧的统计输出
        if fe.info:
            results.check("info统计输出", True, f"keys={list(fe.info.keys())}")
            if "cars_amount" in fe.info:
                results.check("cars_amount", fe.info["cars_amount"] >= 0,
                              f"cars={fe.info['cars_amount']}")
        else:
            results.warn("info统计为空（前100帧可能还不够）")

        # 检查方向统计
        if fe.direction_stats:
            results.check("direction_stats输出", True,
                          f"keys={list(fe.direction_stats.keys())}")
        else:
            results.warn("direction_stats为空（前100帧轨迹可能还不够长）")

    except Exception as e:
        import traceback
        results.check("完整管道测试", False, f"Exception: {e}")
        traceback.print_exc()

    # ── 总结 ──
    all_passed = results.summary()

    if results.warnings:
        print("\n警告:")
        for w in results.warnings:
            print(f"  ⚠️  {w}")

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
