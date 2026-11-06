"""Batch-warp equivalence and latency tests for the image tracker history.

``GroundTrajectoryTrackerNode._build_image_trajectories`` used to run one tiny
numpy warp per track per frame (plus a per-point ``list.copy()`` and a fresh
homogeneous matrix per track).  The batched path (``TRACKER_BATCH_WARP=1``,
default) projects every track's display trail with a single matmul while keeping
the exact historical fallback semantics per track.

These tests drive the real node through 140 synthetic frames that cover: no
warp, valid 3x3 warp, valid 2x3 warp, NaN warp, singular warp, wrong-shape
warp, a warp applied mid-life, a track that disappears and is re-activated, and
two tracks with different history lengths.  Both switch values must emit
byte-identical image-history facts for every frame.
"""

from __future__ import annotations

import statistics
import time
from types import SimpleNamespace

import numpy as np

from elements.FrameElement import FrameElement
from nodes.GroundTrajectoryTrackerNode import GroundTrajectoryTrackerNode

SCENARIO_FRAMES = 140
SCENARIO_FRAME_INTERVAL_SEC = 0.04
TRACK_A_BORN = 0
TRACK_A_MISSING = range(60, 68)
TRACK_B_BORN = 5
TRACK_C_BORN = 35

BENCHMARK_TRACKS = 300
BENCHMARK_POINTS = 30
BENCHMARK_RUNS = 9

TRAJECTORY_FIELDS = (
    "track_id",
    "trajectory_px",
    "trajectory_display_px",
    "trajectory_timestamps_sec",
    "trajectory_frame_nums",
)


def _config() -> dict:
    return {
        "general": {"buffer_analytics": 1, "min_time_life_track": 0},
        "trajectory": {"min_track_duration_sec": 0.0},
        "tracking_node": {
            "first_track_thresh": 0.5,
            "second_track_thresh": 0.1,
            "match_thresh": 0.8,
            "track_buffer": 30,
            "max_lost_sec": 2.0,
            "max_frame_gap_sec": 0.5,
        },
    }


def _frame(timestamp: float, boxes, frame_num: int) -> FrameElement:
    frame = FrameElement(
        source="test",
        frame=np.zeros((480, 640, 3), dtype=np.uint8),
        timestamp=timestamp,
        frame_num=frame_num,
        roads_info={},
        detected_conf=[0.9] * len(boxes),
        detected_cls=["car"] * len(boxes),
        detected_cls_ids=[3] * len(boxes),
        detected_xyxy=boxes,
    )
    frame.camera_motion_warp = None
    return frame


def _warp_for(index: int):
    """Per-frame camera warp covering every fallback branch of the node."""
    if index < 30:  # no warp
        return None
    if index < 70:  # valid identity warp over a long stretch (mid-life)
        return np.eye(3)
    if index == 70:  # valid 3x3 translation warp, changes trail values
        return np.array([[1.0, 0.0, 3.0], [0.0, 1.0, -2.0], [0.0, 0.0, 1.0]])
    if index == 71:  # valid affine 2x3 warp (ByteTrack ignores it, node accepts)
        return np.array([[1.0, 0.0, -2.0], [0.0, 1.0, 1.0]])
    if 72 <= index <= 75:  # non-finite warp
        return np.full((3, 3), np.nan)
    if 76 <= index <= 79:  # singular warp: every denominator is zero
        return np.zeros((3, 3))
    if index == 80:  # wrong shape
        return np.eye(4)
    return None


def _scenario_specs() -> list[dict]:
    specs = []
    for index in range(SCENARIO_FRAMES):
        boxes = []
        if index >= TRACK_A_BORN and index not in TRACK_A_MISSING:
            left = 20.0 + 1.2 * index
            boxes.append([left, 20.0, left + 20.0, 40.0])
        if index >= TRACK_B_BORN:
            top = 120.0 + 0.8 * index
            boxes.append([420.0 - 0.6 * index, top, 460.0 - 0.6 * index, top + 20.0])
        if index >= TRACK_C_BORN:  # third track has a shorter image history
            left = 300.0 + 1.0 * index
            boxes.append([left, 300.0, left + 20.0, 320.0])
        specs.append(
            {
                "timestamp": index * SCENARIO_FRAME_INTERVAL_SEC,
                "frame_num": index,
                "boxes": boxes,
                "warp": _warp_for(index),
            }
        )
    return specs


