"""冲突候选空间网格预筛与逐对枚举路径的逐字段等价性测试。

覆盖随机场景（远端对/近端对/嵌套框/静止目标/缺失速度/单侧为空/未当前观测）、
多帧去重、非有限位置保守回退、阈值边界以及 300 轨迹场景的同进程耗时基准。
"""

import copy
import os
import statistics
import time
from contextlib import contextmanager

import numpy as np
import pytest

from elements.FrameElement import FrameElement
from elements.TrackElement import TrackElement
from nodes.ConflictDetectionNode import ConflictDetectionNode

ENV_KEY = "CONFLICT_GRID_PREFILTER"
RANDOM_SCENE_COUNT = 120
_BENCHMARK_TRACKS = 300


def _config(**overrides):
    conflict = {
        "enabled": True,
        "prediction_horizon_sec": 5.0,
        "critical_horizon_sec": 3.0,
        "hard_ttc_sec": 2.0,
        "hard_pet_sec": 1.0,
        "sample_interval_sec": 0.2,
        "collision_radius_m": 2.0,
        "same_time_collision_radius_m": 0.8,
        "arrival_time_tolerance_sec": 1.0,
        "relative_speed_min_ms": 0.5,
        "min_history_points": 4,
        "min_conflict_angle_deg": 30.0,
        "max_conflict_angle_deg": 150.0,
        "enable_high_angle_path_intersection": True,
        "high_angle_max_conflict_angle_deg": 170.0,
        "turn_angle_threshold_deg": 45.0,
        "min_turn_leg_m": 2.0,
        "straight_angle_threshold_deg": 25.0,
        "hard_deceleration_ms2": -3.0,
        "hard_heading_change_deg": 60.0,
        "stop_speed_ms": 1.0,
        "moving_speed_ms": 2.0,
        "max_segment_speed_ms": 45.0,
        "min_vehicle_class_confidence": 0.8,
        "min_heading_confidence": 0.6,
        "min_general_crossing_angle_deg": 60.0,
        "min_participant_border_clearance_px": 8.0,
        "max_cross_class_bbox_containment": 0.8,
        "max_current_observation_age_sec": 0.05,
        "max_pair_distance_m": 15.0,
        "min_trajectory_length_m": 3.0,
        "emit_cooldown_sec": 2.0,
    }
    conflict.update(overrides)
    return {"conflict_detection": conflict}


@contextmanager
def _grid_switch(enabled):
    previous = os.environ.get(ENV_KEY)
    os.environ[ENV_KEY] = "true" if enabled else "false"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(ENV_KEY, None)
        else:
            os.environ[ENV_KEY] = previous


def _new_node(config, *, grid_enabled):
    with _grid_switch(grid_enabled):
        node = ConflictDetectionNode(config)
    assert node.grid_prefilter_enabled is grid_enabled
    return node


