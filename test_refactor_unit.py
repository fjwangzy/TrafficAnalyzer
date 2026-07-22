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
os.environ["TOPIC_NAME"] = "uav_statistics_1"
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

track_world = TrackElement(id=3, timestamp_first=0.0)
for i in range(5):
    track_world.position_history.append((10 + i * 2, 50, float(i)))

fe_world = FrameElement("test", frame, 4.0, 4, roads_info)
fe_world.buffer_tracks = {3: track_world}
fe_world.homography_matrix = np.eye(3)
fe_world_out = speed_node.process(fe_world)
velocity_ms = fe_world_out.buffer_tracks[3].velocity_ms

results.check(
    "标定场景输出世界速度向量",
    velocity_ms is not None and np.allclose(velocity_ms, np.array([2.0, 0.0]), atol=0.05),
    f"velocity_ms={velocity_ms}"
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

classification_cfg = {
    "non_motor_class_names": [
        "pedestrian",
        "person",
        "people",
        "bicycle",
        "tricycle",
        "awning-tricycle",
        "motor",
        "motorcycle",
        "motorbike",
        "e-bike",
        "electric-bike",
        "electric-bicycle",
        "ebike",
        "scooter",
        "electric-scooter",
    ],
    "non_motor_class_ids": [0, 1, 2, 6, 7, 9],
}

results.check(
    "VisDrone bicycle 归类为 non_motor",
    classify_vehicle(2, "bicycle", classification_cfg) == "non_motor",
    f"class={classify_vehicle(2, 'bicycle', classification_cfg)}"
)

results.check(
    "VisDrone tricycle 归类为 non_motor",
    classify_vehicle(6, "tricycle", classification_cfg) == "non_motor",
    f"class={classify_vehicle(6, 'tricycle', classification_cfg)}"
)

results.check(
    "VisDrone awning-tricycle 归类为 non_motor",
    classify_vehicle(7, "awning-tricycle", classification_cfg) == "non_motor",
    f"class={classify_vehicle(7, 'awning-tricycle', classification_cfg)}"
)

results.check(
    "VisDrone car 归类为 motor",
    classify_vehicle(3, "car", classification_cfg) == "motor",
    f"class={classify_vehicle(3, 'car', classification_cfg)}"
)

results.check(
    "motor 类别名按配置归类为 non_motor",
    classify_vehicle(9, "motor", classification_cfg) == "non_motor",
    f"class={classify_vehicle(9, 'motor', classification_cfg)}"
)

results.check(
    "motorcycle 类别名按配置归类为 non_motor",
    classify_vehicle(3, "motorcycle", classification_cfg) == "non_motor",
    f"class={classify_vehicle(3, 'motorcycle', classification_cfg)}"
)

results.check(
    "motorbike 类别名按配置归类为 non_motor",
    classify_vehicle(3, "motorbike", classification_cfg) == "non_motor",
    f"class={classify_vehicle(3, 'motorbike', classification_cfg)}"
)

results.check(
    "electric-bike 类别名按配置归类为 non_motor",
    classify_vehicle(3, "electric-bike", classification_cfg) == "non_motor",
    f"class={classify_vehicle(3, 'electric-bike', classification_cfg)}"
)

results.check(
    "未配置类别名默认归类为 motor",
    classify_vehicle(42, "unknown-new-class", classification_cfg) == "motor",
    f"class={classify_vehicle(42, 'unknown-new-class', classification_cfg)}"
)

results.check(
    "无类别名时按非机动车 ID 兜底",
    classify_vehicle(9, None, classification_cfg) == "non_motor",
    f"class={classify_vehicle(9, None, classification_cfg)}"
)

results.check(
    "完全缺失类别信息保持 unknown",
    classify_vehicle(None, None, classification_cfg) == "unknown",
    f"class={classify_vehicle(None, None, classification_cfg)}"
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
        "prediction_horizon_sec": 5.0,
        "critical_horizon_sec": 3.0,
        "hard_ttc_sec": 1.5,
        "hard_pet_sec": 1.0,
        "sample_interval_sec": 0.1,
        "collision_radius_m": 2.0,
        "same_time_collision_radius_m": 0.8,
        "arrival_time_tolerance_sec": 1.0,
        "relative_speed_min_ms": 0.5,
        "min_history_points": 4,
        "min_conflict_angle_deg": 30.0,
        "max_conflict_angle_deg": 150.0,
        "turn_angle_threshold_deg": 45.0,
        "min_turn_leg_m": 2.0,
        "straight_angle_threshold_deg": 25.0,
        "hard_deceleration_ms2": -3.0,
        "hard_heading_change_deg": 60.0,
        "stop_speed_ms": 1.0,
        "moving_speed_ms": 2.0,
    },
}