def _run_scenario(monkeypatch, *, batch: bool):
    monkeypatch.setenv("TRACKER_BATCH_WARP", "1" if batch else "0")
    node = GroundTrajectoryTrackerNode(_config())
    assert node._batch_warp is batch
    emitted = []
    for spec in _scenario_specs():
        frame = _frame(spec["timestamp"], spec["boxes"], spec["frame_num"])
        frame.camera_motion_warp = spec["warp"]
        result = node.process(frame)
        emitted.append(
            [
                {field: trajectory[field] for field in TRAJECTORY_FIELDS}
                for trajectory in (result.association_trajectories or [])
            ]
        )
    return node, emitted


def _trajectory_by_id(frame_trajectories) -> dict[int, dict]:
    return {int(item["track_id"]): item for item in frame_trajectories}


def test_batched_warp_matches_per_track_path_on_every_frame(monkeypatch):
    old_node, old_frames = _run_scenario(monkeypatch, batch=False)
    new_node, new_frames = _run_scenario(monkeypatch, batch=True)

    assert old_node._batch_warp is False
    assert new_node._batch_warp is True
    assert len(old_frames) == len(new_frames) == SCENARIO_FRAMES
    for index, (old, new) in enumerate(zip(old_frames, new_frames)):
        assert new == old, f"frame {index} image history differs between warp paths"

    # -- the scenario really exercised the intended branches -----------------
    warp_specs = [spec["warp"] for spec in _scenario_specs()]
    assert warp_specs[0] is None
    assert np.array_equal(warp_specs[30], np.eye(3))
    assert warp_specs[70].shape == (3, 3)
    assert warp_specs[71].shape == (2, 3)
    assert np.isnan(warp_specs[72]).all()
    assert not np.any(warp_specs[76])

    track_a_id = int(old_frames[TRACK_A_BORN][0]["track_id"])
    assert track_a_id in _trajectory_by_id(old_frames[59])
    for index in TRACK_A_MISSING:  # history survives the lost window internally
        assert track_a_id not in _trajectory_by_id(old_frames[index])
    assert track_a_id in _trajectory_by_id(old_frames[68])

    # two live tracks with different image-history lengths at frame 45
    # (uncompensated frames keep only the new point, so trails grow when the
    # valid warp starts at frame 30; the late-born track C is shorter).
    lengths = {len(item["trajectory_display_px"]) for item in old_frames[45]}
    assert len(old_frames[45]) == 3 and len(lengths) == 2

    # valid mid-life warp rewrites the older display points in place; the
    # 30-point tail trim then drops the oldest warped point
    before = _trajectory_by_id(old_frames[69])[track_a_id]["trajectory_display_px"]
    after = _trajectory_by_id(old_frames[70])[track_a_id]["trajectory_display_px"]
    assert after[: len(before) - 1] == [
        [round(point[0] + 3.0, 2), round(point[1] - 2.0, 2)]
        for point in before[1:]
    ]
    assert len(after) == len(before)

    # NaN/singular warps clear the trail and keep only the new point
    for index in (72, 74, 78):
        for item in old_frames[index]:
            assert len(item["trajectory_display_px"]) == 1
    assert len(_trajectory_by_id(old_frames[71])[track_a_id]["trajectory_display_px"]) > 1