def _materialize_scene(scene, timestamp):
    """按“每个节点各自独立的一帧”重建 TrackElement/FrameElement，避免共享副作用。"""
    tracks = []
    id_list = []
    tracked_xyxy = []
    for spec in scene["tracks"]:
        track = TrackElement(id=spec["id"], timestamp_first=timestamp - 5.0)
        track.vehicle_class = spec["vehicle_class"]
        track.current_vehicle_class = spec.get("current_vehicle_class")
        track.vehicle_class_confidence = spec.get("vehicle_class_confidence")
        track.avg_speed_kmh = spec.get("max_speed_kmh")
        track.max_speed_kmh = spec.get("max_speed_kmh")
        velocity = spec.get("velocity")
        track.velocity_ms = (
            None if velocity is None else np.asarray(velocity, dtype=np.float64)
        )
        history = spec.get("history")
        track.position_history = list(history) if history is not None else []
        track.position_history_enu_m = list(history) if history is not None else []
        current_position = spec.get("current_position")
        track.current_position_enu_m = (
            None if current_position is None else list(current_position)
        )
        track.trajectory_points = [(point[0], point[1]) for point in (history or [])]
        track.trajectory_output_eligible = spec.get("trajectory_output_eligible", True)
        observation_delay = spec.get("observation_delay")
        track.current_observation_timestamp_sec = (
            None if observation_delay is None else timestamp - observation_delay
        )
        bbox = spec.get("bbox")
        track.current_bbox_xyxy = None if bbox is None else list(bbox)
        track.current_frame_size = [1920, 1080] if bbox is not None else None
        track.tracking_quality = "verified"
        tracks.append(track)
        id_list.append(spec["id"])
        if bbox is None:
            center = current_position or (0.0, 0.0)
            tracked_xyxy.append(
                [
                    float(center[0]) - 2.0,
                    float(center[1]) - 2.0,
                    float(center[0]) + 2.0,
                    float(center[1]) + 2.0,
                ]
            )
        else:
            tracked_xyxy.append([float(value) for value in bbox])

    frame = FrameElement(
        "grid-prefilter-test", np.zeros((8, 8, 3), dtype=np.uint8), timestamp, 1, {}
    )
    frame.id_list = id_list
    frame.tracked_xyxy = tracked_xyxy
    frame.buffer_tracks = {track.id: track for track in tracks}
    frame.homography_matrix = np.eye(3)
    frame.pixel_to_world_enu = np.eye(3)
    frame.tcc_analytics_eligible = True
    frame.flight_segment_id = scene.get("flight_segment_id")
    frame.flight_phase = scene.get("flight_phase")
    frame.geo_reference_quality = {
        "geo_status": "verified",
        "tcc_reasons": [],
        "current_frame_matrix": {"status": "verified"},
        "visual_warp": {"status": "verified"},
    }
    frame.drone_displacement_m = np.array([0.0, 0.0])
    frame.anchor_gcj02 = scene.get("anchor_gcj02")
    return frame


def _run_sequence(node, scene):
    """按 scene 的时间戳逐帧处理，返回每帧 (events, diagnostics, reported_pairs) 快照。"""
    results = []
    for timestamp in scene["timestamps"]:
        frame = _materialize_scene(scene, timestamp)
        node.process(frame)
        results.append(
            (
                frame.conflict_events,
                copy.deepcopy(frame.tcc_diagnostics),
                copy.deepcopy(node._reported_pairs),
            )
        )
    return results


def _assert_scene_equivalent(scene, scene_label):
    config = _config(**scene.get("config_overrides", {}))
    legacy = _new_node(config, grid_enabled=False)
    grid = _new_node(config, grid_enabled=True)
    legacy_results = _run_sequence(legacy, scene)
    grid_results = _run_sequence(grid, scene)

    for frame_index, (legacy_result, grid_result) in enumerate(
        zip(legacy_results, grid_results)
    ):
        legacy_events, legacy_diagnostics, legacy_state = legacy_result
        grid_events, grid_diagnostics, grid_state = grid_result
        prefix = f"{scene_label} frame={frame_index} "
        assert grid_events == legacy_events, (
            f"{prefix}conflict_events differ: grid={grid_events} legacy={legacy_events}"
        )
        assert grid_diagnostics == legacy_diagnostics, (
            f"{prefix}tcc_diagnostics differ: grid={grid_diagnostics} "
            f"legacy={legacy_diagnostics}"
        )
        assert grid_state == legacy_state, (
            f"{prefix}_reported_pairs differ: grid={grid_state} legacy={legacy_state}"
        )
        assert list(grid_diagnostics["rejection_reasons"]) == list(
            legacy_diagnostics["rejection_reasons"]
        ), (
            f"{prefix}rejection_reasons key order differs: "
            f"grid={list(grid_diagnostics['rejection_reasons'])} "
            f"legacy={list(legacy_diagnostics['rejection_reasons'])}"
        )
        expected_pairs = (
            grid_diagnostics["eligible_motor_tracks"]
            * grid_diagnostics["eligible_non_motor_tracks"]
        )
        assert grid_diagnostics["candidate_pairs"] == expected_pairs, (
            f"{prefix}candidate_pairs={grid_diagnostics['candidate_pairs']} "
            f"!= eligible motor*non_motor={expected_pairs}"
        )
    return legacy_results, grid_results


