"""Equivalence and cost guards for incremental world / GCJ-02 tail projection.

``PostTrackingWorldProjectionNode`` historically rebuilt, for every track and
every frame, a copy of the whole bounded ENU tail, a copy of every lineage
dict, and a full ENU->GCJ-02 re-conversion of the tail.  The incremental path
keeps the emitted contracts byte-identical while converting only the points
that were appended since the previous frame.  This module drives the real
tracker + projection nodes over a long synthetic scenario with the
``WORLD_PROJECTION_INCREMENTAL`` switch in both positions and compares every
emitted field frame by frame.
"""

from __future__ import annotations

import copy
import os
import statistics
import time

import numpy as np

import nodes.PostTrackingWorldProjectionNode as projection_module
from elements.FrameElement import FrameElement
from nodes.GroundTrajectoryTrackerNode import GroundTrajectoryTrackerNode
from nodes.PostTrackingWorldProjectionNode import PostTrackingWorldProjectionNode

FRAME_COUNT = 170
FRAME_DT = 0.05
FRAME_HEIGHT = 480
FRAME_WIDTH = 640
CANDIDATE_ASSOCIATION_ID = 9001
CANDIDATE_FIRST_FRAME = 10
CANDIDATE_LAST_FRAME = 139
INCREMENTAL_ENV = "WORLD_PROJECTION_INCREMENTAL"

# The frame-by-frame comparison covers every field the projection node emits.
_EMITTED_TRAJECTORY_FIELDS = (
    "track_id",
    "association_id",
    "trajectory_output_eligible",
    "geo_analytics_eligible",
    "road_analytics_eligible",
    "tcc_analytics_eligible",
    "tracking_quality",
    "geo_reference_quality",
    "road_match_quality",
    "quality_reasons",
    "flight_phase",
    "flight_segment_id",
    "anchor_gcj02",
    "trajectory_enu_m",
    "trajectory_gcj02",
    "point_quality_lineage",
)


def _config() -> dict:
    return {
        "tracking_node": {
            "first_track_thresh": 0.5,
            "second_track_thresh": 0.1,
            "match_thresh": 0.8,
            "track_buffer": 30,
            "max_lost_sec": 2.0,
            "max_frame_gap_sec": 0.5,
            "candidate_trajectory_tail_points": 30,
        }
    }


def _projection_matrix() -> np.ndarray:
    return np.array([[0.1, 0.0, 0.0], [0.0, 0.1, 0.0], [0.0, 0.0, 1.0]])


def _detection(center_x: float, center_y: float) -> list[float]:
    width, height = 30.0, 20.0
    return [
        center_x - width / 2.0,
        center_y - height / 2.0,
        center_x + width / 2.0,
        center_y + height / 2.0,
    ]


def _detections_for(index: int) -> list[list[float]]:
    boxes = [_detection(50.0 + 1.5 * index, 100.0)]
    if index <= 50:
        boxes.append(_detection(500.0 - 2.0 * index, 400.0))
    if index >= 30:
        boxes.append(_detection(100.0 + 1.0 * (index - 30), 250.0))
    if 80 <= index <= 120:
        boxes.append(_detection(400.0 + 1.2 * (index - 80), 200.0))
    return boxes


def _anchor_for(index: int):
    if index < 40:
        return (117.0, 36.0)
    if index < 70:
        return (117.5123, 36.7123)
    if index == 70:
        return (117.6001, 36.8001)
    if index < 80:
        return (117.5123, 36.7123)
    if index < 100:
        return None
    if index < 140:
        return (117.0, 36.0)
    if index < 160:
        return (116.9002, 35.9003)
    return (117.0, 36.0)