def _track(track_id, vehicle_class, velocity, history, speed_kmh=12.0):
    tr = TrackElement(id=track_id, timestamp_first=history[0][2])
    tr.vehicle_class = vehicle_class
    tr.avg_speed_kmh = speed_kmh
    tr.max_speed_kmh = speed_kmh
    tr.velocity_ms = np.array(velocity, dtype=np.float64)
    tr.position_history = history
    tr.trajectory_points = [(p[0], p[1]) for p in history]
    return tr


def _bbox_at(x, y):
    return [x - 1, y - 1, x + 1, y + 1]


def _conflict_frame(motor_track, non_motor_track):
    fe = FrameElement("test", frame, 20.0, 600, {})
    fe.id_list = [motor_track.id, non_motor_track.id]
    mx, my = motor_track.position_history[-1][:2]
    nx, ny = non_motor_track.position_history[-1][:2]
    fe.tracked_xyxy = [_bbox_at(mx, my), _bbox_at(nx, ny)]
    fe.homography_matrix = np.eye(3)
    fe.drone_displacement_m = np.array([0.0, 0.0])
    fe.anchor_gcj02 = [117.022330, 36.702909]
    fe.buffer_tracks = {motor_track.id: motor_track, non_motor_track.id: non_motor_track}
    return fe


straight_motor = _track(
    101,
    "motor",
    [0.0, 4.0],
    [(0.0, -8.0, 0.0), (0.0, -6.0, 1.0), (0.0, -4.0, 2.0), (0.0, -2.0, 3.0)],
)
crossing_non_motor = _track(
    202,
    "non_motor",
    [4.0, 0.0],
    [(-10.0, 0.0, 0.0), (-8.0, 0.0, 1.0), (-6.0, 0.0, 2.0), (-4.0, 0.0, 3.0)],
)
no_scene_events = ConflictDetectionNode(conflict_config).process(
    _conflict_frame(straight_motor, crossing_non_motor)
).conflict_events
results.check(
    "TTC/PET危险但不属于右转/左转专项场景时不上报",
    len(no_scene_events) == 0,
    f"events={no_scene_events}"
)

right_turn_motor = _track(
    303,
    "motor",
    [0.0, -3.0],
    [(-5.0, 0.0, 0.0), (-2.0, 0.0, 1.0), (0.0, -1.0, 2.0), (0.0, -2.0, 3.0)],
    speed_kmh=10.8,
)
right_turn_non_motor = _track(
    404,
    "non_motor",
    [4.0, 0.0],
    [(-12.0, -6.0, 0.0), (-10.0, -6.0, 1.0), (-8.0, -6.0, 2.0), (-6.0, -6.0, 3.0)],
    speed_kmh=14.4,
)
right_turn_events = ConflictDetectionNode(conflict_config).process(
    _conflict_frame(right_turn_motor, right_turn_non_motor)
).conflict_events
results.check(
    "疑似右转机非场景且 hard TTC/PET 时产生 critical 冲突",
    (
        len(right_turn_events) == 1
        and right_turn_events[0]["severity"] == "critical"
        and right_turn_events[0]["prediction_type"] == "path_intersection"
        and right_turn_events[0]["conflict_scene"] == "suspected_right_turn_mv_nmv"
        and "hard_ttc_or_pet" in right_turn_events[0]["evidence"]
        and "motor_position_m" in right_turn_events[0]
    ),
    f"events={right_turn_events}"
)

evidence_node = ConflictDetectionNode(conflict_config)
cpa_without_avoidance_evidence = evidence_node._collect_evidence(
    {"prediction_type": "same_time_cpa", "ttc_sec": 2.4, "pet_sec": 0.0},
    {
        "min_acceleration_ms2": 0.0,
        "max_heading_change_deg": 75.0,
        "is_stopped": False,
    },
    {
        "min_acceleration_ms2": 0.0,
        "max_heading_change_deg": 5.0,
        "is_stopped": False,
    },
)
results.check(
    "CPA候选pet=0不作为PET证据且机动车正常转弯不算急转向避险",
    cpa_without_avoidance_evidence == [],
    f"evidence={cpa_without_avoidance_evidence}"
)

