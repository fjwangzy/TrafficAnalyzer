#!/usr/bin/env python3
"""Run published .1/.2 and candidate receivers on identical synthetic packets.

Measures append + frame-tail restoration, including SQLite and JSON. This is a
component test, not NPU or end-to-end FPS acceptance. Old runtimes stay untouched.
"""

import argparse
from contextlib import contextmanager
import hashlib
import pickle
import importlib.util
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from elements.RenderSnapshot import RenderTrackSnapshot  # noqa: E402
from services import PipelineEgress as candidate  # noqa: E402
from services import TrajectorySpoolIndex as candidate_index  # noqa: E402


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def index_module(module):
    key = "services.TrajectorySpoolIndex"
    old = sys.modules.get(key)
    sys.modules[key] = module
    try:
        yield
    finally:
        if old is None:
            sys.modules.pop(key, None)
        else:
            sys.modules[key] = old


def rows(n, start, size):
    values = {}
    for name in candidate.POINT_FIELDS:
        values[name] = [
            {}
            if name == "point_quality_lineage"
            else i
            if name == "trajectory_frame_nums"
            else i * 0.04
            if name == "trajectory_timestamps_sec"
            else None
            if name in {"trajectory_enu_m", "trajectory_gcj02"} and i % 3 == 0
            else [float(i), float(i + 1)]
            for i in range(start, start + size)
        ]
    return [{"track_id": str(k), "start": start, "arrays": values} for k in range(n)]