def _geo_flags_for(index: int) -> dict:
    if 90 <= index <= 97:
        return {
            "geo_analytics_eligible": False,
            "road_analytics_eligible": False,
            "tcc_analytics_eligible": True,
        }
    if 110 <= index <= 112 or 150 <= index <= 152:
        return {
            "geo_analytics_eligible": True,
            "road_analytics_eligible": False,
            "tcc_analytics_eligible": True,
        }
    if 130 <= index <= 132:
        return {
            "geo_analytics_eligible": True,
            "road_analytics_eligible": False,
            "tcc_analytics_eligible": True,
        }
    if 115 <= index <= 121:
        return {
            "geo_analytics_eligible": False,
            "road_analytics_eligible": True,
            "tcc_analytics_eligible": True,
        }
    return {
        "geo_analytics_eligible": True,
        "road_analytics_eligible": True,
        "tcc_analytics_eligible": True,
    }


def _projection_for(index: int) -> np.ndarray:
    if 20 <= index <= 27 or 145 <= index <= 147:
        # Invalid homography: the ENU point of those frames is None.
        return np.zeros((3, 3))
    return _projection_matrix()


def _quality_for(index: int) -> dict:
    if 90 <= index <= 97:
        return {
            "status": "degraded",
            "geo_status": "degraded",
            "reasons": ["geo_unavailable"],
        }
    if 110 <= index <= 112 or 150 <= index <= 152:
        return {
            "status": "verified",
            "geo_status": "verified",
            "reasons": [],
            "road_reasons": ["lane_verified_map_required"],
        }
    if 130 <= index <= 132:
        return {
            "status": "degraded",
            "geo_status": "verified",
            "reasons": ["lane_verified_map_required"],
            "road_reasons": [
                "lane_verified_map_required",
                "road_match_low_confidence",
            ],
        }
    return {"status": "verified", "geo_status": "verified"}


def _build_frame(index: int) -> FrameElement:
    boxes = _detections_for(index)
    frame = FrameElement(
        source="test",
        frame=np.zeros((FRAME_HEIGHT, FRAME_WIDTH, 3), dtype=np.uint8),
        timestamp=float(index * FRAME_DT),
        frame_num=int(index),
        roads_info={},
        detected_conf=[0.9] * len(boxes),
        detected_cls=["car"] * len(boxes),
        detected_cls_ids=[3] * len(boxes),
        detected_xyxy=[list(box) for box in boxes],
    )
    frame.camera_motion_warp = np.eye(3)
    frame.formal_analytics_eligible = True
    return frame


def _apply_projection_inputs(index: int, frame: FrameElement) -> None:
    frame.pixel_to_world_enu = _projection_for(index)
    frame.anchor_gcj02 = _anchor_for(index)
    frame.geo_reference_quality = _quality_for(index)
    flags = _geo_flags_for(index)
    frame.geo_analytics_eligible = flags["geo_analytics_eligible"]
    frame.road_analytics_eligible = flags["road_analytics_eligible"]
    frame.tcc_analytics_eligible = flags["tcc_analytics_eligible"]
    frame.flight_phase = "hover" if index % 3 else "cruise"
    frame.flight_segment_id = f"segment-{index // 60}"


def _raw_frames():
    """Yield real tracker output frames with a synthetic candidate association."""
    tracker = GroundTrajectoryTrackerNode(_config())
    candidate_px: list[list[float]] = []
    candidate_timestamps: list[float] = []
    candidate_frame_nums: list[int] = []
    for index in range(FRAME_COUNT):
        tracked = tracker.process(_build_frame(index))
        _apply_projection_inputs(index, tracked)
        if CANDIDATE_FIRST_FRAME <= index <= CANDIDATE_LAST_FRAME:
            candidate_px.append([float(200 + 0.5 * (index - CANDIDATE_FIRST_FRAME)), 350.0])
            candidate_px = candidate_px[-30:]
            candidate_timestamps.append(float(index * FRAME_DT))
            candidate_timestamps = candidate_timestamps[-30:]
            candidate_frame_nums.append(index)
            candidate_frame_nums = candidate_frame_nums[-30:]
            tracked.association_trajectories.append(
                {
                    "track_id": CANDIDATE_ASSOCIATION_ID,
                    "association_id": CANDIDATE_ASSOCIATION_ID,
                    "tracking_method": "motion_compensated_image_v2",
                    "trajectory_px": [list(point) for point in candidate_px],
                    "trajectory_timestamps_sec": list(candidate_timestamps),
                    "trajectory_frame_nums": list(candidate_frame_nums),
                }
            )
            diagnostics = dict(tracked.tracking_diagnostics or {})
            state_ids = set(diagnostics.get("association_state_ids") or [])
            diagnostics["association_state_ids"] = sorted(
                state_ids | {CANDIDATE_ASSOCIATION_ID}
            )
            tracked.tracking_diagnostics = diagnostics
        yield tracked


