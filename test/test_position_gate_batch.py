"""Compare production gate masks and real tracker sequences with batching on/off."""

from types import SimpleNamespace
import numpy as np
import pytest
from byte_tracker.utils import matching
from byte_tracker.utils.kalman_filter import KalmanFilter, chi2inv95


class Detection:
    def __init__(self, value):
        self.value = value

    def to_xyah(self):
        return self.value


def fixture(seed=72, n=297, m=197):
    rng = np.random.default_rng(seed)
    tracks = []
    for i in range(n):
        a = rng.normal(size=(8, 8))
        mean = np.r_[rng.uniform(-30, 30, 2), 1.0, 20.0, np.zeros(4)]
        tracks.append(SimpleNamespace(mean=mean, covariance=a @ a.T + np.eye(8)))
    measurements = rng.uniform(-30, 30, (m, 4))
    measurements[:, 2] = 1.0
    measurements[:, 3] = 20.0
    return tracks, [Detection(v) for v in measurements], rng.random((n, m))


@pytest.mark.parametrize("seed", range(12))
def test_batch_mask_and_cost_are_exactly_the_same_as_row_path(seed):
    kf = KalmanFilter()
    tracks, dets, cost = fixture(seed)
    kf.batch_position_gate_enabled = False
    expected = matching.gate_cost_matrix(kf, cost.copy(), tracks, dets, True)
    kf.batch_position_gate_enabled = True
    actual = matching.gate_cost_matrix(kf, cost.copy(), tracks, dets, True)
    np.testing.assert_array_equal(actual, expected)


def test_batch_is_used_and_reduces_row_calls(monkeypatch):
    kf = KalmanFilter()
    kf.batch_position_gate_enabled = True
    tracks, dets, cost = fixture()
    calls = []
    original = kf.gating_distance

    def count(*a, **kw):
        calls.append(1)
        return original(*a, **kw)

    monkeypatch.setattr(kf, "gating_distance", count)
    matching.gate_cost_matrix(kf, cost, tracks, dets, True)
    assert len(calls) < 10


def test_threshold_neighbors_remain_identical():
    kf = KalmanFilter()
    tracks, _, _ = fixture(n=8, m=1)
    mean, cov = kf.project(tracks[0].mean, tracks[0].covariance)
    lower = np.linalg.cholesky(cov[:2, :2])
    edge = mean[:2] + lower[:, 0] * np.sqrt(chi2inv95[2])
    threshold_x = edge[0]
    dets = [
        Detection(np.array([x, edge[1], 1.0, 20.0]))
        for x in (
            np.nextafter(threshold_x, -np.inf),
            threshold_x,
            np.nextafter(threshold_x, np.inf),
        )
    ]
    cost = np.zeros((8, 3))
    kf.batch_position_gate_enabled = False
    expected = matching.gate_cost_matrix(kf, cost.copy(), tracks, dets, True)
    kf.batch_position_gate_enabled = True
    np.testing.assert_array_equal(
        matching.gate_cost_matrix(kf, cost.copy(), tracks, dets, True), expected
    )


@pytest.mark.parametrize("shape", [(0, 3), (3, 0), (1, 3), (3, 1)])
def test_empty_and_small_inputs(shape):
    kf = KalmanFilter()
    tracks, dets, cost = fixture(n=shape[0], m=shape[1])
    kf.batch_position_gate_enabled = False
    expected = matching.gate_cost_matrix(kf, cost.copy(), tracks, dets, True)
    kf.batch_position_gate_enabled = True
    np.testing.assert_array_equal(
        matching.gate_cost_matrix(kf, cost.copy(), tracks, dets, True), expected
    )


def test_non_positive_covariance_keeps_original_failure():
    kf = KalmanFilter()
    tracks, dets, cost = fixture(n=8, m=10)
    tracks[4].covariance[0, 0] = -1e8
    for flag in (False, True):
        kf.batch_position_gate_enabled = flag
        with pytest.raises(np.linalg.LinAlgError):
            matching.gate_cost_matrix(kf, cost.copy(), tracks, dets, True)


def test_real_ground_tracker_sequences_are_identical_with_batch_on_off():
    import json
    from nodes.GroundTrajectoryTrackerNode import GroundTrajectoryTrackerNode
    from elements.FrameElement import FrameElement

    def replay(enabled):
        tracker = GroundTrajectoryTrackerNode(
            {
                "tracking_node": {
                    "first_track_thresh": 0.5,
                    "second_track_thresh": 0.1,
                    "match_thresh": 0.8,
                    "track_buffer": 30,
                    "max_lost_sec": 2.0,
                    "batch_position_gate": enabled,
                }
            }
        )
        outputs = []
        for i in range(120):
            visible = [j for j in range(50) if not (j % 7 == 0 and 25 <= i < 32)]
            boxes = [
                [
                    10 + (j % 10) * 24 + i * 0.2,
                    10 + (j // 10) * 24,
                    22 + (j % 10) * 24 + i * 0.2,
                    22 + (j // 10) * 24,
                ]
                for j in visible
            ]
            frame = FrameElement(
                "fixed-replay",
                np.zeros((240, 320, 3), np.uint8),
                i * 0.1,
                i + 1,
                {},
                detected_xyxy=boxes,
                detected_cls=["car"] * len(boxes),
                detected_cls_ids=[3] * len(boxes),
                detected_conf=[0.9] * len(boxes),
            )
            frame.camera_motion_warp = np.eye(3)
            frame = tracker.process(frame)

            def encode(v):
                if isinstance(v, np.ndarray):
                    return v.tolist()
                if isinstance(v, np.generic):
                    return v.item()
                raise TypeError(type(v).__name__)

            outputs.append(
                json.dumps(
                    {
                        "ids": frame.id_list,
                        "boxes": frame.tracked_xyxy,
                        "classes": frame.tracked_cls,
                        "trajectories": frame.association_trajectories,
                        "diagnostics": frame.tracking_diagnostics,
                    },
                    default=encode,
                    sort_keys=True,
                )
            )
        return outputs

    assert replay(False) == replay(True)


@pytest.mark.parametrize("dtype", [np.float32, np.float64])
@pytest.mark.parametrize("only_position", [False, True])
def test_cost_dtypes_and_four_dimensional_original_path(dtype, only_position):
    kf = KalmanFilter()
    tracks, dets, cost = fixture(n=9, m=20)
    cost = cost.astype(dtype)
    kf.batch_position_gate_enabled = False
    expected = matching.gate_cost_matrix(kf, cost.copy(), tracks, dets, only_position)
    kf.batch_position_gate_enabled = True
    np.testing.assert_array_equal(
        matching.gate_cost_matrix(kf, cost.copy(), tracks, dets, only_position),
        expected,
    )


def test_custom_filter_keeps_its_original_distance_behavior():
    class Custom(KalmanFilter):
        def gating_distance(
            self, mean, covariance, measurements, only_position=False, metric="maha"
        ):
            return np.zeros(len(measurements))

    kf = Custom()
    kf.batch_position_gate_enabled = True
    tracks, dets, cost = fixture(n=12, m=20)
    np.testing.assert_array_equal(
        matching.gate_cost_matrix(kf, cost.copy(), tracks, dets, True), cost
    )