# ── 场景构造 ──────────────────────────────────────────────────────────────


def _track_spec(
    track_id,
    vehicle_class,
    *,
    center,
    max_speed_kmh,
    velocity,
    history,
    current_position,
    bbox=None,
    observation_delay=None,
    trajectory_output_eligible=True,
    current_vehicle_class=None,
    vehicle_class_confidence=None,
):
    return {
        "id": track_id,
        "vehicle_class": vehicle_class,
        "velocity": velocity,
        "max_speed_kmh": max_speed_kmh,
        "history": history,
        "current_position": current_position,
        "bbox": bbox,
        "observation_delay": observation_delay,
        "trajectory_output_eligible": trajectory_output_eligible,
        "current_vehicle_class": current_vehicle_class,
        "vehicle_class_confidence": vehicle_class_confidence,
        "center": center,
    }


def _moving_history(center, velocity, point_count, step_sec):
    return [
        (
            float(center[0] - velocity[0] * step_sec * (point_count - 1 - index)),
            float(center[1] - velocity[1] * step_sec * (point_count - 1 - index)),
            float(index * step_sec),
        )
        for index in range(point_count)
    ]


def _random_track_spec(rng, track_id, vehicle_class, spread, bbox_slot):
    center = np.array(
        [
            rng.uniform(-spread / 2.0, spread / 2.0),
            rng.uniform(-spread / 2.0, spread / 2.0),
        ]
    )
    past_speed = float(rng.uniform(0.0, 6.0))
    past_heading = float(rng.uniform(0.0, 2.0 * np.pi))
    past_velocity = past_speed * np.array([np.cos(past_heading), np.sin(past_heading)])
    point_count = int(rng.integers(4, 8))
    step_sec = float(rng.uniform(0.4, 1.0))
    history = _moving_history(center, past_velocity, point_count, step_sec)

    speed_mode = str(rng.choice(["moving", "stationary", "missing"], p=[0.6, 0.25, 0.15]))
    if speed_mode == "missing":
        max_speed_kmh = None
    elif speed_mode == "stationary":
        max_speed_kmh = float(rng.uniform(0.0, 4.9))
    else:
        max_speed_kmh = float(rng.uniform(5.5, 60.0))

    if rng.random() < 0.1:
        velocity = None
    else:
        current_heading = float(rng.uniform(0.0, 2.0 * np.pi))
        current_speed = 0.0 if speed_mode != "moving" else float(rng.uniform(0.0, 5.0))
        velocity = [
            float(np.cos(current_heading) * current_speed),
            float(np.sin(current_heading) * current_speed),
        ]

    if rng.random() < 0.08:
        history = history[: int(rng.integers(0, 4))]

    bbox = None
    if rng.random() < 0.2:
        column = bbox_slot % 12
        row = bbox_slot // 12
        bbox = [
            40.0 + column * 120.0,
            40.0 + row * 100.0,
            90.0 + column * 120.0,
            100.0 + row * 100.0,
        ]

    if rng.random() < 0.5:
        observation_delay = None
    elif rng.random() < 0.8:
        observation_delay = 0.0
    else:
        observation_delay = 0.2

    current_vehicle_class = None
    vehicle_class_confidence = None
    if rng.random() < 0.08:
        current_vehicle_class = (
            "non_motor" if vehicle_class == "motor" else "motor"
        )
    elif rng.random() < 0.08:
        vehicle_class_confidence = 0.5

    current_position = None
    if rng.random() > 0.05:
        current_position = [float(center[0]), float(center[1])]

    return _track_spec(
        track_id,
        vehicle_class,
        center=center,
        max_speed_kmh=max_speed_kmh,
        velocity=velocity,
        history=history,
        current_position=current_position,
        bbox=bbox,
        observation_delay=observation_delay,
        trajectory_output_eligible=bool(rng.random() > 0.08),
        current_vehicle_class=current_vehicle_class,
        vehicle_class_confidence=vehicle_class_confidence,
    )


