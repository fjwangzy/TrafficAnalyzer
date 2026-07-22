#!/usr/bin/env python3
"""管道集成测试（无YOLO）：使用合成检测数据验证遥测→标定→运动补偿→统计全链路。

用法（Docker内运行）：
  docker run --rm -v $(pwd):/app -w /app traffic_analyzer python3 test_pipeline_no_yolo.py
"""

import os
import sys
import json
import time
import math
import logging
import numpy as np

os.environ["VIDEO_SRC"] = "test_videos/inter_xqh/DJI_20260403142902_0001_V小清河北路与水屯路路口.mp4"
os.environ["TOPIC_NAME"] = "uav_statistics_1"
os.environ["CAMERA_ID"] = "1"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("test_pipeline")


class TestResults:
    def __init__(self):
        self.checks = []
        self.warnings = []

    def check(self, name, condition, detail=""):
        status = "PASS" if condition else "FAIL"
        self.checks.append({"name": name, "status": status, "detail": detail})
        icon = "✅" if condition else "❌"
        print(f"  {icon} {name}" + (f" — {detail}" if detail else ""))

    def warn(self, msg):
        self.warnings.append(msg)
        print(f"  ⚠️  {msg}")

    def summary(self):
        passed = sum(1 for c in self.checks if c["status"] == "PASS")
        failed = sum(1 for c in self.checks if c["status"] == "FAIL")
        print(f"\n{'='*60}")
        print(f"测试结果: {passed} PASS / {failed} FAIL / {len(self.warnings)} WARN")
        print(f"{'='*60}")
        return failed == 0


def make_synthetic_detections(frame_num, img_w, img_h):
    """生成模拟检测+跟踪结果（2-3辆移动车辆）。"""
    # 模拟3辆车沿不同方向移动
    vehicles = []
    for i in range(3):
        # 每辆车有不同起点和速度
        base_x = 500 + i * 600 + frame_num * (3 + i * 2)
        base_y = 400 + i * 300 + frame_num * (1 + i)
        w, h = 80 + i * 20, 60 + i * 15
        x1 = max(0, min(base_x, img_w - w))
        y1 = max(0, min(base_y, img_h - h))
        x2 = x1 + w
        y2 = y1 + h
        vehicles.append({
            "xyxy": [x1, y1, x2, y2],
            "conf": 0.85 + i * 0.03,
            "cls_id": 2,  # car
            "track_id": 100 + i,
        })
    return vehicles


