#!/usr/bin/env python3
"""Run mp4new/mp4new2 sources serially on native macOS MPS.

The detector runs on the host, publishes canonical messages to the root Compose
Kafka, and registers its lifecycle with Platform. Complete track and conflict
messages are captured directly from Kafka so the acceptance artifact is not
limited by REST pagination.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import platform
import signal
import statistics
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import uuid

from kafka import KafkaConsumer


ROOT = Path(__file__).resolve().parents[1]
PLATFORM_DIR = ROOT / "platform"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

from scripts.bootstrap_mp4new_sources import MP4NEW_CATALOG  # noqa: E402
from utils_local.event_evidence import CONFLICT_EVIDENCE_KINDS  # noqa: E402


def source_catalog() -> dict[str, dict]:
    """Return only the eight mp4new/mp4new2 source profiles."""
    result: dict[str, dict] = {}
    for intersection in MP4NEW_CATALOG:
        shared = {
            key: value
            for key, value in intersection.items()
            if key not in {"sources", "test_coordinate"}
        }
        for source in intersection["sources"]:
            result[source["profile_id"]] = {**shared, **source}
    return result


def verify_native_mps() -> dict:
    import torch

    result = {
        "machine": platform.machine(),
        "python": platform.python_version(),
        "executable": sys.executable,
        "torch": torch.__version__,
        "mps_built": torch.backends.mps.is_built(),
        "mps_available": torch.backends.mps.is_available(),
    }
    if result["machine"] != "arm64":
        raise RuntimeError(f"native arm64 Python required, got {result['machine']}")
    if not result["mps_built"] or not result["mps_available"]:
        raise RuntimeError("PyTorch MPS is not built and available")
    return result


def validate_tcc_events(messages: list[dict]) -> list[dict]:
    invalid = []
    for message in messages:
        data = message.get("data") or {}
        try:
            distance = abs(float(data.get("distance_m")))
        except (TypeError, ValueError):
            distance = float("inf")
        evidence = data.get("evidence_images")
        evidence_kinds = tuple(
            item.get("kind") for item in evidence if isinstance(item, dict)
        ) if isinstance(evidence, list) else ()
        evidence_complete = (
            evidence_kinds == CONFLICT_EVIDENCE_KINDS
            and all(
                isinstance(item.get("jpeg_base64"), str) and item["jpeg_base64"]
                for item in evidence
            )
        )
        if (
            data.get("prediction_type") != "path_intersection"
            or distance > 0.05
            or not evidence_complete
        ):
            invalid.append(
                {
                    "message_id": message.get("message_id"),
                    "prediction_type": data.get("prediction_type"),
                    "distance_m": data.get("distance_m"),
                    "evidence_kinds": list(evidence_kinds),
                }
            )
    return invalid


def inference_summary(messages: list[dict]) -> dict:
    samples = []
    fps = []
    for message in messages:
        data = message.get("data") or {}
        if isinstance(data.get("inference_ms"), (int, float)):
            samples.append(float(data["inference_ms"]))
        if isinstance(data.get("fps"), (int, float)):
            fps.append(float(data["fps"]))
    if not samples:
        return {"samples": 0, "inference_ms": None, "fps_median": None}
    ordered = sorted(samples)
    p95_index = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
    return {
        "samples": len(samples),
        "inference_ms": {
            "min": round(min(samples), 1),
            "median": round(statistics.median(samples), 1),
            "p95": round(ordered[p95_index], 1),
            "max": round(max(samples), 1),
        },
        "fps_median": round(statistics.median(fps), 2) if fps else None,
    }


def tcc_diagnostics_summary(messages: list[dict]) -> dict:
    """Summarize observable TCC funnel execution without inventing events."""
    diagnostics = [
        message.get("data", {}).get("tcc_diagnostics")
        for message in messages
    ]
    diagnostics = [item for item in diagnostics if isinstance(item, dict)]
    status_counts: dict[str, int] = {}
    for item in diagnostics:
        status = str(item.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    def _positive(item: dict, key: str) -> bool:
        try:
            return float(item.get(key) or 0) > 0
        except (TypeError, ValueError):
            return False

    def _count(item: dict, key: str) -> int:
        try:
            return max(0, int(item.get(key) or 0))
        except (TypeError, ValueError):
            return 0

    return {
        "samples": len(diagnostics),
        "status_counts": dict(sorted(status_counts.items())),
        "frames_with_candidate_pairs": sum(
            _positive(item, "candidate_pairs") for item in diagnostics
        ),
        "frames_with_predictions": sum(
            _positive(item, "prediction_candidates") for item in diagnostics
        ),
        "business_events_emitted": sum(
            _count(item, "business_events_emitted") for item in diagnostics
        ),
    }


def source_result_passed(result: dict) -> bool:
    """Apply the per-source functional acceptance contract."""
    return bool(
        result.get("return_code") == 0
        and not result.get("error")
        and int(result.get("stats_count") or 0) > 0
        and int(result.get("trajectory_count") or 0) > 0
        and not result.get("invalid_tcc_events")
        and int((result.get("tcc_diagnostics") or {}).get("samples") or 0) > 0
    )


class PlatformClient:
    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.token: str | None = None
        self._login()

    def _login(self) -> None:
        login = self.request(
            "POST",
            "/api/v1/auth/login",
            {"username": self.username, "password": self.password},
            authenticated=False,
            retry_auth=False,
        )
        self.token = login["access_token"]

    def request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        *,
        authenticated: bool = True,
        retry_auth: bool = True,
    ):
        headers = {"Content-Type": "application/json"}
        token = getattr(self, "token", None)
        if authenticated and token:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(
            f"{self.base_url}{path}",
            method=method,
            headers=headers,
            data=json.dumps(body).encode("utf-8") if body is not None else None,
        )
        try:
            with urlopen(request, timeout=30) as response:
                payload = response.read()
                return json.loads(payload) if payload else None
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if authenticated and retry_auth and exc.code == 401:
                self._login()
                return self.request(
                    method,
                    path,
                    body,
                    authenticated=True,
                    retry_auth=False,
                )
            raise RuntimeError(f"Platform {method} {path} failed: HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"Platform is unavailable at {self.base_url}: {exc}") from exc

    def register(self, source: dict, camera_id: int, video_port: int) -> dict:
        return self.request(
            "POST",
            "/api/v1/pipelines/register",
            {
                "drone_id": source["drone_id"],
                "intersection_id": source["inter_id"],
                "video_src": source["video"],
                "roads_json": "",
                "camera_id": camera_id,
                "video_port": video_port,
                "topic_name": f"uav_statistics_{camera_id}",
            },
        )

    def stop(self, pipeline_id: str) -> None:
        self.request("DELETE", f"/api/v1/pipelines/{pipeline_id}")

    def stop_stale_reserved(self) -> list[str]:
        """Stop stale registrations owned by this serial replay runner."""
        stopped = []
        for pipeline in self.request("GET", "/api/v1/pipelines"):
            if (
                pipeline.get("status") == "running"
                and 5701 <= int(pipeline.get("camera_id") or 0) <= 5708
                and 15701 <= int(pipeline.get("video_port") or 0) <= 15708
            ):
                self.stop(pipeline["pipeline_id"])
                stopped.append(pipeline["pipeline_id"])
        return stopped


def _capture_message(buckets: dict[str, list[dict]], message, pipeline_id: str) -> bool:
    payload = message.value
    if not isinstance(payload, dict) or (payload.get("data") or {}).get("pipeline_id") != pipeline_id:
        return False
    if payload.get("msg_type") == "uav_stats":
        data = payload.get("data") or {}
        buckets["stats"].append(
            {
                "message_id": payload.get("message_id"),
                "occurred_at": payload.get("occurred_at"),
                "data": {
                    "pipeline_id": data.get("pipeline_id"),
                    "source_profile_id": data.get("source_profile_id"),
                    "inference_ms": data.get("inference_ms"),
                    "fps": data.get("fps"),
                    "active_tracks": data.get("active_tracks"),
                    "cars": data.get("cars"),
                    "conflict_count": data.get("conflict_count"),
                    "tcc_diagnostics": data.get("tcc_diagnostics"),
                },
            }
        )
    elif payload.get("msg_type") == "uav_track_complete":
        buckets["tracks"].append(payload)
    elif payload.get("msg_type") == "uav_conflict":
        buckets["conflicts"].append(payload)
    return True


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def hydra_string(value: str) -> str:
    """Quote a path as one Hydra string value, including spaces and CJK."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def terminate_process_tree(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=10)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)