def test_mixed_valid_and_invalid_tracks_fall_back_in_same_frame(monkeypatch):
    """One warped track and one degenerate track in the same frame."""

    def seeded_node(*, batch: bool):
        monkeypatch.setenv("TRACKER_BATCH_WARP", "1" if batch else "0")
        node = GroundTrajectoryTrackerNode(_config())
        node._image_history = {
            1: {
                "trajectory_px": [[100.0, 200.0], [110.0, 200.0], [120.0, 200.0]],
                "trajectory_display_px": [
                    [100.0, 100.0],
                    [110.0, 100.0],
                    [120.0, 100.0],
                ],
                "trajectory_timestamps_sec": [0.0, 0.1, 0.2],
                "trajectory_frame_nums": [0, 1, 2],
            },
            2: {
                "trajectory_px": [[200.0, 200.0], [210.0, 200.0]],
                "trajectory_display_px": [[200.0, 30.0], [210.0, 30.0]],
                "trajectory_timestamps_sec": [0.0, 0.1],
                "trajectory_frame_nums": [0, 1],
            },
        }
        node._active_track_ids = lambda: [1, 2]
        return node

    # Denominator is 0.01*y - 0.3: live for y=100 (track 1), degenerate for
    # y=30 (track 2) -- valid/invalid mixed inside one frame.
    warp = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.01, -0.3]])
    tracks = [
        SimpleNamespace(track_id=1, tlbr=[10.0, 20.0, 30.0, 40.0]),
        SimpleNamespace(track_id=2, tlbr=[40.0, 150.0, 60.0, 170.0]),
    ]

    results = {}
    for batch in (False, True):
        node = seeded_node(batch=batch)
        frame = _frame(1.0, [], 10)
        frame.camera_motion_warp = warp
        trajectories = node._build_image_trajectories(frame, tracks)
        results[batch] = [
            {field: item[field] for field in TRAJECTORY_FIELDS}
            for item in trajectories
        ]

    assert results[True] == results[False]
    by_id = {int(item["track_id"]): item for item in results[True]}
    assert len(by_id[1]["trajectory_display_px"]) == 4  # 3 warped + new point
    assert by_id[1]["trajectory_display_px"][-1] == [20.0, 30.0]
    assert by_id[2]["trajectory_display_px"] == [[50.0, 160.0]]  # cleared + new
    assert by_id[1]["trajectory_px"] == [
        [100.0, 200.0],
        [110.0, 200.0],
        [120.0, 200.0],
        [20.0, 40.0],
    ]