def _positive_pair_specs():
    """与既有 TCC 测试一致的可触发正式冲突的右转机非对。"""
    motor = _track_spec(
        9001,
        "motor",
        center=np.array([0.0, -2.0]),
        max_speed_kmh=10.8,
        velocity=[0.0, -3.0],
        history=[
            (-5.0, 0.0, 0.0),
            (-2.0, 0.0, 1.0),
            (0.0, -1.0, 2.0),
            (0.0, -2.0, 3.0),
        ],
        current_position=[0.0, -2.0],
    )
    non_motor = _track_spec(
        9002,
        "non_motor",
        center=np.array([-6.0, -6.0]),
        max_speed_kmh=14.4,
        velocity=[4.0, 0.0],
        history=[
            (-12.0, -6.0, 0.0),
            (-10.0, -6.0, 1.0),
            (-8.0, -6.0, 2.0),
            (-6.0, -6.0, 3.0),
        ],
        current_position=[-6.0, -6.0],
    )
    return [motor, non_motor]


def _nested_pair_specs():
    """同一物理对象的跨类别嵌套检测：像素框高度重叠，ENU 位置相邻（现实几何）。"""
    motor = _track_spec(
        9101,
        "motor",
        center=np.array([10.0, 10.0]),
        max_speed_kmh=30.0,
        velocity=[8.0, 0.0],
        history=[
            (-2.0, 10.0, 0.0),
            (2.0, 10.0, 0.5),
            (6.0, 10.0, 1.0),
            (10.0, 10.0, 1.5),
        ],
        current_position=[10.0, 10.0],
        bbox=[100.0, 100.0, 180.0, 160.0],
    )
    non_motor = _track_spec(
        9102,
        "non_motor",
        center=np.array([10.4, 10.2]),
        max_speed_kmh=12.0,
        velocity=[2.0, 0.0],
        history=[
            (2.0, 10.2, 0.0),
            (4.0, 10.2, 0.5),
            (6.0, 10.2, 1.0),
            (8.0, 10.2, 1.5),
        ],
        current_position=[10.4, 10.2],
        bbox=[120.0, 115.0, 150.0, 145.0],
    )
    return [motor, non_motor]


def _random_scene(scene_index):
    rng = np.random.default_rng(20261105 + scene_index)
    spread = float(rng.choice([20.0, 80.0, 200.0]))
    motor_count = int(rng.integers(0, 6))
    non_motor_count = int(rng.integers(0, 6))
    if scene_index % 41 == 0:
        motor_count = 0
    if scene_index % 43 == 0:
        non_motor_count = 0

    specs = []
    for index in range(motor_count):
        specs.append(_random_track_spec(rng, 1000 + index, "motor", spread, index))
    for index in range(non_motor_count):
        specs.append(
            _random_track_spec(rng, 5000 + index, "non_motor", spread, 40 + index)
        )
    if scene_index % 3 == 0:
        specs.extend(_positive_pair_specs())
    if scene_index % 5 == 0:
        # 嵌套检测是同物异类，必须与相邻 ENU 位置一起出现；其余随机框置空避免
        # 构造出“像素嵌套但世界坐标很远”的非现实几何。
        for spec in specs:
            spec["bbox"] = None
        specs.extend(_nested_pair_specs())

    return {
        "tracks": specs,
        "timestamps": [20.0, 20.5],
        "anchor_gcj02": (121.5, 31.2) if scene_index % 2 == 0 else None,
        "flight_phase": str(rng.choice(["hover", "cruise"])),
        "flight_segment_id": f"runtime-flight-{scene_index % 4}",
        "config_overrides": {
            "max_pair_distance_m": float(rng.choice([5.0, 10.0, 15.0, 20.0, 30.0])),
            # enable_same_time_cpa 保持生产默认 False：该实验分支的事件负载缺
            # min_same_time_distance_m（HEAD 既有潜在问题，不属本次预筛范围）。
            "emit_cooldown_sec": float(rng.choice([0.5, 2.0, 3.0])),
            "min_trajectory_length_m": float(rng.choice([1.0, 3.0, 5.0])),
            "max_current_observation_age_sec": float(rng.choice([0.05, 0.1])),
        },
    }


