#!/usr/bin/env python3
"""Compare two ``profile_pipeline_fps.py`` runs and gate on P2 serial budget.

A single-machine comparison is only meaningful when both runs saw a comparable
load, so the script first checks median tracks/detections and refuses a verdict
when they differ beyond ``--load-tolerance`` unless ``--force`` is given.

Examples:

    .venv-mps/bin/python scripts/compare_fps_profile.py \
        output/fps-profile-20261105/long300/stages.json \
        output/fps-profile-20261105/<candidate>/stages.json \
        --target-ms 333 --json output/fps-profile-20261105/ab.json
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

# Every stage that runs inside the tracker process, i.e. on the serial P2 budget.
# Egress handoff is included because P2 pays for it even when the write happens in P4.
P2_STAGES = (
    "tracker.image_motion",
    "tracker.association",
    "tracker.homography",
    "tracker.motion_compensation",
    "tracker.geo_reference",
    "tracker.world_projection",
    "tracker.info",
    "tracker.speed",
    "tracker.direction",
    "tracker.lane_detection",
    "tracker.trajectory",
    "tracker.lane_change",
    "tracker.map_matching",
    "tracker.enforcement",
    "tracker.lane_analysis",
    "tracker.auto_lane",
    "tracker.conflict",
    "tracker.statistics",
    "tracker.snapshot_scheduler",
    "tracker.egress_delta",
    "tracker.freeze_views",
    "tracker.render_snapshot",
    "tracker.geojson",
    "tracker.kafka_archive",
)


def load(path: Path) -> dict:
    data = json.loads(Path(path).read_text())
    return {
        "payload": data,
        "stages": data["stages"],
        "frames": [row for row in data.get("load", []) if row.get("stage_ms")],
    }


def med(rows, key, default=0.0):
    values = [row.get(key) or default for row in rows]
    return statistics.median(values) if values else default


def frame_budgets(run):
    # Only mutually exclusive P2 stages; inner egress.* timers must not be added.
    return [sum(row["stage_ms"].get(name, 0.0) for name in P2_STAGES)
            for row in run["frames"]]


def p2_sum(run):
    values = frame_budgets(run)
    if not values or not all(value > 0 for value in values):
        raise ValueError("per-frame P2 timings required; aggregate stage medians cannot establish a frame budget")
    return statistics.median(values)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--target-ms", type=float, default=None, help="required P2 serial budget for the candidate")
    parser.add_argument("--load-tolerance", type=float, default=0.15)
    parser.add_argument(
        "--max-regression-pct",
        type=float,
        default=5.0,
        help="fail when the candidate P2 budget grows more than this percentage",
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    base, cand = load(args.baseline), load(args.candidate)
    base_tracks = med(base["frames"], "active_tracks")
    cand_tracks = med(cand["frames"], "active_tracks")
    base_dets = med(base["frames"], "detections")
    cand_dets = med(cand["frames"], "detections")
    drift_tracks = abs(cand_tracks - base_tracks) / max(base_tracks, 1)
    drift_dets = abs(cand_dets - base_dets) / max(base_dets, 1)
    comparable = drift_tracks <= args.load_tolerance and drift_dets <= args.load_tolerance
    base_trace = base['payload'].get('detection_trace_sha256')
    cand_trace = cand['payload'].get('detection_trace_sha256')
    if base_trace or cand_trace:
        comparable = comparable and bool(base_trace) and base_trace == cand_trace

    base_sum, cand_sum = p2_sum(base), p2_sum(cand)
    result = {
        "baseline": str(args.baseline),
        "candidate": str(args.candidate),
        "baseline_frames": len(base["frames"]),
        "candidate_frames": len(cand["frames"]),
        "baseline_tracks": round(base_tracks, 1),
        "candidate_tracks": round(cand_tracks, 1),
        "baseline_detections": round(base_dets, 1),
        "candidate_detections": round(cand_dets, 1),
        "load_comparable": comparable,
        "baseline_p2_ms": round(base_sum, 1),
        "candidate_p2_ms": round(cand_sum, 1),
        "measurement_scope": "single-process P2 per-frame budget; excludes real journal, Kafka and four-process backpressure",
        "baseline_fps_ceiling": round(1000 / base_sum, 2) if base_sum else None,
        "candidate_fps_ceiling": round(1000 / cand_sum, 2) if cand_sum else None,
        "stages": {},
    }
    for name in P2_STAGES:
        before, after = base["stages"].get(name), cand["stages"].get(name)
        if before is None and after is None:
            continue
        result["stages"][name] = {
            "baseline_ms": before["wall_median_ms"] if before else None,
            "candidate_ms": after["wall_median_ms"] if after else None,
            "delta_ms": round(
                (after["wall_median_ms"] if after else 0.0)
                - (before["wall_median_ms"] if before else 0.0),
                2,
            ),
        }

    regression_pct = (cand_sum - base_sum) / max(base_sum, 1e-9) * 100.0
    result["p2_delta_pct"] = round(regression_pct, 1)
    verdict = "not_evaluated"
    reasons = []
    if not comparable and not args.force:
        reasons.append(
            f"load drift tracks={drift_tracks:.0%} detections={drift_dets:.0%} "
            f"exceeds {args.load_tolerance:.0%}; rerun with matched load or pass --force"
        )
    elif regression_pct > args.max_regression_pct:
        verdict = "failed"
        reasons.append(
            f"P2 budget regressed {regression_pct:+.1f}% (limit {args.max_regression_pct:.0f}%)"
        )
    elif args.target_ms is None:
        verdict = "measured"
    elif cand_sum <= args.target_ms:
        verdict = "passed"
    else:
        verdict = "failed"
        reasons.append(
            f"P2 {cand_sum:.0f}ms exceeds target {args.target_ms:.0f}ms "
            f"(need to remove {cand_sum - args.target_ms:.0f}ms)"
        )
    result["verdict"] = verdict
    result["reasons"] = reasons

    print(f"P2 serial budget: {base_sum:.1f}ms -> {cand_sum:.1f}ms "
          f"({cand_sum - base_sum:+.1f}ms)")
    print(f"implied ceiling : {1000 / base_sum:.2f} -> {1000 / cand_sum:.2f} FPS" if base_sum and cand_sum else "")
    print("note: single-process tracker budget; includes measured handoff only, excludes real P4 journal/Kafka and backpressure")
    print(f"load            : tracks {base_tracks:.0f}->{cand_tracks:.0f} "
          f"dets {base_dets:.0f}->{cand_dets:.0f} "
          f"({'comparable' if comparable else 'NOT comparable'})")
    print()
    print(f"{'stage':32}{'base ms':>9}{'cand ms':>9}{'delta':>9}")
    for name, row in sorted(
        result["stages"].items(), key=lambda item: item[1]["delta_ms"]
    ):
        before = "—" if row["baseline_ms"] is None else f"{row['baseline_ms']:.1f}"
        after = "—" if row["candidate_ms"] is None else f"{row['candidate_ms']:.1f}"
        print(f"{name:32}{before:>9}{after:>9}{row['delta_ms']:>+9.1f}")
    print()
    print(f"verdict: {verdict}")
    for reason in reasons:
        print(f"  - {reason}")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if verdict in {"passed", "measured"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