def test_batched_rounding_matches_builtin_round_on_midpoint_values(monkeypatch):
    """The vectorised rounding must be bit-identical to CPython ``round(x, 2)``.

    Each pair below is a display point; neighbours of exact decimal midpoints
    and values whose ``x * 100`` lands exactly on a half-integer are included.
    """

    def seeded_node(*, batch: bool):
        monkeypatch.setenv("TRACKER_BATCH_WARP", "1" if batch else "0")
        return GroundTrajectoryTrackerNode(_config())

    midpoint_points = [
        [float(np.nextafter((k + 0.5) / 100.0, np.inf)),
         float(np.nextafter((k + 0.5) / 100.0, -np.inf))]
        for k in range(-500, 501)
    ]
    midpoint_points.extend(
        [
            [-1620.2250000000001, 1664.7450000000001],
            [16.235, 1.005],
            [2.675, 123456.785],
            [0.125, -0.375],
            [5e-324, 1e300],
            [-1e300, -0.0],
        ]
    )
    points_per_track = 15
    track_ids = list(range(1, len(midpoint_points) // points_per_track + 2))
    chunks = []
    base_history = {}
    tracks = []
    for offset, track_id in enumerate(track_ids):
        chunk = midpoint_points[
            offset * points_per_track : (offset + 1) * points_per_track
        ]
        chunks.append(chunk)
        base_history[track_id] = {
            "trajectory_px": [list(point) for point in chunk],
            "trajectory_display_px": [list(point) for point in chunk],
            "trajectory_timestamps_sec": [0.5] * len(chunk),
            "trajectory_frame_nums": [1] * len(chunk),
        }
        tracks.append(SimpleNamespace(track_id=track_id, tlbr=[10.0, 20.0, 30.0, 40.0]))

    results = {}
    for batch in (False, True):
        node = seeded_node(batch=batch)
        node._image_history = _copy_history(base_history)
        node._active_track_ids = lambda: list(track_ids)
        frame = _frame(1.0, [], 10)
        frame.camera_motion_warp = np.eye(3)
        results[batch] = node._build_image_trajectories(frame, tracks)

    assert results[True] == results[False]
    for chunk, trajectory in zip(chunks, results[True]):
        warped = trajectory["trajectory_display_px"][: len(chunk)]
        assert warped == [
            [round(point[0], 2), round(point[1], 2)] for point in chunk
        ]


def test_tracker_batch_warp_env_switch_defaults_to_on(monkeypatch):
    monkeypatch.delenv("TRACKER_BATCH_WARP", raising=False)
    assert GroundTrajectoryTrackerNode(_config())._batch_warp is True
    monkeypatch.setenv("TRACKER_BATCH_WARP", "false")
    assert GroundTrajectoryTrackerNode(_config())._batch_warp is False
    monkeypatch.setenv("TRACKER_BATCH_WARP", "0")
    assert GroundTrajectoryTrackerNode(_config())._batch_warp is False
    monkeypatch.setenv("TRACKER_BATCH_WARP", "1")
    assert GroundTrajectoryTrackerNode(_config())._batch_warp is True


def _benchmark_history() -> dict:
    history = {}
    for track_id in range(1, BENCHMARK_TRACKS + 1):
        base_x = 20.0 + (track_id % 25) * 22.0
        base_y = 40.0 + (track_id // 25) * 18.0
        display = [
            [
                round(base_x + 0.7 * step, 2),
                round(base_y + 0.4 * step + 0.05 * (step % 3), 2),
            ]
            for step in range(BENCHMARK_POINTS)
        ]
        history[track_id] = {
            "trajectory_px": [[point[0], point[1] + 10.0] for point in display],
            "trajectory_display_px": display,
            "trajectory_timestamps_sec": [
                round(step * 0.04, 6) for step in range(BENCHMARK_POINTS)
            ],
            "trajectory_frame_nums": list(range(BENCHMARK_POINTS)),
        }
    return history


def _copy_history(history: dict) -> dict:
    return {
        track_id: {
            key: [
                list(point) if isinstance(point, list) else point for point in values
            ]
            for key, values in track_history.items()
        }
        for track_id, track_history in history.items()
    }


def _median_pair_ms(old_node, new_node, tracks, frame, history) -> tuple[float, float]:
    """Interleaved old/new timings so ambient load drift cancels out."""
    old_timings: list[float] = []
    new_timings: list[float] = []
    for node, timings in (
        (old_node, old_timings),
        (new_node, new_timings),
    ):
        node._image_history = _copy_history(history)  # warm-up (unmeasured)
        node._build_image_trajectories(frame, tracks)
    for _ in range(BENCHMARK_RUNS):
        for node, timings in (
            (old_node, old_timings),
            (new_node, new_timings),
        ):
            node._image_history = _copy_history(history)
            started = time.perf_counter()
            node._build_image_trajectories(frame, tracks)
            timings.append((time.perf_counter() - started) * 1000.0)
    return statistics.median(old_timings), statistics.median(new_timings)


def test_batched_warp_benchmark_300_tracks_30_points(monkeypatch):
    def benchmark_node(*, batch: bool):
        monkeypatch.setenv("TRACKER_BATCH_WARP", "1" if batch else "0")
        node = GroundTrajectoryTrackerNode(_config())
        active_ids = list(range(1, BENCHMARK_TRACKS + 1))
        node._active_track_ids = lambda: active_ids
        return node

    tracks = [
        SimpleNamespace(
            track_id=track_id,
            tlbr=[40.0 + track_id, 260.0, 60.0 + track_id, 300.0],
        )
        for track_id in range(1, BENCHMARK_TRACKS + 1)
    ]
    frame = _frame(1.0, [], 30)
    # A typical small camera-motion warp: scale/rotation + translation + weak
    # perspective term.
    frame.camera_motion_warp = np.array(
        [
            [0.9997, 0.0041, 2.3],
            [-0.0037, 0.9989, -1.7],
            [1.2e-6, -3.4e-6, 1.0],
        ]
    )
    history = _benchmark_history()

    old_ms, new_ms = _median_pair_ms(
        benchmark_node(batch=False),
        benchmark_node(batch=True),
        tracks,
        frame,
        history,
    )
    ratio = old_ms / new_ms if new_ms else float("inf")
    print(
        f"\nimage history warp 300 tracks x 30 points (median of "
        f"{BENCHMARK_RUNS}): old={old_ms:.2f} ms, new={new_ms:.2f} ms, "
        f"ratio={ratio:.2f}x"
    )
    assert new_ms <= old_ms