# ── 测试 ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("scene_index", range(RANDOM_SCENE_COUNT))
def test_random_scene_grid_and_legacy_paths_are_identical(scene_index):
    scene = _random_scene(scene_index)
    _assert_scene_equivalent(scene, f"random-scene-{scene_index}")


def test_default_switch_is_enabled_and_false_value_disables_grid(monkeypatch):
    monkeypatch.delenv(ENV_KEY, raising=False)
    enabled_default = ConflictDetectionNode(_config())
    monkeypatch.setenv(ENV_KEY, "true")
    enabled_true = ConflictDetectionNode(_config())
    monkeypatch.setenv(ENV_KEY, "0")
    disabled_zero = ConflictDetectionNode(_config())
    monkeypatch.setenv(ENV_KEY, "false")
    disabled_false = ConflictDetectionNode(_config())

    assert enabled_default.grid_prefilter_enabled is True
    assert enabled_true.grid_prefilter_enabled is True
    assert disabled_zero.grid_prefilter_enabled is False
    assert disabled_false.grid_prefilter_enabled is False


def test_grid_cell_size_is_derived_from_max_pair_distance():
    narrow = ConflictDetectionNode(_config(max_pair_distance_m=5.0))
    wide = ConflictDetectionNode(_config(max_pair_distance_m=20.0))

    assert narrow._grid_cell_size() == pytest.approx(5.0, rel=1e-6)
    assert wide._grid_cell_size() == pytest.approx(20.0, rel=1e-6)
    assert ConflictDetectionNode(_config(max_pair_distance_m=0.0))._grid_cell_size() is None


def _static_scene(specs, timestamps=(20.0,), anchor=None):
    return {
        "tracks": specs,
        "timestamps": list(timestamps),
        "anchor_gcj02": anchor,
        "flight_phase": None,
        "flight_segment_id": "runtime-flight-static",
        "config_overrides": {},
    }


def _straight_spec(track_id, vehicle_class, position, velocity=(0.0, 0.0), bbox=None):
    center = np.array(position, dtype=np.float64)
    # 历史必须真的有位移才能通过 min_trajectory_length_m 资格门禁（与当前速度解耦）。
    history = _moving_history(center, np.array([1.5, 0.0]), 4, 1.0)
    return _track_spec(
        track_id,
        vehicle_class,
        center=center,
        max_speed_kmh=12.0,
        velocity=list(velocity),
        history=history,
        current_position=[float(center[0]), float(center[1])],
        bbox=bbox,
    )


def test_far_pairs_are_bulk_counted_in_candidate_and_distance_counters():
    specs = []
    for index in range(3):
        specs.append(
            _straight_spec(1000 + index, "motor", (-100.0, 10.0 * index))
        )
    for index in range(4):
        specs.append(
            _straight_spec(5000 + index, "non_motor", (100.0, 10.0 * index))
        )

    legacy_results, grid_results = _assert_scene_equivalent(
        _static_scene(specs), "far-pairs"
    )
    for events, diagnostics, _state in (legacy_results[0], grid_results[0]):
        assert events == []
        assert diagnostics["candidate_pairs"] == 12
        assert diagnostics["distance_filtered"] == 12
        assert diagnostics["nested_cross_class_detection"] == 0
        assert diagnostics["rejection_reasons"] == {"pair_distance_exceeded": 12}
        assert diagnostics["status"] == "no_prediction_candidates"