path_pet_evidence = evidence_node._collect_evidence(
    {"prediction_type": "path_intersection", "ttc_sec": 2.4, "pet_sec": 0.8},
    {
        "min_acceleration_ms2": 0.0,
        "max_heading_change_deg": 75.0,
        "is_stopped": False,
    },
    {
        "min_acceleration_ms2": 0.0,
        "max_heading_change_deg": 70.0,
        "is_stopped": False,
    },
)
results.check(
    "路径交点候选PET低于阈值且叠加避险急转向时作为hard证据",
    path_pet_evidence == ["hard_pet", "hard_steering"],
    f"evidence={path_pet_evidence}"
)

pet_only_without_avoidance_evidence = evidence_node._collect_evidence(
    {"prediction_type": "path_intersection", "ttc_sec": 2.4, "pet_sec": 0.8},
    {
        "min_acceleration_ms2": 0.0,
        "max_heading_change_deg": 75.0,
        "is_stopped": False,
    },
    {
        "min_acceleration_ms2": 0.0,
        "max_heading_change_deg": 5.0,
        "is_stopped": False,
    },
)
results.check(
    "PET危险但TTC不极端且无避险行为证据时不上报",
    pet_only_without_avoidance_evidence == [],
    f"evidence={pet_only_without_avoidance_evidence}"
)

cpa_only_config = {
    "conflict_detection": {
        **conflict_config["conflict_detection"],
        "same_time_collision_radius_m": 2.0,
        "enable_same_time_cpa": False,
    },
}
cpa_only_prediction = ConflictDetectionNode(cpa_only_config)._predict_collision(
    np.array([0.0, 0.0]),
    np.array([0.4, 1.0]),
    np.array([0.0, 1.0]),
    np.array([1.0, 0.0]),
)
results.check(
    "默认不把仅CPA近距离且无未来路径交点的轨迹作为冲突候选",
    cpa_only_prediction is None,
    f"prediction={cpa_only_prediction}"
)

loose_pet_no_same_space_prediction = ConflictDetectionNode(conflict_config)._predict_collision(
    np.array([0.0, 0.0]),
    np.array([-8.0, 5.0]),
    np.array([0.0, 2.0]),
    np.array([4.0, 0.0]),
)
results.check(
    "路径交点到达时间差达标但同刻中心距离超过实际碰撞半径时不上报",
    loose_pet_no_same_space_prediction is None,
    f"prediction={loose_pet_no_same_space_prediction}"
)

near_miss_point_nine_motor = _track(
    407,
    "motor",
    [0.0, -3.0],
    [(-5.0, 0.0, 0.0), (-2.0, 0.0, 1.0), (0.0, -1.0, 2.0), (0.0, -2.0, 3.0)],
    speed_kmh=10.8,
)
near_miss_point_nine_non_motor = _track(
    408,
    "non_motor",
    [4.0, 0.0],
    [(-7.5, -2.0, 0.0), (-5.5, -2.0, 1.0), (-3.5, -2.0, 2.0), (-1.5, -2.0, 3.0)],
    speed_kmh=14.4,
)
near_miss_point_nine_events = ConflictDetectionNode(conflict_config).process(
    _conflict_frame(near_miss_point_nine_motor, near_miss_point_nine_non_motor)
).conflict_events
results.check(
    "同刻预测最近距离约0.9m但无有效PET交汇时不上报",
    len(near_miss_point_nine_events) == 0,
    f"events={near_miss_point_nine_events}"
)

near_miss_but_separated_motor = _track(
    409,
    "motor",
    [0.0, -3.0],
    [(-5.0, 0.0, 0.0), (-2.0, 0.0, 1.0), (0.0, -1.0, 2.0), (0.0, -2.0, 3.0)],
    speed_kmh=10.8,
)
near_miss_but_separated_non_motor = _track(
    410,
    "non_motor",
    [2.0, 0.0],
    [(-13.0, -9.25, 0.0), (-11.0, -9.25, 1.0), (-9.0, -9.25, 2.0), (-7.0, -9.25, 3.0)],
    speed_kmh=7.2,
)
near_miss_but_separated_events = ConflictDetectionNode(conflict_config).process(
    _conflict_frame(near_miss_but_separated_motor, near_miss_but_separated_non_motor)
).conflict_events
results.check(
    "同刻预测最近距离约1.8m且无有效PET交汇时不上报",
    len(near_miss_but_separated_events) == 0,
    f"events={near_miss_but_separated_events}"
)

