#!/usr/bin/env python3
"""Compare the real P2 handoff against a saved baseline, without detection/network IO."""

import argparse
import cProfile
import gc
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import pickle
import pstats
from queue import Queue
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "test")]
from native_trajectory_pickle_fixture import make  # noqa: E402
import services.PipelineEgress as candidate  # noqa: E402


def load(path):
    spec = importlib.util.spec_from_file_location("transport_baseline", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class AckSink:
    def __init__(self, acknowledgements):
        self.acknowledgements = acknowledgements
        self.packets = []

    def put(self, packet, timeout):
        self.packets.append(packet[3])
        self.acknowledgements.put(packet[1])


def run(module, frame, disable_gc=False):
    acks = Queue()
    sink = AckSink(acks)
    packets = sink.packets
    client = module.EgressClient("tracker", sink, acks)
    client.offsets = {
        str(k): len(t.trajectory_points) - 1 for k, t in frame.active_tracks.items()
    }
    collected = gc.isenabled()
    if disable_gc:
        gc.disable()
    start = time.perf_counter()
    cpu_start = time.thread_time()
    rendered = client.frame(frame)
    handoff_ms = (time.perf_counter() - start) * 1000
    cpu_ms = (time.thread_time() - cpu_start) * 1000
    start = time.perf_counter()
    encoded = pickle.dumps(rendered, protocol=pickle.HIGHEST_PROTOCOL)
    render_pickle_ms = (time.perf_counter() - start) * 1000
    if collected:
        gc.enable()
    return (
        {
            "thread_cpu_ms": cpu_ms,
            "handoff_ms": handoff_ms,
            "render_pickle_ms": render_pickle_ms,
            "render_bytes": len(encoded),
            "archive_wire_bytes": sum(map(len, packets)),
        },
        rendered,
        packets,
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--candidate", type=Path)
    p.add_argument("--disable-gc", action="store_true")
    p.add_argument("--tracks", type=int, default=250)
    p.add_argument("--points", type=int, nargs="+", default=[500, 5000])
    p.add_argument("--iterations", type=int, default=20)
    args = p.parse_args()
    old = load(args.baseline)
    current = load(args.candidate) if args.candidate else candidate
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    for count in args.points:
        frame = make(False, args.tracks, count)
        frame.association_trajectories = [
            {
                "association_id": k,
                "trajectory_display_px": t.trajectory_points,
                "trajectory_enu_m": t.trajectory_enu_m,
                "point_quality_lineage": t.point_quality_lineage,
            }
            for k, t in frame.active_tracks.items()
        ]
        for module in (old, current):
            for _ in range(20):
                run(module, frame, args.disable_gc)
        samples = {"baseline": [], "candidate": []}
        for i in range(args.iterations):
            for name, module in (
                [("baseline", old), ("candidate", current)]
                if i % 2 == 0
                else [("candidate", current), ("baseline", old)]
            ):
                result, _, _ = run(module, frame, args.disable_gc)
                samples[name].append(result)
        stats = {
            name: {key: statistics.median(r[key] for r in values) for key in values[0]}
            for name, values in samples.items()
        }
        p95 = {
            name: {
                key: sorted(r[key] for r in values)[
                    max(0, int(len(values) * 0.95 + 0.999) - 1)
                ]
                for key in values[0]
            }
            for name, values in samples.items()
        }
        profile = cProfile.Profile()
        profile.runcall(run, old, frame, args.disable_gc)
        stream = io.StringIO()
        pstats.Stats(profile, stream=stream).sort_stats("cumulative").print_stats(24)
        (args.output / f"baseline-profile-{count}.txt").write_text(stream.getvalue())
        profile = cProfile.Profile()
        profile.runcall(run, current, frame, args.disable_gc)
        stream = io.StringIO()
        pstats.Stats(profile, stream=stream).sort_stats("cumulative").print_stats(24)
        (args.output / f"candidate-profile-{count}.txt").write_text(stream.getvalue())
        row = {
            "tracks": args.tracks,
            "history_points": count,
            "iterations_per_version": args.iterations,
            "medians": stats,
            "p95": p95,
            "handoff_reduction": 1
            - stats["candidate"]["handoff_ms"] / stats["baseline"]["handoff_ms"],
            "baseline_sha256": hashlib.sha256(args.baseline.read_bytes()).hexdigest(),
            "candidate_sha256": hashlib.sha256(
                Path(current.__file__).read_bytes()
            ).hexdigest(),
            "gc_policy": "disabled" if args.disable_gc else "normal",
            "scope": "synthetic authoritative state with real EgressClient.frame; immediate ACK sink; excludes producer FS/network, detector and tracker algorithms",
        }
        print(json.dumps(row), flush=True)
        results.append(row)
        del frame
        gc.collect()
    (args.output / "transport-benchmark.json").write_text(
        json.dumps(results, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
