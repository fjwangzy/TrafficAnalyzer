#!/usr/bin/env python3
"""Run the real entrypoint in an isolated output directory; never initialize a DB.

This runner measures local worker health/resources. Kafka/DB acceptance requires
an explicitly isolated broker plus the transactional consumer integration suite.
"""

import argparse
import hashlib
import json
import os
import platform
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid
import socket

try:
    import psutil
except ImportError:
    psutil = None


def fingerprint(path):
    path = Path(path).resolve()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {
        "path": str(path),
        "size": path.stat().st_size,
        "sha256": digest.hexdigest(),
    }


def sample_processes(parent_pid, observed):
    if psutil is None:
        # Standard Unix tooling keeps the diagnostic runner out of the native
        # runtime dependency baseline. ps CPU is a lifetime average, labelled below.
        output = subprocess.check_output(
            ["ps", "-axo", "pid=,ppid=,%cpu=,rss="], text=True
        )
        rows = [line.split() for line in output.splitlines() if line.strip()]
        members = {parent_pid}
        while True:
            expanded = members | {int(row[0]) for row in rows if int(row[1]) in members}
            if expanded == members:
                break
            members = expanded
        return [
            {
                "pid": int(row[0]),
                "rss": int(row[3]) * 1024,
                "cpu_percent": float(row[2]),
                "io": None,
                "cpu_basis": "ps lifetime average",
            }
            for row in rows
            if int(row[0]) in members
        ]
    try:
        parent = psutil.Process(parent_pid)
        workers = [parent] + parent.children(recursive=True)
    except psutil.NoSuchProcess:
        return []
    samples = []
    for worker in workers:
        try:
            probe = observed.setdefault(worker.pid, worker)
            io = (
                probe.io_counters()._asdict() if hasattr(probe, "io_counters") else None
            )
            samples.append(
                {
                    "pid": probe.pid,
                    "rss": probe.memory_info().rss,
                    "cpu_percent": probe.cpu_percent(),
                    "io": io,
                    "cpu_basis": "psutil interval; first sample zero",
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return samples


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--app-root", type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument("--video", type=Path, required=True)
    p.add_argument("--telemetry", type=Path, required=True)
    p.add_argument("--weight", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--duration", type=float, default=390)
    p.add_argument("--stride", type=int, default=3)
    p.add_argument("--kafka-bootstrap")
    p.add_argument("--isolation-project")
    p.add_argument("--device", default="mps")
    p.add_argument(
        "--render",
        action="store_true",
        help="enable actual ShowNode/MJPEG on a dedicated loopback port",
    )
    args = p.parse_args()
    if args.duration <= 0 or args.stride < 1:
        p.error("duration and stride must be positive")
    if args.kafka_bootstrap and (
        not args.isolation_project
        or args.kafka_bootstrap in {"localhost:9092", "127.0.0.1:9092"}
    ):
        p.error(
            "Kafka audit requires a named isolated project and a dedicated broker port"
        )
    root, out = args.app_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    inputs = {
        name: fingerprint(path)
        for name, path in [
            ("video", args.video),
            ("telemetry", args.telemetry),
            ("weight", args.weight),
        ]
    }
    sources = {
        str(path.relative_to(root)): fingerprint(path)["sha256"]
        for folder in (
            "nodes",
            "elements",
            "services",
            "utils_local",
            "byte_tracker",
            "configs",
        )
        for path in sorted((root / folder).rglob("*"))
        if path.suffix in {".py", ".yaml"} and path.is_file()
    }
    sources["main_optimized.py"] = fingerprint(root / "main_optimized.py")["sha256"]
    with socket.socket() as port_probe:
        port_probe.bind(("127.0.0.1", 0))
        video_port = port_probe.getsockname()[1]
    identity = "pipe-fps-audit-" + uuid.uuid4().hex[:8]
    env = os.environ.copy()
    env.update(
        VIDEO_SRC=str(args.video.resolve()),
        SRT_FILE_PATH=str(args.telemetry.resolve()),
        DETECTION_WEIGHT_PATH=str(args.weight.resolve()),
        FRAME_STRIDE=str(args.stride),
        PIPELINE_EGRESS_ENABLED="true",
        PIPELINE_PERF_AUDIT="1",
        ROAD_FEATURES_ENABLED="false",
        CAMERA_ID="1",
        TOPIC_NAME="uav_statistics_1",
        PIPELINE_ID=identity,
        VIDEO_PORT=str(video_port),
        VIDEO_BIND_HOST="127.0.0.1",
        SURVEY_STORAGE_DIR=str(out / "survey"),
        DATA_ROOT=str(out / "data"),
        KAFKA_SPOOL_DIR=str(out / "kafka-spool"),
        TRAJECTORY_ARCHIVE_SPOOL_DIR=str(out / "archive"),
    )
    if args.kafka_bootstrap:
        env["KAFKA_BOOTSTRAP"] = args.kafka_bootstrap
    command = [
        sys.executable,
        str(root / "main_optimized.py"),
        f"hydra.run.dir={out}",
        "pipeline.egress_enabled=True",
        f"pipeline.send_info_kafka={bool(args.kafka_bootstrap)}",
        "pipeline.save_video=False",
        f"pipeline.show_in_web={args.render}",
        "show_node.imshow=False",
        "video_saver_node.save_conflict_clips=False",
        f"detection_node.device={args.device}",
        "telemetry.enabled=True",
        "telemetry.source=srt",
        "telemetry.file_path=${oc.env:SRT_FILE_PATH}",
        f"geojson_export.output_dir={out}/geojson",
    ]
    manifest = {
        "host": {
            "system": platform.system(),
            "machine": platform.machine(),
            "cpu_count": os.cpu_count(),
            "loadavg": os.getloadavg(),
        },
        "inputs": inputs,
        "sources": sources,
        "command": command,
        "isolation_project": args.isolation_project,
        "scope": "real four-worker local run; database receipts and production FPS not evaluated",
        "duration_requested_sec": args.duration,
        "device": args.device,
        "stride": args.stride,
        "switches": {
            k: env.get(k)
            for k in (
                "PIPELINE_FACTS_DELTA",
                "TRACKER_BATCH_WARP",
                "WORLD_PROJECTION_INCREMENTAL",
                "CONFLICT_GRID_PREFILTER",
            )
        },
        "kafka_enabled": bool(args.kafka_bootstrap),
        "pipeline_id": identity,
        "render_enabled": args.render,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    process = None
    try:
        with (
            (out / "pipeline.log").open("w") as log,
            (out / "resources.jsonl").open("w") as resource,
        ):
            process = subprocess.Popen(
                command,
                cwd=root,
                env=env,
                stdout=log,
                stderr=log,
                start_new_session=True,
            )
            started = time.monotonic()
            observed = {}
            while process.poll() is None and time.monotonic() - started < args.duration:
                try:
                    for row in sample_processes(process.pid, observed):
                        row["elapsed_sec"] = time.monotonic() - started
                        resource.write(json.dumps(row) + "\n")
                except (ProcessLookupError, OSError):
                    if process.poll() is None:
                        raise
                resource.flush()
                time.sleep(1)
            if process.poll() is None:
                # Parent owns graceful worker shutdown and SHM cleanup.
                process.send_signal(signal.SIGTERM)
                try:
                    process.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
            manifest.update(
                returncode=process.returncode, elapsed_sec=time.monotonic() - started
            )
    finally:
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        resolved = out / ".hydra" / "config.yaml"
        if resolved.exists():
            manifest["hydra_config"] = fingerprint(resolved)
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, ensure_ascii=False))
    return 0 if process.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