stale_regression_motor = _track(
    413,
    "motor",
    [0.0, -3.0],
    [(-5.0, 0.0, 0.0), (-2.0, 0.0, 1.0), (0.0, -1.0, 2.0), (0.0, -2.0, 3.0)],
    speed_kmh=10.8,
)
stale_regression_non_motor = _track(
    414,
    "non_motor",
    [4.0, 0.0],
    [(-4.0, -12.0, 0.0), (-4.0, -10.0, 1.0), (-4.0, -8.0, 2.0), (-4.0, -6.0, 3.0)],
    speed_kmh=14.4,
)
stale_regression_events = ConflictDetectionNode(conflict_config).process(
    _conflict_frame(stale_regression_motor, stale_regression_non_motor)
).conflict_events
results.check(
    "有历史轨迹时优先使用最近轨迹方向，避免测速回归向量制造虚假交点",
    len(stale_regression_events) == 0,
    f"events={stale_regression_events}"
)

minor_kink_motor = _track(
    411,
    "motor",
    [0.0, -3.0],
    [(0.0, 0.0, 0.0), (1.5, 0.0, 1.0), (1.8, -0.2, 2.0), (1.8, -2.0, 3.0)],
    speed_kmh=10.8,
)
minor_kink_non_motor = _track(
    412,
    "non_motor",
    [4.0, 0.0],
    [(-12.0, -6.0, 0.0), (-10.0, -6.0, 1.0), (-8.0, -6.0, 2.0), (-6.0, -6.0, 3.0)],
    speed_kmh=14.4,
)
minor_kink_events = ConflictDetectionNode(conflict_config).process(
    _conflict_frame(minor_kink_motor, minor_kink_non_motor)
).conflict_events
results.check(
    "机动车只是短窗口小折线且转弯腿不足时不上报",
    len(minor_kink_events) == 0,
    f"events={minor_kink_events}"
)

ordinary_config = {
    "conflict_detection": {
        **conflict_config["conflict_detection"],
        "collision_radius_m": 0.5,
        "hard_pet_sec": 0.2,
    },
}
left_turn_motor_no_evidence = _track(
    505,
    "motor",
    [0.0, 3.0],
    [(-3.0, -10.0, 0.0), (-1.0, -10.0, 1.0), (0.0, -9.0, 2.0), (0.0, -8.0, 3.0)],
)
left_turn_non_motor = _track(
    606,
    "non_motor",
    [4.0, 0.0],
    [(-14.0, 0.0, 0.0), (-12.0, 0.0, 1.0), (-10.0, 0.0, 2.0), (-8.0, 0.0, 3.0)],
)
ordinary_no_evidence_events = ConflictDetectionNode(ordinary_config).process(
    _conflict_frame(left_turn_motor_no_evidence, left_turn_non_motor)
).conflict_events
results.check(
    "普通 TTC/PET 风险但无避险行为证据时不上报",
    len(ordinary_no_evidence_events) == 0,
    f"events={ordinary_no_evidence_events}"
)

left_turn_motor_decel = _track(
    707,
    "motor",
    [0.0, 3.0],
    [(-8.0, -10.0, 0.0), (0.0, -10.0, 1.0), (0.0, -8.0, 2.0), (0.0, -8.0, 3.0)],
)
left_turn_non_motor_2 = _track(
    808,
    "non_motor",
    [4.0, 0.0],
    [(-15.6, 0.0, 0.0), (-13.6, 0.0, 1.0), (-11.6, 0.0, 2.0), (-9.6, 0.0, 3.0)],
)
ordinary_with_evidence_events = ConflictDetectionNode(ordinary_config).process(
    _conflict_frame(left_turn_motor_decel, left_turn_non_motor_2)
).conflict_events
results.check(
    "疑似无保护左转普通风险叠加急减速证据时上报",
    (
        len(ordinary_with_evidence_events) == 1
        and ordinary_with_evidence_events[0]["conflict_scene"] == "suspected_unprotected_left_turn"
        and "hard_deceleration" in ordinary_with_evidence_events[0]["evidence"]
        and ordinary_with_evidence_events[0]["pet_sec"] > 0.2
    ),
    f"events={ordinary_with_evidence_events}"
)

conflict_node_once_per_pair = ConflictDetectionNode(conflict_config)
first_pair_events = conflict_node_once_per_pair.process(
    _conflict_frame(right_turn_motor, right_turn_non_motor)
).conflict_events
second_pair_events = conflict_node_once_per_pair.process(
    _conflict_frame(right_turn_motor, right_turn_non_motor)
).conflict_events
results.check(
    "motor/non_motor 轨迹对首次跨过冲突临界点后不重复上报",
    len(first_pair_events) == 1 and len(second_pair_events) == 0,
    f"first={first_pair_events}, second={second_pair_events}"
)