def measure(
    label, module, index, n, points, chunk, iterations, directory, real_journal=False
):
    with index_module(index):
        store = module.DeltaTracks() if label == ".1" else module.DeltaTracks(directory)
        directory.mkdir(parents=True, exist_ok=True)
        journal = module.PacketJournal(directory) if real_journal else None
        journal_ms, close_ms = [], []
        sequence = 0

        def persist(kind, value):
            nonlocal sequence
            if journal is None:
                return
            sequence += 1
            payload = pickle.dumps((kind, value), protocol=pickle.HIGHEST_PROTOCOL)
            before = time.perf_counter()
            decoded = journal.accept(
                ("tracker", sequence, hashlib.sha256(payload).hexdigest(), payload)
            )
            journal_ms.append((time.perf_counter() - before) * 1000)
            assert decoded[0] == kind

        append_ms = []
        append_step_ms = []
        try:
            for start in range(0, points, chunk):
                packet = rows(n, start, min(chunk, points - start))
                batch_tracks = max(1, 1024 // min(chunk, points - start))
                elapsed = 0.0
                for offset in range(0, len(packet), batch_tracks):
                    batch = packet[offset : offset + batch_tracks]
                    persist("points_batch", batch)
                    before = time.perf_counter()
                    if hasattr(store, "append_batch"):
                        store.append_batch(batch)
                    else:
                        for row in batch:
                            store.append(row)
                    elapsed += (time.perf_counter() - before) * 1000
                if start >= max(0, points - 32 * chunk):
                    append_ms.append(elapsed)
                    append_step_ms.append(elapsed / min(chunk, points - start))
            timings = []
            sql = []
            for _ in range(iterations):
                frame = SimpleNamespace(
                    active_tracks={
                        k: RenderTrackSnapshot({"trajectory_point_count": points})
                        for k in range(n)
                    },
                    mature_tracks=None,
                )
                before = time.perf_counter()
                module.restore_fact_tails(frame, store)
                timings.append((time.perf_counter() - before) * 1000)
            if hasattr(store, "disk"):
                store.disk.set_trace_callback(sql.append)
                probe = SimpleNamespace(
                    active_tracks={
                        k: RenderTrackSnapshot({"trajectory_point_count": points})
                        for k in range(n)
                    },
                    mature_tracks=None,
                )
                module.restore_fact_tails(probe, store)
                store.disk.set_trace_callback(None)
            digest = hashlib.sha256(
                json.dumps(
                    [view._values for view in frame.active_tracks.values()],
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            # Full-resolution disk iteration must still include the evicted prefix.
            expected = rows(1, 0, points)[0]["arrays"]
            assert all(
                list(store.rows["0"][field]) == expected[field]
                for field in candidate.POINT_FIELDS
            )
            for key in range(n):
                value = {
                    "track_id": str(key),
                    "point_count": points,
                    "metadata": {"track_id": str(key), "timestamp_first": 0.0},
                }
                persist("close", value)
                before = time.perf_counter()
                store.finish(value)
                close_ms.append((time.perf_counter() - before) * 1000)
                assert store.closed[str(key)]["trajectory_frame_nums"] == list(
                    range(points)
                )
                # Emulate publication draining completed tracks; do not accumulate them.
                store.closed.pop(str(key))

            def stats(values):
                values = sorted(values)
                return {
                    "count": len(values),
                    "total_ms": sum(values),
                    **{
                        f"p{q}_ms": values[int((len(values) - 1) * q / 100)]
                        if values
                        else None
                        for q in (50, 95, 99)
                    },
                }

            return {
                "journal": stats(journal_ms),
                "close": stats(close_ms),
                "append": stats(append_ms),
                "restore": stats(timings),
                "version": label,
                "append_round_median_ms": statistics.median(append_ms),
                "append_per_source_step_median_ms": statistics.median(append_step_ms),
                "restore_median_ms": statistics.median(timings),
                "restore_max_ms": max(timings),
                "restore_sql_selects_per_frame": sum(
                    s.startswith("SELECT") for s in sql
                ),
                "tail_sha256": digest,
                "full_resolution_sample_equal": True,
            }
        finally:
            if journal is not None:
                journal.close()
            if hasattr(store, "disk"):
                store.disk.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-root", type=Path, default=ROOT / "dist")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument(
        "--journal",
        action="store_true",
        help="real PacketJournal flush+fsync before each batch/close (still a component benchmark)",
    )
    parser.add_argument("--quick", action="store_true", help="omit the 5000-point case")
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 1 or args.iterations < 1:
        parser.error("repeats and iterations must be positive")
    releases = []
    for version in ("1", "2", "3"):
        source = (
            args.baseline_root
            / f"traffic-analyzer-native-2026.11.04.{version}"
            / "app/services"
        )
        releases.append(
            (
                "." + version,
                load(source / "PipelineEgress.py", "receiver_v" + version),
                load(source / "TrajectorySpoolIndex.py", "index_v" + version)
                if version != "1"
                else None,
            )
        )
    releases.append(("candidate", candidate, candidate_index))
    result = {
        "scope": "actual receiver components; synthetic packets; no field FPS claim",
        "source_sha256": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [
                ROOT / "services/PipelineEgress.py",
                ROOT / "services/TrajectorySpoolIndex.py",
            ]
        },
        "cases": [],
    }
    result["journal_enabled"] = args.journal
    result["baseline_sha256"] = {}
    for version in ("1", "2", "3"):
        source = (
            args.baseline_root
            / f"traffic-analyzer-native-2026.11.04.{version}"
            / "app/services"
        )
        result["baseline_sha256"][version] = {
            name: hashlib.sha256((source / name).read_bytes()).hexdigest()
            for name in ("PipelineEgress.py", "TrajectorySpoolIndex.py")
            if (source / name).exists()
        }
    with tempfile.TemporaryDirectory(prefix="traffic-receiver-ab-") as temporary:
        cases = [(280, 160, 1), (486, 160, 1)]
        if not args.quick:
            cases.append((486, 5000, 64))
        for run in range(args.repeats):
            order = releases if run % 2 == 0 else list(reversed(releases))
            for n, points, chunk in cases:
                case = {
                    "repeat": run,
                    "tracks": n,
                    "points_per_track": points,
                    "points_per_track_per_round": chunk,
                    "wire_batch_max_points": 1024,
                    "versions": [],
                }
                for label, module, index in order:
                    row = measure(
                        label,
                        module,
                        index,
                        n,
                        points,
                        chunk,
                        args.iterations,
                        Path(temporary) / f"{run}-{n}-{points}-{label}",
                        args.journal,
                    )
                    case["versions"].append(row)
                    print(
                        json.dumps({"tracks": n, "points": points, **row}), flush=True
                    )
                assert len({row["tail_sha256"] for row in case["versions"]}) == 1
                old = next(row for row in case["versions"] if row["version"] == ".2")
                new = next(
                    row for row in case["versions"] if row["version"] == "candidate"
                )
                case["combined_reduction"] = 1 - (
                    new["append_per_source_step_median_ms"] + new["restore_median_ms"]
                ) / (old["append_per_source_step_median_ms"] + old["restore_median_ms"])
                case["passed"] = (
                    case["combined_reduction"] >= 0.70
                    and new["restore_sql_selects_per_frame"] == 0
                )
                result["cases"].append(case)
    result["passed"] = all(case["passed"] for case in result["cases"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    if not result["passed"]:
        raise SystemExit(
            "receiver performance acceptance failed; inspect recorded cases"
        )


if __name__ == "__main__":
    main()
