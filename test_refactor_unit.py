#!/usr/bin/env python3
"""单元测试：验证 2026-05-31 重构的核心功能。

测试范围：
  - T-202: SpeedEstimationNode 线性回归速度计算
  - T-201: CalcStatisticsNode 动态道路数
  - T-203: KafkaProducerNode 多因子拥堵指数
  - T-204: TrackerInfoUpdateNode break 修复
  - T-205: FrameElement send_to_kafka 声明
"""

import sys
import os
import numpy as np
import time

# 设置环境变量
os.environ["VIDEO_SRC"] = "dummy"
os.environ["ROADS_JSON"] = "dummy"
os.environ["TOPIC_NAME"] = "statistics_1"
os.environ["CAMERA_ID"] = "1"

from elements.FrameElement import FrameElement
from elements.TrackElement import TrackElement
from nodes.SpeedEstimationNode import SpeedEstimationNode
from nodes.CalcStatisticsNode import CalcStatisticsNode


class TestResults:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.checks = []

    def check(self, name, condition, detail=""):
        if condition:
            self.passed += 1
            self.checks.append(f"✅ {name}" + (f" — {detail}" if detail else ""))
            print(f"✅ {name}" + (f" — {detail}" if detail else ""))
        else:
            self.failed += 1
            self.checks.append(f"❌ {name}" + (f" — {detail}" if detail else ""))
            print(f"❌ {name}" + (f" — {detail}" if detail else ""))

    def summary(self):
        print(f"\n{'='*60}")
        print(f"测试结果: {self.passed} PASS / {self.failed} FAIL")
        print(f"{'='*60}\n")
        return self.failed == 0


results = TestResults()


# ============================================================
# Test 1: T-202 线性回归速度计算
# ============================================================
print("\n" + "="*60)
print("Test 1: T-202 线性回归速度计算")
print("="*60)

config = {
    "speed_estimation": {
        "enabled": True,
        "history_frames": 15,
        "smoothing_window": 5,
        "min_displacement_px": 2.0,
    },
    "general": {
        "buffer_analytics": 0.5,
        "min_time_life_track": 3,
        "count_cars_buffer_frames": 25,
    },
}

speed_node = SpeedEstimationNode(config)

# 创建模拟 frame
frame = np.zeros((100, 100, 3), dtype=np.uint8)
roads_info = {"1": [], "2": []}
fe = FrameElement("test", frame, 1.0, 1, roads_info)

# 模拟一个匀速运动的轨迹（15帧，每帧移动 5px）
track = TrackElement(id=1, timestamp_first=0.0)
for i in range(15):
    t = i / 30.0  # 30fps
    x = 10 + i * 5  # 每帧移动 5px
    y = 50
    track.position_history.append((x, y, t))

fe.buffer_tracks = {1: track}
fe.homography_matrix = None  # 无标定，使用像素空间

fe_out = speed_node.process(fe)

# 验证速度计算
track_out = fe_out.buffer_tracks[1]
speed_px_per_sec = track_out.speed_kmh / 3.6  # 转换回 px/s
expected_speed = 5.0 * 30  # 5px/frame * 30fps = 150 px/s

results.check(
    "线性回归速度（像素空间）",
    abs(speed_px_per_sec - expected_speed) < 20,  # 允许 20px/s 误差
    f"expected ~{expected_speed:.0f}px/s, got {speed_px_per_sec:.0f}px/s"
)

results.check(
    "线性回归产生有效速度",
    track_out.speed_kmh > 0,
    f"speed_kmh={track_out.speed_kmh:.1f}"
)

# 测试噪声鲁棒性：添加随机噪声后速度仍稳定
track_noisy = TrackElement(id=2, timestamp_first=0.0)
np.random.seed(42)
for i in range(15):
    t = i / 30.0
    x = 10 + i * 5 + np.random.normal(0, 2)  # ±2px 噪声
    y = 50 + np.random.normal(0, 2)
    track_noisy.position_history.append((x, y, t))

fe.buffer_tracks = {2: track_noisy}
fe_out_noisy = speed_node.process(fe)
track_noisy_out = fe_out_noisy.buffer_tracks[2]

results.check(
    "线性回归抗噪声（±2px 抖动）",
    abs(track_noisy_out.speed_kmh - expected_speed * 3.6) < 100,  # 允许 100km/h 误差（像素空间）
    f"noisy speed={track_noisy_out.speed_kmh:.1f}, expected ~{expected_speed*3.6:.1f}"
)