def _snapshot(frame_element: FrameElement) -> dict:
    diagnostics = frame_element.tracking_diagnostics or {}
    return {
        "association_trajectories": copy.deepcopy(
            frame_element.association_trajectories
        ),
        "candidate_trajectories": copy.deepcopy(frame_element.candidate_trajectories),
        "track_id_by_association": copy.deepcopy(
            frame_element.track_id_by_association
        ),
        "formal_track_ids": copy.deepcopy(frame_element.formal_track_ids),
        "formal_track_id_by_association": copy.deepcopy(
            frame_element.formal_track_id_by_association
        ),
        "previous_formal_track_id_by_association": copy.deepcopy(
            frame_element.previous_formal_track_id_by_association
        ),
        "trajectory_association_ids": copy.deepcopy(
            frame_element.trajectory_association_ids
        ),
        "terminated_track_ids": copy.deepcopy(diagnostics.get("terminated_track_ids")),
        "terminated_association_ids": copy.deepcopy(
            diagnostics.get("terminated_association_ids")
        ),
    }


def _collect_scenario() -> dict:
    previous_env = os.environ.get(INCREMENTAL_ENV)
    try:
        os.environ[INCREMENTAL_ENV] = "false"
        legacy = PostTrackingWorldProjectionNode(_config())
        os.environ[INCREMENTAL_ENV] = "true"
        incremental = PostTrackingWorldProjectionNode(_config())
    finally:
        if previous_env is None:
            os.environ.pop(INCREMENTAL_ENV, None)
        else:
            os.environ[INCREMENTAL_ENV] = previous_env

    real_convert = projection_module.enu_to_gcj02
    conversions = {"legacy": 0, "incremental": 0}

    def _counting_convert(convert_key: str):
        def wrapper(easting_m, northing_m, anchor_gcj02):
            conversions[convert_key] += 1
            return real_convert(easting_m, northing_m, anchor_gcj02)

        return wrapper

    legacy_snapshots = []
    incremental_snapshots = []
    lifecycle = []
    try:
        for raw in _raw_frames():
            projection_module.enu_to_gcj02 = _counting_convert("legacy")
            legacy_result = legacy.process(copy.deepcopy(raw))
            projection_module.enu_to_gcj02 = _counting_convert("incremental")
            incremental_result = incremental.process(copy.deepcopy(raw))
            legacy_snapshots.append(_snapshot(legacy_result))
            incremental_snapshots.append(_snapshot(incremental_result))
            lifecycle.append(
                {
                    "world_history_ids": set(incremental._world_history),
                    "gcj_cache_ids": set(
                        getattr(incremental, "_gcj_tail_cache", {})
                    ),
                    "append_count_ids": set(
                        getattr(incremental, "_append_counts", {})
                    ),
                }
            )
    finally:
        projection_module.enu_to_gcj02 = real_convert

    return {
        "legacy": legacy_snapshots,
        "incremental": incremental_snapshots,
        "lifecycle": lifecycle,
        "conversions": conversions,
    }


_SCENARIO: dict | None = None


def _scenario() -> dict:
    global _SCENARIO
    if _SCENARIO is None:
        _SCENARIO = _collect_scenario()
    return _SCENARIO