def test_far_pair_with_overlapping_bboxes_moves_one_diagnostic_counter_only():
    """Bounds the only known diagnostic divergence of the grid path.

    A cross-class pair can overlap in the image while its ground-contact ENU
    positions are farther than ``max_pair_distance_m`` (occlusion / overtaking).
    The per-pair path evaluates the containment gate first and counts
    ``nested_cross_class_detection``; the grid path never enumerates the pair and
    counts ``distance_filtered`` instead.  Neither path can emit an event for a
    far pair, so business facts are unchanged and only this diagnostic counter
    differs.  Deployments that need byte-identical diagnostics can set
    ``CONFLICT_GRID_PREFILTER=false``.
    """
    # 框完整落在画面内，避免被 participant_not_fully_visible 门禁提前剔除。
    overlapping_bbox = [100.0, 100.0, 110.0, 120.0]
    specs = [
        _straight_spec(1000, "motor", (0.0, 0.0), bbox=overlapping_bbox),
        # 50m > default max_pair_distance_m=15m, yet the bboxes are identical.
        _straight_spec(5000, "non_motor", (0.0, 50.0), bbox=overlapping_bbox),
    ]
    scene = _static_scene(specs)
    config = _config()

    legacy_results = _run_sequence(_new_node(config, grid_enabled=False), scene)
    # Force the grid path regardless of the small-scene pair threshold.
    previous_min = os.environ.get("CONFLICT_GRID_MIN_PAIRS")
    os.environ["CONFLICT_GRID_MIN_PAIRS"] = "0"
    try:
        grid_results = _run_sequence(_new_node(config, grid_enabled=True), scene)
    finally:
        if previous_min is None:
            os.environ.pop("CONFLICT_GRID_MIN_PAIRS", None)
        else:
            os.environ["CONFLICT_GRID_MIN_PAIRS"] = previous_min

    legacy_events, legacy_diagnostics, _ = legacy_results[0]
    grid_events, grid_diagnostics, _ = grid_results[0]
    assert legacy_events == [] and grid_events == []
    assert legacy_diagnostics["candidate_pairs"] == grid_diagnostics["candidate_pairs"] == 1
    assert legacy_diagnostics["nested_cross_class_detection"] == 1
    assert grid_diagnostics["nested_cross_class_detection"] == 0
    assert legacy_diagnostics["distance_filtered"] == 0
    assert grid_diagnostics["distance_filtered"] == 1
    # Only this counter pair may differ; every other diagnostic key must match.
    ignored = {"nested_cross_class_detection", "distance_filtered", "rejection_reasons"}
    assert {k: v for k, v in legacy_diagnostics.items() if k not in ignored} == {
        k: v for k, v in grid_diagnostics.items() if k not in ignored
    }


def test_pairs_exactly_at_max_distance_enter_gate_logic():
    specs = [
        _straight_spec(1000, "motor", (0.0, 0.0)),
        _straight_spec(1001, "motor", (-15.0, 0.0)),
        _straight_spec(5000, "non_motor", (15.0, 0.0)),
        _straight_spec(5001, "non_motor", (15.001, 0.0)),
        _straight_spec(5002, "non_motor", (0.5, 0.0)),
    ]

    legacy_results, grid_results = _assert_scene_equivalent(
        _static_scene(specs), "distance-boundary"
    )
    for events, diagnostics, _state in (legacy_results[0], grid_results[0]):
        assert events == []
        assert diagnostics["candidate_pairs"] == 6
        assert diagnostics["distance_filtered"] == 4
        assert diagnostics["prediction_failed"] == 2