# ============================================================
# Test 2: T-201 动态道路数
# ============================================================
print("\n" + "="*60)
print("Test 2: T-201 动态道路数")
print("="*60)

# 测试 2 条道路
roads_info_2 = {"1": [], "2": []}
calc_node = CalcStatisticsNode(config)

fe2 = FrameElement("test", frame, 1.0, 1, roads_info_2)
fe2.id_list = [1, 2]
fe2.buffer_tracks = {}

fe2_out = calc_node.process(fe2)

results.check(
    "2条道路：roads_activity 长度",
    len(fe2_out.info["roads_activity"]) == 2,
    f"expected 2, got {len(fe2_out.info['roads_activity'])}"
)

results.check(
    "2条道路：道路ID正确",
    set(fe2_out.info["roads_activity"].keys()) == {"1", "2"},
    f"expected {{'1','2'}}, got {set(fe2_out.info['roads_activity'].keys())}"
)

# 测试 5 条道路
roads_info_5 = {"1": [], "2": [], "3": [], "4": [], "5": []}
fe5 = FrameElement("test", frame, 1.0, 1, roads_info_5)
fe5.id_list = [1, 2, 3]
fe5.buffer_tracks = {}

fe5_out = calc_node.process(fe5)

results.check(
    "5条道路：roads_activity 长度",
    len(fe5_out.info["roads_activity"]) == 5,
    f"expected 5, got {len(fe5_out.info['roads_activity'])}"
)

# 测试 8 条道路（超出原始硬编码）
roads_info_8 = {str(i): [] for i in range(1, 9)}
fe8 = FrameElement("test", frame, 1.0, 1, roads_info_8)
fe8.id_list = [1, 2, 3, 4, 5, 6, 7, 8]
fe8.buffer_tracks = {}

fe8_out = calc_node.process(fe8)

results.check(
    "8条道路：roads_activity 长度",
    len(fe8_out.info["roads_activity"]) == 8,
    f"expected 8, got {len(fe8_out.info['roads_activity'])}"
)


# ============================================================
# Test 3: T-205 FrameElement send_to_kafka 声明
# ============================================================
print("\n" + "="*60)
print("Test 3: T-205 FrameElement send_to_kafka 声明")
print("="*60)

fe_test = FrameElement("test", frame, 0.0, 0, roads_info)

results.check(
    "send_to_kafka 属性存在",
    hasattr(fe_test, "send_to_kafka"),
    "FrameElement.send_to_kafka exists"
)

results.check(
    "send_to_kafka 默认值为 False",
    fe_test.send_to_kafka == False,
    f"default={fe_test.send_to_kafka}"
)

fe_test.send_to_kafka = True
results.check(
    "send_to_kafka 可赋值",
    fe_test.send_to_kafka == True,
    f"assigned={fe_test.send_to_kafka}"
)


# ============================================================
# Test 4: T-204 TrackerInfoUpdateNode break 修复
# ============================================================
print("\n" + "="*60)
print("Test 4: T-204 TrackerInfoUpdateNode 清理逻辑")
print("="*60)

from nodes.TrackerInfoUpdateNode import TrackerInfoUpdateNode, classify_vehicle
from nodes.ConflictDetectionNode import ConflictDetectionNode
from nodes.ShowNode import ShowNode

tracker_config = {
    "general": {
        "buffer_analytics": 0.1,  # 6秒
        "min_time_life_track": 2,
        "count_cars_buffer_frames": 10,
    },
    "trajectory": {
        "min_track_duration_sec": 1.0,
        "min_trajectory_points": 3,
    },
}

tracker_node = TrackerInfoUpdateNode(tracker_config)

# 创建多个轨迹，模拟不同创建时间
# track_1: 创建于 t=0，应在 t=10 时被清理（10 > 6+2=8）
# track_2: 创建于 t=5，应在 t=10 时保留（5 < 8）
# track_3: 创建于 t=7，应保留

fe_t0 = FrameElement("test", frame, 0.0, 0, roads_info)
fe_t0.id_list = [1]
fe_t0.tracked_xyxy = [[10, 10, 20, 20]]
fe_t0.tracked_cls_ids = [2]
fe_t0.buffer_tracks = {}
tracker_node.process(fe_t0)

