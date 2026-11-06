#!/usr/bin/env python3
"""Synthetic 100k-ended-track memory probe of the actual disk-backed lifecycle store.

This is a component benchmark, not a two-hour whole-pipeline acceptance or NPU test.
"""

import argparse
import gc
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import psutil
from services.PipelineEgress import DeltaTracks, POINT_FIELDS


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--tracks", type=int, default=100000)
    args = parser.parse_args()
    root = Path(args.output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    store = DeltaTracks(root)
    process = psutil.Process()
    samples = []
    start = time.monotonic()
    try:
        for i in range(args.tracks):
            key = str(i)
            arrays = {field: [0, 1, 2] for field in POINT_FIELDS}
            for field in (
                "trajectory_bbox_center_px",
                "trajectory_px",
                "trajectory_enu_m",
                "trajectory_gcj02",
            ):
                arrays[field] = [[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]]
            arrays["trajectory_timestamps_sec"] = [i * 3.0, i * 3.0 + 1, i * 3.0 + 2]
            arrays["point_quality_lineage"] = [{}, {}, {}]
            store.append({"track_id": key, "start": 0, "arrays": arrays})
            store.finish(
                {"track_id": key, "point_count": 3, "metadata": {"track_id": key}}
            )
            closed = store.closed.pop(key)
            assert len(closed["trajectory_px"]) == 3
            del closed
            if (i + 1) % 1000 == 0:
                store.disk.commit()
            if (i + 1) % 10000 == 0:
                gc.collect()
                samples.append(
                    {"completed": i + 1, "rss_bytes": process.memory_info().rss}
                )
        assert not store.rows and not store.closed
        assert len(store.completed_ids) == args.tracks
        first = samples[1]["rss_bytes"] if len(samples) > 1 else samples[0]["rss_bytes"]
        last = samples[-1]["rss_bytes"]
        growth = (last - first) / first
        result = {
            "scope": "synthetic lifecycle component; not whole pipeline",
            "completed_tracks": args.tracks,
            "samples": samples,
            "rss_growth_after_warmup": growth,
            "elapsed_sec": time.monotonic() - start,
            "passed": growth <= 0.10,
        }
        (root / "result.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result))
        assert result["passed"]
    finally:
        store.disk.commit()
        store.disk.close()


if __name__ == "__main__":
    main()
