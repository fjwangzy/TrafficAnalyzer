#!/usr/bin/env python3
"""Measure egress wire volume from a pipeline's ``pending.packets`` journal.

The journal is the durable copy every egress packet is written to before the
receiver accepts it, so it is an exact record of what crosses the tracker→egress
boundary.  Use it to compare the full facts snapshot with the incremental
``frame_delta`` payload on real runs.

Examples:

    .venv-mps/bin/python scripts/measure_egress_payload.py \\
        /tmp/traffic-pipeline-spool/pipe-<full>/egress/pending.packets \\
        /tmp/traffic-pipeline-spool/pipe-<delta>/egress/pending.packets
"""

from __future__ import annotations

import argparse
import pickle
import statistics
import struct
from collections import defaultdict
from pathlib import Path


def packets(path: Path, limit: int):
    with path.open("rb") as stream:
        count = 0
        while count < limit:
            header = stream.read(8)
            if len(header) < 8:
                return
            (length,) = struct.unpack("!Q", header)
            blob = stream.read(length)
            if len(blob) < length:
                return
            try:
                _, _, _, payload = pickle.loads(blob)
                kind, data = pickle.loads(payload)
            except Exception as error:  # truncated or foreign journal
                print(f"stop: undecodable packet at #{count}: {type(error).__name__}")
                return
            yield kind, len(payload), data
            count += 1


def summarise(path: Path, limit: int) -> dict:
    sizes: dict[str, list[int]] = defaultdict(list)
    tracks = 0
    frames = 0
    for kind, size, data in packets(path, limit):
        sizes[kind].append(size)
        if kind == "frame_delta":
            tracks = len(data.get("present") or [])
            frames += 1
        elif kind == "frame":
            tracks = len(getattr(data, "active_tracks", {}) or {})
            frames += 1
    rows = {}
    for kind, values in sizes.items():
        values.sort()
        rows[kind] = {
            "packets": len(values),
            "median": values[len(values) // 2],
            "p90": values[int(len(values) * 0.9)],
            "total_mb": round(sum(values) / 1e6, 2),
        }
    total_bytes = sum(row["total_mb"] for row in rows.values()) * 1e6
    return {
        "path": str(path),
        "tracks": tracks,
        "frames": frames,
        "kinds": rows,
        "bytes_per_frame": round(total_bytes / frames) if frames else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("journals", nargs="+", type=Path)
    parser.add_argument("--limit", type=int, default=20000, help="max packets per journal")
    args = parser.parse_args()

    results = [summarise(path, args.limit) for path in args.journals]
    for result in results:
        print(f"\n== {result['path']}")
        print(f"   frames={result['frames']} last_tracks={result['tracks']} "
              f"bytes/frame={result['bytes_per_frame']}")
        print(f"   {'kind':14}{'packets':>9}{'median':>9}{'p90':>9}{'total MB':>10}")
        for kind, row in sorted(result["kinds"].items(), key=lambda kv: -kv[1]["total_mb"]):
            print(f"   {kind:14}{row['packets']:>9}{row['median']:>9}{row['p90']:>9}{row['total_mb']:>10.1f}")

    if len(results) == 2:
        before, after = results
        before_bytes = before["bytes_per_frame"] or 0
        after_bytes = after["bytes_per_frame"] or 0
        if before_bytes and after_bytes:
            print(
                f"\nbytes/frame {before_bytes} -> {after_bytes}: "
                f"{100 * (1 - after_bytes / before_bytes):.0f}% smaller "
                f"(tracks {before['tracks']} -> {after['tracks']})"
            )
        for kind in ("frame", "frame_delta"):
            if kind in before["kinds"] and "frame_delta" in after["kinds"]:
                b = before["kinds"][kind]["median"]
                a = after["kinds"]["frame_delta"]["median"]
                print(f"facts packet median {b} -> {a}: {100 * (1 - a / b):.0f}% smaller")
                break
        if statistics.mean([after["tracks"], before["tracks"]]) and abs(
            after["tracks"] - before["tracks"]
        ) > 0.2 * max(before["tracks"], 1):
            print("note: track counts differ by more than 20%; compare with matched load")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