def run_source(
    client: PlatformClient,
    source: dict,
    *,
    index: int,
    output_dir: Path,
    kafka_bootstrap: str,
    frame_stride: int,
    imgsz: int,
    drain_seconds: float,
) -> dict:
    camera_id = 5700 + index
    video_port = 15700 + index
    registered = client.register(source, camera_id, video_port)
    pipeline_id = registered["pipeline_id"]
    run_id = f"native-mps-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{source['profile_id']}"
    topics = [
        f"uav_statistics_{camera_id}",
        f"uav_track_complete_{camera_id}",
        f"uav_conflicts_{camera_id}",
    ]
    consumer = KafkaConsumer(
        bootstrap_servers=kafka_bootstrap,
        group_id=f"native-mps-acceptance-{uuid.uuid4().hex}",
        enable_auto_commit=False,
        auto_offset_reset="latest",
        consumer_timeout_ms=1000,
        value_deserializer=lambda raw: json.loads(raw.decode("utf-8")),
    )
    consumer.subscribe(topics)
    deadline = time.monotonic() + 15
    while not consumer.assignment() and time.monotonic() < deadline:
        consumer.poll(timeout_ms=500)
    if not consumer.assignment():
        consumer.close()
        client.stop(pipeline_id)
        raise RuntimeError(f"Kafka topic assignment timed out for {source['profile_id']}")
    consumer.seek_to_end(*consumer.assignment())

    source_dir = output_dir / source["profile_id"]
    source_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(
        {
            "VIDEO_SRC": str((ROOT / source["video"]).resolve()),
            "ROADS_JSON": "",
            "TOPIC_NAME": f"uav_statistics_{camera_id}",
            "CAMERA_ID": str(camera_id),
            "VIDEO_PORT": str(video_port),
            "KAFKA_BOOTSTRAP": kafka_bootstrap,
            "DRONE_ID": source["drone_id"],
            "INTERSECTION_ID": source["inter_id"],
            "INTER_ID": source["inter_id"],
            "PIPELINE_ID": pipeline_id,
            "RUN_ID": run_id,
            "SOURCE_PROFILE_ID": source["profile_id"],
            "ROAD_DATA_VERSION": source["road_data_version"],
            "ROAD_CONTEXT_STATUS": "unverified",
            "QUALITY_STATUS": "unverified",
            "FRAME_STRIDE": str(frame_stride),
            "KAFKA_SPOOL_DIR": str(source_dir / "kafka-spool"),
            "PYTORCH_ENABLE_MPS_FALLBACK": "1",
        }
    )
    command = [
        sys.executable,
        str(ROOT / "main_optimized.py"),
        "pipeline.show_in_web=false",
        "pipeline.save_video=false",
        "pipeline.send_info_kafka=true",
        "video_saver_node.save_conflict_clips=false",
        "kafka_producer_node.hover_annotation_snapshot_enabled=false",
        "detection_node.device=mps",
        f"detection_node.imgsz={imgsz}",
        "telemetry.enabled=true",
        "telemetry.source=file",
        f"telemetry.file_path={hydra_string(source['telemetry'])}",
        f"telemetry.time_offset_sec={source['time_offset_sec']}",
        f"telemetry.sync_tolerance_sec={source.get('sync_tolerance_sec', 2.5)}",
    ]
    buckets: dict[str, list[dict]] = {"stats": [], "tracks": [], "conflicts": []}
    started = time.monotonic()
    log_path = source_dir / "pipeline.log"
    return_code = None
    error = None
    process: subprocess.Popen | None = None
    try:
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
            while process.poll() is None:
                for messages in consumer.poll(timeout_ms=1000, max_records=1000).values():
                    for message in messages:
                        _capture_message(buckets, message, pipeline_id)
            return_code = process.returncode
            quiet_since = time.monotonic()
            final_deadline = quiet_since + drain_seconds
            while time.monotonic() < final_deadline:
                matched = False
                for messages in consumer.poll(timeout_ms=500, max_records=1000).values():
                    for message in messages:
                        matched = _capture_message(buckets, message, pipeline_id) or matched
                if matched:
                    quiet_since = time.monotonic()
                    final_deadline = quiet_since + drain_seconds
    except Exception as exc:  # Preserve artifacts and unregister before surfacing the failure.
        error = f"{type(exc).__name__}: {exc}"
    finally:
        terminate_process_tree(process)
        consumer.close()
        try:
            client.stop(pipeline_id)
        except Exception as exc:
            error = error or f"pipeline unregister failed: {exc}"

    invalid_tcc = validate_tcc_events(buckets["conflicts"])
    _write_json(source_dir / "tracks.json", buckets["tracks"])
    _write_json(source_dir / "tcc-events.json", buckets["conflicts"])
    _write_json(source_dir / "stats.json", buckets["stats"])
    result = {
        "profile_id": source["profile_id"],
        "pipeline_id": pipeline_id,
        "run_id": run_id,
        "video": source["video"],
        "telemetry": source["telemetry"],
        "time_offset_sec": source["time_offset_sec"],
        "camera_id": camera_id,
        "frame_stride": frame_stride,
        "imgsz": imgsz,
        "return_code": return_code,
        "elapsed_sec": round(time.monotonic() - started, 3),
        "stats_count": len(buckets["stats"]),
        "trajectory_count": len(buckets["tracks"]),
        "tcc_event_count": len(buckets["conflicts"]),
        "invalid_tcc_events": invalid_tcc,
        "tcc_diagnostics": tcc_diagnostics_summary(buckets["stats"]),
        "performance": inference_summary(buckets["stats"]),
        "error": error,
    }
    result["passed"] = source_result_passed(result)
    _write_json(source_dir / "result.json", result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", help="profile id; repeat to select sources")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--username", default=os.environ.get("PLATFORM_USERNAME", "admin"))
    parser.add_argument("--password", default=os.environ.get("PLATFORM_PASSWORD", "admin123"))
    parser.add_argument("--kafka-bootstrap", default="127.0.0.1:9092")
    parser.add_argument("--frame-stride", type=int, default=10)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--drain-seconds", type=float, default=5.0)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--resume", action="store_true", help="reuse completed source artifacts")
    parser.add_argument("--skip-preflight", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.frame_stride < 1:
        raise SystemExit("--frame-stride must be >= 1")
    catalog = source_catalog()
    selected = args.source or list(catalog)
    unknown = [profile_id for profile_id in selected if profile_id not in catalog]
    if unknown:
        raise SystemExit(f"unknown source profile(s): {', '.join(unknown)}")
    device = verify_native_mps() if not args.skip_preflight else {"skipped": True}
    for profile_id in selected:
        source = catalog[profile_id]
        for key in ("video", "telemetry"):
            if not (ROOT / source[key]).is_file():
                raise SystemExit(f"missing {key}: {source[key]}")
    if not (ROOT / "weights/yolo11s-visdrone.pt").is_file():
        raise SystemExit("missing weights/yolo11s-visdrone.pt")

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_dir = (args.output_dir or ROOT / "output" / "native-mps" / timestamp).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    client = PlatformClient(args.base_url, args.username, args.password)
    stale = client.stop_stale_reserved()
    if stale:
        print(f"stopped stale replay registrations: {', '.join(stale)}", flush=True)
    results = []
    for index, profile_id in enumerate(selected, start=1):
        existing_path = output_dir / profile_id / "result.json"
        if args.resume and existing_path.is_file():
            existing = json.loads(existing_path.read_text(encoding="utf-8"))
            recoverable_cleanup_error = str(existing.get("error") or "").startswith(
                "pipeline unregister failed:"
            )
            if recoverable_cleanup_error and (
                existing.get("return_code") == 0
                and existing.get("stats_count", 0) > 0
                and existing.get("trajectory_count", 0) > 0
                and not existing.get("invalid_tcc_events")
            ):
                existing["error"] = None
                existing["cleanup_recovered_on_resume"] = True
                existing["passed"] = source_result_passed(existing)
                _write_json(existing_path, existing)
            if existing.get("passed"):
                results.append(existing)
                print(f"[{index}/{len(selected)}] resumed {profile_id}", flush=True)
                continue
        print(f"[{index}/{len(selected)}] running {profile_id}", flush=True)
        result = run_source(
            client,
            catalog[profile_id],
            index=index,
            output_dir=output_dir,
            kafka_bootstrap=args.kafka_bootstrap,
            frame_stride=args.frame_stride,
            imgsz=args.imgsz,
            drain_seconds=args.drain_seconds,
        )
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        if not result["passed"]:
            break
    summary = {
        "schema_version": "uav.native-mps-replay-acceptance/v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "device": device,
        "selected_sources": selected,
        "completed_sources": len(results),
        "trajectory_count": sum(item["trajectory_count"] for item in results),
        "tcc_event_count": sum(item["tcc_event_count"] for item in results),
        "results": results,
        "passed": len(results) == len(selected) and all(item["passed"] for item in results),
    }
    _write_json(output_dir / "summary.json", summary)
    print(f"summary: {output_dir / 'summary.json'}", flush=True)
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