def main():
    results = TestResults()
    time_offset = 94.4  # 视频t=0对应遥测t=94.4s

    # ── Phase 1: 遥测加载 ──
    print("\n" + "="*60)
    print("Phase 1: 遥测文件加载")
    print("="*60)

    from services.TelemetryFileReader import TelemetryFileReader
    tfr = TelemetryFileReader(
        "test_videos/inter_xqh/小清河北路与水屯路路口交通数据收集航线快速计划20260403142353.txt",
        sync_tolerance_sec=2.0,
        time_offset_sec=time_offset,
    )
    results.check("遥测加载", tfr.buffer_count > 0, f"{tfr.buffer_count} records, {tfr.duration_sec:.0f}s")

    # 检查对齐后的遥测数据
    for vt in [0, 50, 100, 500]:
        rec = tfr.get_nearest(vt)
        if rec:
            results.check(
                f"video_t={vt}s遥测",
                rec.get("altitude_agl", 0) > 0,
                f"speed={rec['horizontal_speed']:.1f}m/s, "
                f"gimbal_pitch={rec['gimbal_pitch']}, agl={rec['altitude_agl']:.1f}m"
            )

    # ── Phase 2: 视频+遥测集成 ──
    print("\n" + "="*60)
    print("Phase 2: VideoReader + 遥测注入")
    print("="*60)

    import cv2
    from nodes.VideoReader import VideoReader
    from elements.VideoEndBreakElement import VideoEndBreakElement

    video_config = {
        "src": os.environ["VIDEO_SRC"],
        "skip_secs": 0,
    }
    telemetry_config = {
        "enabled": True,
        "source": "file",
        "file_path": "test_videos/inter_xqh/小清河北路与水屯路路口交通数据收集航线快速计划20260403142353.txt",
        "sync_tolerance_sec": 2.0,
        "time_offset_sec": time_offset,
    }

    vr = VideoReader(video_config, telemetry_config)
    results.check("VideoReader初始化", True)
    results.check("遥测加载器创建", vr.telemetry_subscriber is not None)

    # 读前5帧检查遥测注入
    frame_count = 0
    telemetry_ok_count = 0
    frames_data = []
    for fe in vr.process():
        if isinstance(fe, VideoEndBreakElement):
            break
        frame_count += 1
        if fe.telemetry:
            telemetry_ok_count += 1
        if frame_count <= 5:
            frames_data.append(fe)
        if frame_count >= 5:
            break

    vr.stream.release()
    results.check("帧读取", frame_count >= 5, f"{frame_count} frames")
    results.check("遥测注入", telemetry_ok_count == frame_count, f"{telemetry_ok_count}/{frame_count}")

    # ── Phase 3: 单应性矩阵计算 ──
    print("\n" + "="*60)
    print("Phase 3: HomographyCalibrationNode")
    print("="*60)

    from nodes.HomographyCalibrationNode import HomographyCalibrationNode
    from utils_local.homography import is_valid_homography, pixel_to_world

    calib_config = {
        "calibration": {
            "mode": "auto",
            "camera_intrinsics": {
                "focal_length_mm": 4.5,
                "sensor_width_mm": 6.4,
                "sensor_height_mm": 3.6,
            },
            "reference_points": [],
        },
    }
    h_node = HomographyCalibrationNode(calib_config)

    img_h, img_w = frames_data[0].frame.shape[:2]
    results.check("视频尺寸", img_w > 0 and img_h > 0, f"{img_w}x{img_h}")

    h_valid_count = 0
    nadir_count = 0
    oblique_count = 0

    for fe in frames_data:
        fe = h_node.process(fe)
        if is_valid_homography(fe.homography_matrix):
            h_valid_count += 1
            # 判断模式
            telem = fe.telemetry or {}
            gp = telem.get("gimbal_pitch", -90)
            if abs(gp + 90) < 10:
                nadir_count += 1
            else:
                oblique_count += 1

            # 测试像素→世界变换
            center_px = np.array([[img_w / 2, img_h / 2]])
            world_pt = pixel_to_world(center_px, fe.homography_matrix)[0]
            results.check(
                f"H矩阵(frame {fe.frame_num})",
                True,
                f"mode={fe.calibration_mode}, gimbal_pitch={gp}, "
                f"center→({world_pt[0]:.2f}, {world_pt[1]:.2f})m"
            )

    results.check("H矩阵有效", h_valid_count > 0, f"{h_valid_count}/{len(frames_data)} valid")

    # ── Phase 4: 运动补偿 ──
    print("\n" + "="*60)
    print("Phase 4: MotionCompensationNode（需要10+帧初始化锚点）")
    print("="*60)

    from nodes.MotionCompensationNode import MotionCompensationNode

    mc_config = {
        "motion_compensation": {
            "enabled": True,
            "hover_threshold_ms": 1.0,
            "world_anchor": None,
        },
    }
    mc_node = MotionCompensationNode(mc_config)

    # 需要>10帧才能初始化锚点
    vr2 = VideoReader(video_config, telemetry_config)
    mc_results = []
    frame_count2 = 0
    for fe in vr2.process():
        if isinstance(fe, VideoEndBreakElement):
            break
        frame_count2 += 1
        fe = h_node.process(fe)  # 先过Homography节点
        fe = mc_node.process(fe)
        mc_results.append({
            "frame": frame_count2,
            "has_displacement": fe.drone_displacement_m is not None,
            "has_velocity": fe.drone_velocity_ms is not None,
            "has_anchor": fe.anchor_gcj02 is not None,
            "is_hovering": fe.is_hovering,
            "displacement": fe.drone_displacement_m.copy() if fe.drone_displacement_m is not None else None,
            "velocity": fe.drone_velocity_ms.copy() if fe.drone_velocity_ms is not None else None,
            "anchor": fe.anchor_gcj02,
        })
        if frame_count2 >= 25:
            break

    vr2.stream.release()

    # 前10帧应该是锚点采集期（无位移输出）
    anchor_collect = [r for r in mc_results[:10] if not r["has_displacement"]]
    results.check("锚点采集期（前10帧无位移）", len(anchor_collect) >= 5,
                  f"{len(anchor_collect)}/10 frames without displacement")

    # 第11帧之后应该有位移输出
    post_anchor = [r for r in mc_results[10:] if r["has_displacement"]]
    results.check("锚点初始化后输出位移", len(post_anchor) > 0,
                  f"{len(post_anchor)}/{len(mc_results)-10} frames with displacement")

    if post_anchor:
        r = post_anchor[0]
        results.check("世界锚点GPS", r["anchor"] is not None,
                      f"({r['anchor'][0]:.6f}, {r['anchor'][1]:.6f})" if r["anchor"] else "None")
        results.check("无人机位移", r["displacement"] is not None,
                      f"[{r['displacement'][0]:.2f}, {r['displacement'][1]:.2f}]m")
        results.check("无人机速度", r["velocity"] is not None,
                      f"[{r['velocity'][0]:.2f}, {r['velocity'][1]:.2f}]m/s")
        results.check("悬停检测", isinstance(r["is_hovering"], bool),
                      f"is_hovering={r['is_hovering']}")

    # ── Phase 5: 完整管道（合成检测数据） ──
    print("\n" + "="*60)
    print("Phase 5: 完整管道（合成检测 + 全节点链路，200帧）")
    print("="*60)

    from elements.FrameElement import FrameElement
    from nodes.HomographyCalibrationNode import HomographyCalibrationNode
    from nodes.MotionCompensationNode import MotionCompensationNode
    from nodes.TrackerInfoUpdateNode import TrackerInfoUpdateNode
    from nodes.SpeedEstimationNode import SpeedEstimationNode
    from nodes.DirectionFlowNode import DirectionFlowNode
    from nodes.LaneAnalysisNode import LaneAnalysisNode
    from nodes.TrajectoryNode import TrajectoryNode
    from nodes.ConflictDetectionNode import ConflictDetectionNode
    from nodes.CalcStatisticsNode import CalcStatisticsNode

    full_config = {
        "general": {
            "colors_of_roads": {1: [102,204,255], 2: [0,0,170], 3: [17,70,10], 4: [120,56,126], 5: [30,105,215]},
            "buffer_analytics": 0.5,
            "min_time_life_track": 3,
            "count_cars_buffer_frames": 25,
        },
        "tracking_node": {
            "first_track_thresh": 0.5,
            "second_track_thresh": 0.10,
            "match_thresh": 0.95,
            "track_buffer": 125,
        },
        "calibration": calib_config["calibration"],
        "motion_compensation": mc_config["motion_compensation"],
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
        "kafka_producer_node": {
            "bootstrap_servers": "kafka:29092",
            "topic_name": "uav_statistics_1",
            "how_often_sec": 1,
            "camera_id": 1,
        },
    }

    # 创建所有节点
    h_node2 = HomographyCalibrationNode(full_config)
    mc_node2 = MotionCompensationNode(full_config)
    tracker_node = TrackerInfoUpdateNode(full_config)
    speed_node = SpeedEstimationNode(full_config)
    direction_node = DirectionFlowNode(full_config)
    lane_node = LaneAnalysisNode(full_config)
    trajectory_node = TrajectoryNode(full_config)
    conflict_node = ConflictDetectionNode(full_config)
    calc_node = CalcStatisticsNode(full_config)

    results.check("所有节点实例化", True)

    vr3 = VideoReader(video_config, telemetry_config)
    max_frames = 200
    frame_count3 = 0
    stats = {
        "telemetry": 0,
        "h_matrix": 0,
        "motion_comp": 0,
        "detections": 0,
        "tracks_max": 0,
        "speed_nonzero": 0,
        "direction_stats": 0,
        "completed_tracks": 0,
        "info_output": 0,
    }
    last_fe = None
    t0 = time.time()

    for fe in vr3.process():
        if isinstance(fe, VideoEndBreakElement):
            break
        frame_count3 += 1

        # 注入合成检测数据（替代YOLO）
        vehicles = make_synthetic_detections(frame_count3, img_w, img_h)
        fe.tracked_xyxy = [v["xyxy"] for v in vehicles]
        fe.tracked_conf = [v["conf"] for v in vehicles]
        fe.tracked_cls = [v["cls_id"] for v in vehicles]
        fe.id_list = [v["track_id"] for v in vehicles]
        fe.detected_xyxy = fe.tracked_xyxy
        fe.detected_conf = fe.tracked_conf
        fe.detected_cls = fe.tracked_cls
        stats["detections"] += len(vehicles)

        if fe.telemetry:
            stats["telemetry"] += 1

        # 全链路处理
        fe = h_node2.process(fe)
        if fe.homography_matrix is not None:
            stats["h_matrix"] += 1

        fe = mc_node2.process(fe)
        if fe.drone_displacement_m is not None:
            stats["motion_comp"] += 1

        fe = tracker_node.process(fe)
        if fe.buffer_tracks:
            stats["tracks_max"] = max(stats["tracks_max"], len(fe.buffer_tracks))

        fe = speed_node.process(fe)
        # 检查速度值
        if fe.buffer_tracks:
            for tid, track in fe.buffer_tracks.items():
                if hasattr(track, 'speed_kmh') and track.speed_kmh > 0:
                    stats["speed_nonzero"] += 1
                    break

        fe = direction_node.process(fe)
        if fe.direction_stats:
            stats["direction_stats"] += 1

        fe = lane_node.process(fe)
        fe = trajectory_node.process(fe)
        if fe.completed_tracks:
            stats["completed_tracks"] += len(fe.completed_tracks)

        fe = conflict_node.process(fe)
        fe = calc_node.process(fe)
        if fe.info:
            stats["info_output"] += 1

        last_fe = fe

        if frame_count3 % 50 == 0:
            elapsed = time.time() - t0
            fps_proc = frame_count3 / elapsed if elapsed > 0 else 0
            tracks = len(fe.buffer_tracks) if fe.buffer_tracks else 0
            hover = "HOVER" if fe.is_hovering else "MOVE"
            disp_str = f"[{fe.drone_displacement_m[0]:.1f},{fe.drone_displacement_m[1]:.1f}]" if fe.drone_displacement_m is not None else "None"
            print(f"  帧 {frame_count3}/{max_frames}: "
                  f"tracks={tracks}, H={'Y' if fe.homography_matrix is not None else 'N'}, "
                  f"disp={disp_str}, {hover}, fps={fps_proc:.1f}")

        if frame_count3 >= max_frames:
            break

    vr3.stream.release()
    if vr3.telemetry_subscriber:
        vr3.telemetry_subscriber.stop()

    elapsed_total = time.time() - t0
    print(f"\n  处理完成: {frame_count3} 帧 in {elapsed_total:.1f}s ({frame_count3/elapsed_total:.1f} fps)")
    print(f"  遥测注入: {stats['telemetry']}/{frame_count3}")
    print(f"  H矩阵有效: {stats['h_matrix']}/{frame_count3}")
    print(f"  运动补偿有效: {stats['motion_comp']}/{frame_count3}")
    print(f"  合成检测总数: {stats['detections']}")
    print(f"  最大活跃轨迹数: {stats['tracks_max']}")
    print(f"  速度非零帧数: {stats['speed_nonzero']}")
    print(f"  方向统计输出: {stats['direction_stats']}")
    print(f"  完成轨迹数: {stats['completed_tracks']}")
    print(f"  info输出: {stats['info_output']}")

    # 验证结果
    results.check("遥测注入率 > 80%", stats["telemetry"] > frame_count3 * 0.8,
                  f"{stats['telemetry']}/{frame_count3}")
    results.check("H矩阵生成率 > 80%", stats["h_matrix"] > frame_count3 * 0.8,
                  f"{stats['h_matrix']}/{frame_count3}")
    results.check("运动补偿激活（10帧后）", stats["motion_comp"] > 0,
                  f"{stats['motion_comp']}/{frame_count3}")
    results.check("轨迹跟踪工作", stats["tracks_max"] > 0,
                  f"max {stats['tracks_max']} active tracks")
    results.check("速度估计工作", stats["speed_nonzero"] > 0,
                  f"{stats['speed_nonzero']} frames with speed > 0")
    results.check("统计输出工作", stats["info_output"] > 0,
                  f"{stats['info_output']} frames with info")

    # 检查最后一帧的详细输出
    if last_fe:
        print(f"\n  最终帧详细状态:")
        print(f"    timestamp: {last_fe.timestamp:.3f}s")
        print(f"    telemetry: {'Yes' if last_fe.telemetry else 'No'}")
        print(f"    calibration_mode: {last_fe.calibration_mode}")
        print(f"    homography: {'Yes' if last_fe.homography_matrix is not None else 'No'}")
        print(f"    drone_displacement: {last_fe.drone_displacement_m}")
        print(f"    drone_velocity: {last_fe.drone_velocity_ms}")
        print(f"    anchor_gcj02: {last_fe.anchor_gcj02}")
        print(f"    is_hovering: {last_fe.is_hovering}")
        print(f"    direction_stats: {last_fe.direction_stats}")
        print(f"    info: {last_fe.info}")
        if last_fe.buffer_tracks:
            sample_id = list(last_fe.buffer_tracks.keys())[0]
            sample_track = last_fe.buffer_tracks[sample_id]
            print(f"    sample track {sample_id}:")
            print(f"      speed_kmh: {getattr(sample_track, 'speed_kmh', 'N/A')}")
            print(f"      vehicle_class: {getattr(sample_track, 'vehicle_class', 'N/A')}")
            print(f"      trajectory_points: {len(getattr(sample_track, 'trajectory_points', []))}")

    # ── Phase 6: 运动补偿精度验证 ──
    print("\n" + "="*60)
    print("Phase 6: 运动补偿数学验证")
    print("="*60)

    from utils_local.motion_compensation import (
        gps_to_enu_meters,
        compute_drone_velocity_vector,
        is_hovering as check_hovering,
    )

    # GPS→ENU 测试
    anchor_lat, anchor_lon = 36.702909, 117.022325
    # 偏移约100m东
    test_lat = anchor_lat
    test_lon = anchor_lon + 0.001  # ~89m at lat 36.7
    e, n = gps_to_enu_meters(test_lat, test_lon, anchor_lat, anchor_lon)
    results.check("GPS→ENU东向偏移", 70 < e < 110, f"easting={e:.1f}m (expected ~89m)")
    results.check("GPS→ENU北向偏移≈0", abs(n) < 1, f"northing={n:.1f}m")

    # 偏移约100m北
    test_lat2 = anchor_lat + 0.001  # ~111m
    test_lon2 = anchor_lon
    e2, n2 = gps_to_enu_meters(test_lat2, test_lon2, anchor_lat, anchor_lon)
    results.check("GPS→ENU北向偏移", 100 < n2 < 120, f"northing={n2:.1f}m (expected ~111m)")

    # 速度矢量测试
    telem_east = {"horizontal_speed": 10.0, "attitude_head": 90.0}  # heading east
    vel = compute_drone_velocity_vector(telem_east)
    results.check("速度矢量(东向)", abs(vel[0] - 10.0) < 0.1 and abs(vel[1]) < 0.1,
                  f"[{vel[0]:.2f}, {vel[1]:.2f}] (expected [10, 0])")

    telem_north = {"horizontal_speed": 5.0, "attitude_head": 0.0}  # heading north
    vel2 = compute_drone_velocity_vector(telem_north)
    results.check("速度矢量(北向)", abs(vel2[0]) < 0.1 and abs(vel2[1] - 5.0) < 0.1,
                  f"[{vel2[0]:.2f}, {vel2[1]:.2f}] (expected [0, 5])")

    # 悬停检测
    results.check("悬停检测(speed=0)", check_hovering({"horizontal_speed": 0}, 1.0))
    results.check("悬停检测(speed=0.5)", check_hovering({"horizontal_speed": 0.5}, 1.0))
    results.check("非悬停检测(speed=5)", not check_hovering({"horizontal_speed": 5.0}, 1.0))

    # ── 总结 ──
    all_passed = results.summary()

    if results.warnings:
        print("\n警告:")
        for w in results.warnings:
            print(f"  ⚠️  {w}")

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