def test_non_finite_positions_fall_back_to_per_pair_gate_semantics():
    finite_motor = _straight_spec(1000, "motor", (0.0, 0.0))
    nan_motor = _straight_spec(1001, "motor", (30.0, 30.0))
    nan_motor["current_position"] = [float("nan"), 30.0]
    finite_non_motor = _straight_spec(5000, "non_motor", (1.0, 0.0))
    nan_non_motor = _straight_spec(5001, "non_motor", (30.0, 31.0))
    nan_non_motor["current_position"] = [30.0, float("nan")]
    # 历史点数不足 min_history_points 且速度缺失：所有进入门禁的对都确定性地
    # 以 velocity_missing 拒绝，便于在没有 NaN 事件字段的情况下比较诊断。
    for spec in (finite_motor, nan_motor, finite_non_motor, nan_non_motor):
        spec["history"] = spec["history"][:3]
        spec["velocity"] = None

    legacy_results, grid_results = _assert_scene_equivalent(
        _static_scene(
            [finite_motor, nan_motor, finite_non_motor, nan_non_motor]
        ),
        "non-finite-positions",
    )
    for events, diagnostics, _state in (legacy_results[0], grid_results[0]):
        assert events == []
        assert diagnostics["candidate_pairs"] == 4
        assert diagnostics["distance_filtered"] == 0
        assert diagnostics["prediction_failed"] == 4
        assert diagnostics["rejection_reasons"] == {"velocity_missing": 4}


def _positive_pair_scene(timestamps):
    return _static_scene(
        _positive_pair_specs(), timestamps=timestamps, anchor=(121.5, 31.2)
    )


def test_multiframe_dedup_and_afterglow_match_both_paths():
    timestamps = [20.0, 20.1, 21.0, 22.5]
    scene = _positive_pair_scene(timestamps)

    legacy_results, grid_results = _assert_scene_equivalent(scene, "multiframe-dedup")

    for legacy_result, grid_result in zip(legacy_results, grid_results):
        assert legacy_result[0] == grid_result[0]
        assert legacy_result[1] == grid_result[1]
        assert legacy_result[2] == grid_result[2]

    legacy_events = [frame_events for frame_events, _d, _s in legacy_results]
    grid_events = [frame_events for frame_events, _d, _s in grid_results]
    assert legacy_events == grid_events
    assert len(legacy_events[0]) == 1
    assert legacy_events[1] == [] and legacy_events[2] == []
    assert len(legacy_events[3]) == 1
    assert legacy_results[1][1]["deduplicated"] == 1
    assert legacy_results[2][1]["deduplicated"] == 1
    assert grid_results[1][1]["deduplicated"] == 1
    assert grid_results[2][1]["deduplicated"] == 1
    assert grid_results[3][1]["events_emitted"] == 1
    assert legacy_results[3][2] == grid_results[3][2]


def test_random_scene_corpus_exercises_required_coverage():
    """防止随机语料退化：确认覆盖远端跳对、嵌套、事件、去重、缺失/静止/未观测。"""
    coverage = {
        "events": 0,
        "nested": 0,
        "distance_filtered": 0,
        "deduplicated": 0,
        "prediction_candidates": 0,
        "empty_set_scenes": 0,
        "missing_speed_scenes": 0,
        "stationary_scenes": 0,
        "stale_observation_scenes": 0,
    }
    for scene_index in range(RANDOM_SCENE_COUNT):
        scene = _random_scene(scene_index)
        specs = scene["tracks"]
        motor_count = sum(1 for spec in specs if spec["vehicle_class"] == "motor")
        non_motor_count = sum(
            1 for spec in specs if spec["vehicle_class"] == "non_motor"
        )
        if motor_count == 0 or non_motor_count == 0:
            coverage["empty_set_scenes"] += 1
        if any(spec.get("max_speed_kmh") is None for spec in specs):
            coverage["missing_speed_scenes"] += 1
        if any(
            spec.get("max_speed_kmh") is not None and spec["max_speed_kmh"] < 5.0
            for spec in specs
        ):
            coverage["stationary_scenes"] += 1
        if any(spec.get("observation_delay") == 0.2 for spec in specs):
            coverage["stale_observation_scenes"] += 1

        node = _new_node(_config(**scene["config_overrides"]), grid_enabled=True)
        for timestamp in scene["timestamps"]:
            frame = _materialize_scene(scene, timestamp)
            node.process(frame)
            coverage["events"] += frame.tcc_diagnostics["events_emitted"]
            coverage["nested"] += frame.tcc_diagnostics[
                "nested_cross_class_detection"
            ]
            coverage["distance_filtered"] += frame.tcc_diagnostics[
                "distance_filtered"
            ]
            coverage["deduplicated"] += frame.tcc_diagnostics["deduplicated"]
            coverage["prediction_candidates"] += frame.tcc_diagnostics[
                "prediction_candidates"
            ]

    assert coverage["events"] > 0
    assert coverage["nested"] > 0
    assert coverage["distance_filtered"] > 0
    assert coverage["deduplicated"] > 0
    assert coverage["prediction_candidates"] > 0
    assert coverage["empty_set_scenes"] > 0
    assert coverage["missing_speed_scenes"] > 0
    assert coverage["stationary_scenes"] > 0
    assert coverage["stale_observation_scenes"] > 0