def test_incremental_projection_matches_legacy_frame_by_frame():
    scenario = _scenario()
    assert len(scenario["legacy"]) == FRAME_COUNT >= 150
    for index, (legacy_snapshot, incremental_snapshot) in enumerate(
        zip(scenario["legacy"], scenario["incremental"])
    ):
        assert incremental_snapshot == legacy_snapshot, f"frame {index} diverged"


def test_scenario_exercises_projection_state_transitions():
    snapshots = _scenario()["legacy"]
    anchors = set()
    enu_none_with_anchor = 0
    gcj_missing_frames = 0
    mature_ids = set()
    candidate_ids = set()
    terminated = set()
    maximum_tail = 0
    appearance_growth = []
    seen_association_ids = set()
    for snapshot in snapshots:
        frame_association_ids = set()
        for item in snapshot["association_trajectories"]:
            for field in _EMITTED_TRAJECTORY_FIELDS:
                if field in {"anchor_gcj02", "trajectory_gcj02"}:
                    continue
                assert field in item
            frame_association_ids.add(item["association_id"])
            maximum_tail = max(maximum_tail, len(item["trajectory_enu_m"]))
            if "anchor_gcj02" in item:
                anchors.add(tuple(item["anchor_gcj02"]))
                if "trajectory_gcj02" in item:
                    assert len(item["trajectory_gcj02"]) == len(
                        item["trajectory_enu_m"]
                    )
                    for enu_point, gcj_point in zip(
                        item["trajectory_enu_m"], item["trajectory_gcj02"]
                    ):
                        assert (enu_point is None) == (gcj_point is None)
                        if enu_point is None:
                            enu_none_with_anchor += 1
            else:
                gcj_missing_frames += 1
            if item["trajectory_output_eligible"]:
                mature_ids.add(item["association_id"])
        for item in snapshot["candidate_trajectories"]:
            candidate_ids.add(item["association_id"])
            assert item["trajectory_output_eligible"] is False
        terminated.update(snapshot["terminated_track_ids"] or [])
        appearance_growth.append(len(frame_association_ids - seen_association_ids))
        seen_association_ids.update(frame_association_ids)

    assert len(anchors) >= 4
    assert any(
        "anchor_gcj02" not in item
        for snapshot in snapshots
        for item in snapshot["association_trajectories"]
    )
    assert enu_none_with_anchor > 0
    assert gcj_missing_frames > 0
    assert mature_ids
    assert CANDIDATE_ASSOCIATION_ID in candidate_ids
    assert candidate_ids - mature_ids
    assert terminated
    assert maximum_tail == 30
    assert sum(1 for growth in appearance_growth if growth) >= 3


def test_incremental_converts_only_new_tail_points():
    conversions = _scenario()["conversions"]
    assert conversions["legacy"] > 0
    assert conversions["incremental"] > 0
    assert conversions["incremental"] * 3 < conversions["legacy"]


def test_incremental_cache_releases_closed_tracks():
    lifecycle = _scenario()["lifecycle"]
    seen_ids: set[int] = set()
    released_ids: set[int] = set()
    for record in lifecycle:
        world_ids = record["world_history_ids"]
        cache_ids = record["gcj_cache_ids"]
        append_ids = record["append_count_ids"]
        assert cache_ids <= world_ids
        assert append_ids == world_ids
        for association_id in seen_ids - world_ids:
            assert association_id not in cache_ids
            released_ids.add(association_id)
        seen_ids |= world_ids
    assert released_ids


def _manual_projection_frame() -> FrameElement:
    frame = FrameElement(
        source="manual",
        frame=np.zeros((FRAME_HEIGHT, FRAME_WIDTH, 3), dtype=np.uint8),
        timestamp=0.0,
        frame_num=0,
        roads_info={},
    )
    frame.pixel_to_world_enu = _projection_matrix()
    frame.geo_reference_quality = {"status": "verified", "geo_status": "verified"}
    frame.geo_analytics_eligible = True
    frame.road_analytics_eligible = True
    frame.tcc_analytics_eligible = True
    frame.flight_phase = "hover"
    frame.flight_segment_id = "manual"
    frame.id_list = [1, 2]
    frame.tracking_diagnostics = {"association_state_ids": [1, 2]}
    return frame