fe_false_ttc = FrameElement("test", frame, 21.0, 630, roads_info)
fe_false_ttc.id_list = [305, 406]
fe_false_ttc.tracked_xyxy = [[0, 0, 2, 2], [12, 0, 14, 2]]
fe_false_ttc.homography_matrix = np.eye(3)
parallel_motor_track = TrackElement(id=305, timestamp_first=0.0)
parallel_motor_track.vehicle_class = "motor"
parallel_motor_track.avg_speed_kmh = 36.0
parallel_motor_track.velocity_ms = np.array([0.0, 10.0])
stationary_non_motor_track = TrackElement(id=406, timestamp_first=0.0)
stationary_non_motor_track.vehicle_class = "non_motor"
stationary_non_motor_track.avg_speed_kmh = 0.0
stationary_non_motor_track.velocity_ms = np.array([0.0, 0.0])
fe_false_ttc.buffer_tracks = {
    305: parallel_motor_track,
    406: stationary_non_motor_track,
}

false_ttc_events = ConflictDetectionNode(conflict_config).process(fe_false_ttc).conflict_events
results.check(
    "未来最近点不进入碰撞半径时不产生冲突事件",
    len(false_ttc_events) == 0,
    f"events={false_ttc_events}"
)

fe_motor_only = FrameElement("test", frame, 30.0, 900, roads_info)
fe_motor_only.id_list = [501, 502]
fe_motor_only.tracked_xyxy = [[0, 0, 2, 2], [1, 0, 3, 2]]
fe_motor_only.homography_matrix = np.eye(3)
motor_a = TrackElement(id=501, timestamp_first=0.0)
motor_a.vehicle_class = "motor"
motor_a.avg_speed_kmh = 10.0
motor_b = TrackElement(id=502, timestamp_first=0.0)
motor_b.vehicle_class = "motor"
motor_b.avg_speed_kmh = 10.0
fe_motor_only.buffer_tracks = {501: motor_a, 502: motor_b}
motor_only_events = ConflictDetectionNode(conflict_config).process(fe_motor_only).conflict_events
results.check(
    "两个 motor 不产生机非冲突事件",
    len(motor_only_events) == 0,
    f"events={motor_only_events}"
)

fe_non_motor_only = FrameElement("test", frame, 40.0, 1200, roads_info)
fe_non_motor_only.id_list = [601, 602]
fe_non_motor_only.tracked_xyxy = [[0, 0, 2, 2], [1, 0, 3, 2]]
fe_non_motor_only.homography_matrix = np.eye(3)
non_motor_a = TrackElement(id=601, timestamp_first=0.0)
non_motor_a.vehicle_class = "non_motor"
non_motor_a.avg_speed_kmh = 10.0
non_motor_b = TrackElement(id=602, timestamp_first=0.0)
non_motor_b.vehicle_class = "non_motor"
non_motor_b.avg_speed_kmh = 10.0
fe_non_motor_only.buffer_tracks = {601: non_motor_a, 602: non_motor_b}
non_motor_only_events = ConflictDetectionNode(conflict_config).process(fe_non_motor_only).conflict_events
results.check(
    "两个 non_motor 不产生机非冲突事件",
    len(non_motor_only_events) == 0,
    f"events={non_motor_only_events}"
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
# Test 9: main_optimized 子进程日志在只读目录下降级到 console
# ============================================================
print("\n" + "="*60)
print("Test 9: 子进程日志文件不可写时降级")
print("="*60)

import main_optimized as main_optimized_module

logging_cfg = {
    "version": 1,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
        "file": {"class": "logging.FileHandler", "filename": "logs/app.log"},
    },
    "root": {"handlers": ["console", "file"], "level": "INFO"},
    "loggers": {"demo": {"handlers": ["file"]}},
}
original_can_write_log_file = main_optimized_module._can_write_log_file
try:
    main_optimized_module._can_write_log_file = lambda filename: filename != "logs/app.log"
    sanitized_logging_cfg = main_optimized_module._drop_unwritable_file_handlers(logging_cfg)
finally:
    main_optimized_module._can_write_log_file = original_can_write_log_file

results.check(
    "不可写FileHandler被移除",
    "file" not in sanitized_logging_cfg["handlers"],
    f"handlers={sanitized_logging_cfg['handlers'].keys()}"
)
results.check(
    "root logger 保留 console handler",
    sanitized_logging_cfg["root"]["handlers"] == ["console"],
    f"root={sanitized_logging_cfg['root']}"
)
results.check(
    "普通 logger 同步移除不可写 file handler",
    sanitized_logging_cfg["loggers"]["demo"]["handlers"] == [],
    f"logger={sanitized_logging_cfg['loggers']['demo']}"
)


# ============================================================
# 总结
# ============================================================
success = results.summary()
sys.exit(0 if success else 1)
