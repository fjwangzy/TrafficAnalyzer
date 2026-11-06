#!/usr/bin/env python3
"""Summarize bounded stage windows; never merge window percentiles or sum nested timers."""

import argparse
import json
from pathlib import Path
import statistics

from accept_pipeline_fps import inspect_diagnosis


def summarize(root):
    manifest = json.loads((root / "manifest.json").read_text())
    windows = []
    for line in (root / "pipeline.log").read_text().splitlines():
        if "PERF_SUMMARY " in line:
            windows.append(json.loads(line.split("PERF_SUMMARY ", 1)[1]))
    stages = {}
    for row in windows:
        slot = stages.setdefault(
            row["stage"], {"calls": 0, "total_ms": 0.0, "windows": []}
        )
        slot["calls"] += row["count"]
        slot["total_ms"] += row["total_ms"]
        slot["windows"].append(row)
    resources = {}
    for line in (root / "resources.jsonl").read_text().splitlines():
        row = json.loads(line)
        resources.setdefault(row["pid"], []).append(row)
    trends = {}
    for pid, rows in resources.items():
        trends[pid] = {
            "samples": len(rows),
            "rss_first": rows[0]["rss"],
            "rss_last": rows[-1]["rss"],
            "rss_max": max(row["rss"] for row in rows),
            "cpu_percent_median": statistics.median(row["cpu_percent"] for row in rows),
            "io_first": rows[0]["io"],
            "io_last": rows[-1]["io"],
        }
    rates = {
        role: [
            {
                "pid": row["pid"],
                "window_sec": row["window_sec"],
                "fps": row["count"] / row["window_sec"],
            }
            for row in windows
            if row["stage"] == stage and row["window_sec"] > 0
        ]
        for role, stage in [
            ("detection", "reader.detection"),
            ("tracker", "tracker.egress_delta"),
            ("show", "show.egress_evidence"),
            ("submission", "egress.commit_frame"),
        ]
    }
    return {
        "scope": manifest["scope"],
        "manifest": manifest,
        "throughput": inspect_diagnosis(root / "pipeline.log"),
        "worker_rate_windows": rates,
        "stages": stages,
        "resources": trends,
        "notes": [
            "P50/P95/P99 are per-window bounded samples, not combined percentiles.",
            "Stage timers can nest; do not sum all totals.",
            "Local egress commit is not a PostgreSQL ingest receipt.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    report = summarize(args.run)
    (args.run / "audit.json").write_text(json.dumps(report, indent=2))
    print(
        json.dumps(
            {
                "throughput": report["throughput"],
                "stages": len(report["stages"]),
                "processes": len(report["resources"]),
            }
        )
    )


if __name__ == "__main__":
    main()
