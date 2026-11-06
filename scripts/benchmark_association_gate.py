#!/usr/bin/env python3
"""Benchmark the actual position gate with its original and batch branches."""

import argparse
import json
from pathlib import Path
import statistics
import sys
import time
from types import SimpleNamespace
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from byte_tracker.utils import matching  # noqa: E402
from byte_tracker.utils.kalman_filter import KalmanFilter  # noqa: E402


class Detection:
    def __init__(self, value):
        self.value = value

    def to_xyah(self):
        return self.value


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--iterations", type=int, default=100)
    args = p.parse_args()
    results = []
    for n, m in ((50, 50), (297, 197), (500, 500)):
        rng = np.random.default_rng(72)
        kf = KalmanFilter()
        tracks = []
        for i in range(n):
            a = rng.normal(size=(8, 8))
            mean = np.r_[rng.uniform(-30, 30, 2), 1.0, 20.0, np.zeros(4)]
            tracks.append(SimpleNamespace(mean=mean, covariance=a @ a.T + np.eye(8)))
        measures = rng.uniform(-30, 30, (m, 4))
        measures[:, 2] = 1.0
        measures[:, 3] = 20.0
        detections = [Detection(v) for v in measures]
        cost = rng.random((n, m))

        def run(flag):
            kf.batch_position_gate_enabled = flag
            return matching.gate_cost_matrix(kf, cost.copy(), tracks, detections, True)

        np.testing.assert_array_equal(run(False), run(True))
        for flag in (False, True):
            for _ in range(10):
                run(flag)
        timings = {False: [], True: []}
        for i in range(args.iterations):
            for flag in (False, True) if i % 2 == 0 else (True, False):
                start = time.perf_counter()
                run(flag)
                timings[flag].append((time.perf_counter() - start) * 1000)
        old = statistics.median(timings[False])
        new = statistics.median(timings[True])
        row = {
            "tracks": n,
            "detections": m,
            "iterations": args.iterations,
            "baseline_median_ms": old,
            "candidate_median_ms": new,
            "reduction": 1 - new / old,
            "gating_mask_and_cost_equal": True,
            "scope": "synthetic Kalman states; real gate implementation; not whole association or field FPS",
        }
        print(json.dumps(row), flush=True)
        results.append(row)
    args.output.parent.mkdir(exist_ok=True, parents=True)
    args.output.write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()