def _drive_anchor_sequence(incremental: bool):
    anchors = (
        [(117.0, 36.0)] * 10
        + [(117.5123, 36.7123)] * 5
        + [None] * 46
        + [(117.0, 36.0)] * 5
        + [(117.5123, 36.7123)] * 5
    )
    previous_env = os.environ.get(INCREMENTAL_ENV)
    try:
        os.environ[INCREMENTAL_ENV] = "true" if incremental else "false"
        node = PostTrackingWorldProjectionNode(_config())
    finally:
        if previous_env is None:
            os.environ.pop(INCREMENTAL_ENV, None)
        else:
            os.environ[INCREMENTAL_ENV] = previous_env
    frame = _manual_projection_frame()
    px_history = {1: [], 2: []}
    real_convert = projection_module.enu_to_gcj02
    conversions = 0

    def _counting_convert(easting_m, northing_m, anchor_gcj02):
        nonlocal conversions
        conversions += 1
        return real_convert(easting_m, northing_m, anchor_gcj02)

    snapshots = []
    frames_without_gcj = 0
    projection_module.enu_to_gcj02 = _counting_convert
    try:
        for step, anchor in enumerate(anchors):
            for track_id in (1, 2):
                px_history[track_id].append(
                    [track_id * 10.0 + step, 20.0 + 0.1 * step]
                )
            frame.association_trajectories = [
                {
                    "track_id": track_id,
                    "association_id": track_id,
                    "tracking_method": "motion_compensated_image_v2",
                    "trajectory_px": [list(point) for point in px_history[track_id]],
                }
                for track_id in (1, 2)
            ]
            frame.anchor_gcj02 = anchor
            frame.timestamp = step * 0.1
            frame.frame_num = step
            node._enrich_trajectories(frame, {1, 2}, {1, 2})
            snapshots.append(copy.deepcopy(frame.association_trajectories))
            if anchor is None:
                assert all(
                    "trajectory_gcj02" not in item
                    for item in frame.association_trajectories
                )
                frames_without_gcj += 1
    finally:
        projection_module.enu_to_gcj02 = real_convert
    assert frames_without_gcj == 46
    flush_result = node.flush("natural_eof")
    assert flush_result["termination_reason"] == "natural_eof"
    assert not node._world_history
    assert not node._append_counts
    assert not node._gcj_tail_cache
    return snapshots, conversions


def test_anchor_changes_invalidate_the_cached_gcj_tail():
    legacy_snapshots, legacy_conversions = _drive_anchor_sequence(incremental=False)
    incremental_snapshots, incremental_conversions = _drive_anchor_sequence(
        incremental=True
    )
    assert incremental_snapshots == legacy_snapshots
    assert incremental_conversions < legacy_conversions
    # After a None gap longer than the bounded tail the whole tail is rebuilt,
    # so every point is still present and anchored to the current anchor.
    last_items = incremental_snapshots[-1]
    for item in last_items:
        assert len(item["trajectory_enu_m"]) == 30
        assert len(item["trajectory_gcj02"]) == 30
        assert item["anchor_gcj02"] == [
            round(117.5123, 6),
            round(36.7123, 6),
        ]


def test_incremental_is_default_and_switch_disables_it(monkeypatch):
    monkeypatch.delenv(INCREMENTAL_ENV, raising=False)
    assert PostTrackingWorldProjectionNode(_config())._incremental is True
    monkeypatch.setenv(INCREMENTAL_ENV, "false")
    assert PostTrackingWorldProjectionNode(_config())._incremental is False


_BENCHMARK_TRACKS = 300
_BENCHMARK_POINTS = 30
_BENCHMARK_SAMPLES = 7
_BENCHMARK_ITERATIONS = 3


