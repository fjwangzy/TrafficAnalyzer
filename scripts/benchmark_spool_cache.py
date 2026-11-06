#!/usr/bin/env python3
"""ABBA SQLite cache probe on private synthetic trajectories; no Kafka/DB access."""

import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.PipelineEgress import DeltaTracks, POINT_FIELDS  # noqa: E402
from benchmark_egress_receiver import rows  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tracks", type=int, default=160)
    parser.add_argument("--frames", type=int, default=220)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.tracks <= 1024 or args.frames < 60:
        parser.error("tracks must be 1..1024 and frames >=60")
    result = {
        "scope": "synthetic append path only; page-cache comparison, not field FPS acceptance",
        "tracks": args.tracks,
        "frames": args.frames,
        "runs": [],
    }
    with tempfile.TemporaryDirectory(prefix="traffic-cache-abba-") as temporary:
        for budget in (2048, 16384, 16384, 2048):
            store = DeltaTracks(
                Path(temporary) / str(len(result["runs"])), cache_kib=budget
            )
            timings = []
            try:
                for step in range(args.frames):
                    packet = rows(args.tracks, step, 1)
                    start = time.perf_counter()
                    store.append_batch(packet)
                    timings.append((time.perf_counter() - start) * 1000)
                digest = hashlib.sha256()
                for key in sorted(store.rows):
                    for field in POINT_FIELDS:
                        digest.update(
                            json.dumps(
                                list(store.rows[key][field]), sort_keys=True
                            ).encode()
                        )
                row = {
                    "cache_kib": budget,
                    "early_ms": statistics.median(timings[10:30]),
                    "late_ms": statistics.median(timings[-30:]),
                    "max_ms": max(timings),
                    "sha256": digest.hexdigest(),
                }
                result["runs"].append(row)
                print(json.dumps(row), flush=True)
            finally:
                store.disk.close()
    result["data_equal"] = len({row["sha256"] for row in result["runs"]}) == 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2))
    if not result["data_equal"]:
        raise SystemExit("archive content mismatch")


if __name__ == "__main__":
    main()