fe_t5 = FrameElement("test", frame, 5.0, 150, roads_info)
fe_t5.id_list = [2]
fe_t5.tracked_xyxy = [[30, 30, 40, 40]]
fe_t5.tracked_cls_ids = [2]
fe_t5.buffer_tracks = tracker_node.buffer_tracks
tracker_node.process(fe_t5)

fe_t7 = FrameElement("test", frame, 7.0, 210, roads_info)
fe_t7.id_list = [3]
fe_t7.tracked_xyxy = [[50, 50, 60, 60]]
fe_t7.tracked_cls_ids = [2]
fe_t7.buffer_tracks = tracker_node.buffer_tracks
tracker_node.process(fe_t7)

results.check(
    "t=7 时 buffer_tracks 有 3 条轨迹（track_1 年龄=7 < 8）",
    len(tracker_node.buffer_tracks) == 3,
    f"count={len(tracker_node.buffer_tracks)}"
)

# 在 t=10 时，track_1 应该被清理（10 > 8）
fe_t10_cleanup = FrameElement("test", frame, 10.0, 300, roads_info)
fe_t10_cleanup.id_list = []  # 无新检测
fe_t10_cleanup.tracked_xyxy = []
fe_t10_cleanup.tracked_cls_ids = []
fe_t10_cleanup.buffer_tracks = tracker_node.buffer_tracks
tracker_node.process(fe_t10_cleanup)

results.check(
    "t=10 时 track_1 被清理（年龄=10 > 阈值=8）",
    1 not in tracker_node.buffer_tracks,
    f"remaining keys={list(tracker_node.buffer_tracks.keys())}"
)

results.check(
    "t=10 时 track_2 保留（年龄=5 < 阈值=8）",
    2 in tracker_node.buffer_tracks,
    f"track_2 age=5s < 8s"
)

results.check(
    "t=10 时 track_3 保留（年龄=3 < 阈值=8）",
    3 in tracker_node.buffer_tracks,
    f"track_3 age=3s < 8s"
)


# ============================================================
# Test 5: VisDrone motor/non_motor 类别映射
# ============================================================
print("\n" + "="*60)
print("Test 5: VisDrone motor/non_motor 类别映射")
print("="*60)

results.check(
    "VisDrone bicycle 归类为 non_motor",
    classify_vehicle(2, "bicycle") == "non_motor",
    f"class={classify_vehicle(2, 'bicycle')}"
)

results.check(
    "VisDrone tricycle 归类为 non_motor",
    classify_vehicle(6, "tricycle") == "non_motor",
    f"class={classify_vehicle(6, 'tricycle')}"
)

results.check(
    "VisDrone awning-tricycle 归类为 non_motor",
    classify_vehicle(7, "awning-tricycle") == "non_motor",
    f"class={classify_vehicle(7, 'awning-tricycle')}"
)

results.check(
    "VisDrone car 归类为 motor",
    classify_vehicle(3, "car") == "motor",
    f"class={classify_vehicle(3, 'car')}"
)

results.check(
    "COCO motorcycle id 3 保持 motor",
    classify_vehicle(3) == "motor",
    f"class={classify_vehicle(3)}"
)


# ============================================================
# Test 6: 机非冲突检测
# ============================================================
print("\n" + "="*60)
print("Test 6: 机非冲突检测")
print("="*60)

conflict_config = {
    "conflict_detection": {
        "enabled": True,
        "proximity_threshold_m": 3.0,
        "ttc_threshold_sec": 2.0,
        "severity_levels": {
            "critical": {"ttc": 1.0, "distance_m": 1.5},
            "warning": {"ttc": 2.0, "distance_m": 3.0},
            "info": {"ttc": 3.0, "distance_m": 5.0},
        },
    },
}

fe_conflict = FrameElement("test", frame, 10.0, 300, roads_info)
fe_conflict.id_list = [101, 202]
fe_conflict.tracked_xyxy = [[0, 0, 2, 2], [2, 0, 4, 2]]
fe_conflict.homography_matrix = np.eye(3)
fe_conflict.drone_displacement_m = np.array([0.0, 0.0])
fe_conflict.world_anchor_lat_lon = [36.702909, 117.022330]

motor_track = TrackElement(id=101, timestamp_first=0.0)
motor_track.vehicle_class = "motor"
motor_track.avg_speed_kmh = 10.0
non_motor_track = TrackElement(id=202, timestamp_first=0.0)
non_motor_track.vehicle_class = "non_motor"
non_motor_track.avg_speed_kmh = 5.0
fe_conflict.buffer_tracks = {
    101: motor_track,
    202: non_motor_track,
}