def test_benchmark_300_tracks_200m_box_grid_is_not_slower():
    rng = np.random.default_rng(424242)
    positions = rng.uniform(-100.0, 100.0, size=(_BENCHMARK_TRACKS, 2))
    specs = []
    for index in range(_BENCHMARK_TRACKS):
        position = positions[index]
        vehicle_class = "motor" if index < _BENCHMARK_TRACKS // 2 else "non_motor"
        center = np.array([float(position[0]), float(position[1])])
        history = _moving_history(center, np.array([1.0, 0.5]), 5, 1.0)
        specs.append(
            _track_spec(
                index + 1,
                vehicle_class,
                center=center,
                max_speed_kmh=12.0,
                velocity=[0.0, 0.0],
                history=history,
                current_position=[float(center[0]), float(center[1])],
            )
        )
    scene = _static_scene(specs)

    config = _config()
    legacy = _new_node(config, grid_enabled=False)
    grid = _new_node(config, grid_enabled=True)
    expected_pairs = (_BENCHMARK_TRACKS // 2) * (_BENCHMARK_TRACKS // 2)

    verify_legacy_frame = _materialize_scene(scene, 20.0)
    legacy.process(verify_legacy_frame)
    verify_grid_frame = _materialize_scene(scene, 20.0)
    grid.process(verify_grid_frame)
    assert verify_grid_frame.conflict_events == verify_legacy_frame.conflict_events
    assert verify_grid_frame.tcc_diagnostics == verify_legacy_frame.tcc_diagnostics
    assert verify_grid_frame.tcc_diagnostics["candidate_pairs"] == expected_pairs

    def _timed_runs(node, iterations):
        frame = _materialize_scene(scene, 20.0)
        durations = []
        for _ in range(iterations + 1):
            node._reported_pairs.clear()
            started = time.perf_counter()
            node.process(frame)
            durations.append((time.perf_counter() - started) * 1000.0)
        return durations[1:]

    legacy_ms = []
    grid_ms = []
    for _ in range(7):
        legacy_ms.extend(_timed_runs(legacy, 1))
        grid_ms.extend(_timed_runs(grid, 1))
    legacy_median = statistics.median(legacy_ms)
    grid_median = statistics.median(grid_ms)
    speedup = legacy_median / grid_median if grid_median > 0 else float("inf")

    print(
        f"\n[conflict-grid-prefilter] 300 tracks / {expected_pairs:,} pairs: "
        f"legacy median={legacy_median:.2f} ms, grid median={grid_median:.2f} ms, "
        f"speedup={speedup:.2f}x"
    )
    assert grid_median <= legacy_median, (
        f"grid prefilter slower than legacy path: "
        f"grid={grid_median:.2f} ms legacy={legacy_median:.2f} ms"
    )
