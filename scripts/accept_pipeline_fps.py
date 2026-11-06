#!/usr/bin/env python3
"""Read exported diagnostics and check completed-frame throughput; never changes offsets or services."""
import argparse
import ast
from datetime import datetime
import json
from pathlib import Path
import re


def inspect_diagnosis(path, minimum_fps=3., duration=300., capacity=32):
    content = Path(path).read_text()
    try:
        diagnosis = json.loads(content)
    except json.JSONDecodeError:
        # Full per-task logs avoid the diagnostic export's 256 KiB tail limit.
        logs = {}
        for line in content.splitlines():
            identity = re.search(r"pipeline=(pipe-[A-Za-z0-9_-]+)", line)
            if identity and "EGRESS_STATUS" in line:
                logs.setdefault(identity[1], []).append(line)
        diagnosis = {"logs": {key: "\n".join(lines) for key, lines in logs.items()}}
    candidates = []
    for name, content in diagnosis.get("logs", {}).items():
        if not name.startswith("pipe-") or not isinstance(content, str):
            continue
        samples = []
        for line in content.splitlines():
            if "EGRESS_STATUS" not in line:
                continue
            times = re.findall(r"\d{4}-\d\d-\d\dT[\d:.]+Z", line)
            frames = re.search(r"frames=(\{.*?\})", line)
            depth = re.search(r"queue_depth=(-?\d+)", line)
            if times and frames and depth:
                completed = ast.literal_eval(frames[1])
                committed = re.search(r"committed=(\d+)", line)
                watermark = int(committed[1]) if committed else None
                samples.append((datetime.fromisoformat(times[-1].replace("Z", "+00:00")).timestamp(), watermark if watermark is not None else min(completed["tracker"], completed["show"]), int(depth[1]), watermark, completed))
        if samples:
            candidates.append((samples[-1][0], name, samples))
    if not candidates:
        return {"file": str(path), "status": "not_evaluated", "reason": "no completed-frame status samples"}
    _, name, samples = max(candidates)
    elapsed = samples[-1][0]-samples[0][0]
    if any(row[3] is None for row in samples):
        return {"file": str(path), "pipeline": name, "status": "not_evaluated",
                "reason": "missing committed watermark; tracker/show arrivals do not prove business submission"}
    if any(row[3] > min(row[4]["tracker"], row[4]["show"]) for row in samples):
        return {"file": str(path), "pipeline": name, "status": "not_evaluated", "reason": "commit exceeds arrival watermarks"}
    valid = all(b[0] > a[0] and b[1] >= a[1] for a, b in zip(samples, samples[1:]))
    if not valid or elapsed < duration:
        return {"file": str(path), "pipeline": name, "status": "not_evaluated", "duration_sec": elapsed, "reason": "need monotonic completed watermarks covering the full requested duration"}
    rate = (samples[-1][1]-samples[0][1])/elapsed
    midpoint = len(samples)//2
    early = (samples[midpoint][1]-samples[0][1])/(samples[midpoint][0]-samples[0][0])
    late = (samples[-1][1]-samples[midpoint][1])/(samples[-1][0]-samples[midpoint][0])
    known_depths = [row[2] for row in samples if row[2] >= 0]
    fraction_full = sum(depth >= capacity for depth in known_depths)/len(known_depths) if known_depths else None
    passed = rate >= minimum_fps and late >= minimum_fps and late >= .9*early and fraction_full is not None and fraction_full < .1
    return {"file": str(path), "pipeline": name, "status": "passed" if passed else "failed", "duration_sec": elapsed, "completed_fps": rate, "watermark_basis": "egress local business submission; not database receipt", "arrival_fps": {role: (samples[-1][4][role]-samples[0][4][role])/elapsed for role in ("tracker", "show")}, "early_half_fps": early, "late_half_fps": late, "full_queue_sample_fraction": fraction_full}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("diagnosis", nargs="+", type=Path)
    parser.add_argument("--minimum-fps", type=float, default=3.)
    parser.add_argument("--minimum-duration", type=float, default=300.)
    parser.add_argument("--minimum-runs", type=int, default=3)
    parser.add_argument("--queue-capacity", type=int, default=32)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results = [inspect_diagnosis(path, args.minimum_fps, args.minimum_duration, args.queue_capacity) for path in args.diagnosis]
    # Three exports of the same task do not constitute three independent runs.
    unique = {row.get("pipeline") for row in results if row["status"] == "passed"}
    passed = len(unique) >= args.minimum_runs and all(row["status"] == "passed" for row in results)
    report = {"status": "passed" if passed else "not_accepted", "minimum_fps": args.minimum_fps, "minimum_duration_sec": args.minimum_duration, "runs": results, "scope": "completed-frame throughput only; compare source/model/stride externally; not memory, precision, or end-to-end latency acceptance"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