def _benchmark_frame() -> FrameElement:
    frame = FrameElement(
        source="bench",
        frame=np.zeros((FRAME_HEIGHT, FRAME_WIDTH, 3), dtype=np.uint8),
        timestamp=0.0,
        frame_num=0,
        roads_info={},
    )
    frame.pixel_to_world_enu = _projection_matrix()
    frame.geo_reference_quality = {"status": "verified", "geo_status": "verified"}
    frame.geo_analytics_eligible = True
    frame.road_analytics_eligible = True
    frame.tcc_analytics_eligible = True
    frame.anchor_gcj02 = (117.0, 36.0)
    frame.flight_phase = "hover"
    frame.flight_segment_id = "benchmark"
    association_ids = list(range(1, _BENCHMARK_TRACKS + 1))
    frame.association_trajectories = [
        {
            "track_id": association_id,
            "association_id": association_id,
            "tracking_method": "motion_compensated_image_v2",
            "trajectory_px": [
                [10.0 + 0.25 * step, 20.0 + float(association_id % 7)]
                for step in range(_BENCHMARK_POINTS)
            ],
        }
        for association_id in association_ids
    ]
    frame.id_list = association_ids
    frame.tracking_diagnostics = {"association_state_ids": list(association_ids)}
    return frame


def _prefill_benchmark_history(node, frame: FrameElement) -> None:
    tail = max(node._tail_points, 1)
    lineage_unit = {
        "timestamp_sec": 0.0,
        "frame_num": 0,
        "flight_phase": "hover",
        "flight_segment_id": "benchmark",
        "geo_reference_quality": "verified",
        "tracking_quality": "verified",
    }
    for index, association_id in enumerate(frame.id_list):
        point_count = tail - 1
        node._world_history[association_id] = {
            "trajectory_enu_m": [
                [float(index) + 0.01 * step, 0.5 * step]
                for step in range(point_count)
            ],
            "trajectory_timestamps_sec": [
                0.01 * step for step in range(point_count)
            ],
            "trajectory_frame_nums": list(range(point_count)),
            "point_quality_lineage": [dict(lineage_unit) for _ in range(point_count)],
        }
        if hasattr(node, "_append_counts"):
            node._append_counts[association_id] = point_count


def _measure_projection_ms(incremental: bool) -> float:
    previous_env = os.environ.get(INCREMENTAL_ENV)
    try:
        os.environ[INCREMENTAL_ENV] = "true" if incremental else "false"
        node = PostTrackingWorldProjectionNode(_config())
    finally:
        if previous_env is None:
            os.environ.pop(INCREMENTAL_ENV, None)
        else:
            os.environ[INCREMENTAL_ENV] = previous_env
    frame = _benchmark_frame()
    active_ids = set(frame.id_list)
    _prefill_benchmark_history(node, frame)
    # Warm once so the incremental cache is primed and the timed loop measures
    # the steady-state per-frame cost.
    node._enrich_trajectories(frame, active_ids, active_ids)
    samples = []
    for _ in range(_BENCHMARK_SAMPLES):
        started = time.perf_counter()
        for _ in range(_BENCHMARK_ITERATIONS):
            node._enrich_trajectories(frame, active_ids, active_ids)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        samples.append(elapsed_ms / _BENCHMARK_ITERATIONS)
    return statistics.median(samples)


def test_incremental_projection_is_not_slower_than_legacy():
    legacy_ms = _measure_projection_ms(incremental=False)
    incremental_ms = _measure_projection_ms(incremental=True)
    ratio = legacy_ms / incremental_ms if incremental_ms > 0 else float("inf")
    print(
        f"world projection micro-benchmark ({_BENCHMARK_TRACKS} tracks x "
        f"{_BENCHMARK_POINTS} ENU points, fixed anchor): "
        f"legacy={legacy_ms:.3f} ms, incremental={incremental_ms:.3f} ms, "
        f"ratio={ratio:.2f}x"
    )
    assert incremental_ms <= legacy_ms