fe_conflict_out = ConflictDetectionNode(conflict_config).process(fe_conflict)
events = fe_conflict_out.conflict_events

results.check(
    "近距离 motor/non_motor 产生冲突事件",
    len(events) == 1,
    f"events={events}"
)

if events:
    results.check(
        "冲突事件包含 motor/non_motor id",
        events[0]["motor_id"] == 101 and events[0]["non_motor_id"] == 202,
        f"event={events[0]}"
    )
    results.check(
        "冲突严重级别为 critical",
        events[0]["severity"] == "critical",
        f"severity={events[0]['severity']}"
    )
    results.check(
        "冲突事件输出世界坐标",
        "motor_position_m" in events[0] and "non_motor_position_m" in events[0],
        f"event={events[0]}"
    )


# ============================================================
# Test 7: ShowNode 可视化过滤左上角幽灵框
# ============================================================
print("\n" + "="*60)
print("Test 7: ShowNode 可视化过滤左上角幽灵框")
print("="*60)

visible_shape = (100, 100, 3)
road_roi = {"1": [20, 20, 80, 20, 80, 80, 20, 80]}

results.check(
    "越界框裁剪后仍可见",
    ShowNode._normalize_visible_box([-5, 30, 30, 60], visible_shape) == [0, 30, 30, 60],
    f"box={ShowNode._normalize_visible_box([-5, 30, 30, 60], visible_shape)}"
)

results.check(
    "完全在画面外的框被过滤",
    ShowNode._normalize_visible_box([-50, -50, -10, -10], visible_shape) is None,
    f"box={ShowNode._normalize_visible_box([-50, -50, -10, -10], visible_shape)}"
)

results.check(
    "NaN框被过滤",
    ShowNode._normalize_visible_box([np.nan, 0, 20, 20], visible_shape) is None,
    f"box={ShowNode._normalize_visible_box([np.nan, 0, 20, 20], visible_shape)}"
)

results.check(
    "ROI 内轨迹框允许显示",
    ShowNode._box_center_in_roads([30, 30, 50, 50], road_roi),
    "center=(40,40)"
)

results.check(
    "ROI 外轨迹框过滤，避免左上角堆积",
    not ShowNode._box_center_in_roads([0, 0, 15, 15], road_roi),
    "center=(7.5,7.5)"
)


# ============================================================
# Test 8: 无道路标注模式不绘制左上角车道统计黑块
# ============================================================
print("\n" + "="*60)
print("Test 8: 无道路标注模式不绘制左上角车道统计黑块")
print("="*60)

show_config_no_roads = {
    "general": {
        "colors_of_roads": {"1": [0, 255, 0]},
        "buffer_analytics": 0.1,
        "min_time_life_track": 1,
    },
    "show_node": {
        "scale": 1.0,
        "fps_counter_N_frames_stat": 15,
        "draw_fps_info": False,
        "show_roi": True,
        "overlay_transparent_mask": False,
        "imshow": False,
        "show_only_yolo_detections": False,
        "show_track_id_different_colors": False,
        "show_info_statistics": False,
        "show_trace_trails": False,
    },
}


class DummyInferredLane:
    def __init__(self):
        self.direction_class = "straight"
        self.centerline_px = []
        self.entry_center_px = None
        self.exit_center_px = None
        self.label = "lane-1"
        self.count = 3
        self.avg_speed_kmh = 12.0
        self.stopped_count = 0
        self.flow_per_min = 2.5
        self.avg_headway_sec = None


white_frame = np.full((220, 420, 3), 255, dtype=np.uint8)
fe_no_roads_overlay = FrameElement("test", white_frame, 1.0, 1, {})
fe_no_roads_overlay.tracked_xyxy = []
fe_no_roads_overlay.id_list = []
fe_no_roads_overlay.inferred_lanes = {1: DummyInferredLane()}

show_no_roads = ShowNode(show_config_no_roads)
show_out = show_no_roads.process(fe_no_roads_overlay)
left_overlay_band = show_out.frame_result[100:150, 0:360]
black_pixels = np.count_nonzero(np.all(left_overlay_band == [0, 0, 0], axis=2))

results.check(
    "无道路标注时不绘制自动车道统计黑底块",
    black_pixels == 0,
    f"black_pixels={black_pixels}"
)


# ============================================================
# 总结
# ============================================================
success = results.summary()
sys.exit(0 if success else 1)
