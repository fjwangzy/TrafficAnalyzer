#!/usr/bin/env python3
"""Run mp4new/mp4new2 sources serially on native macOS MPS.

The detector runs on the host, publishes canonical messages to the root Compose
Kafka, and registers its lifecycle with Platform. Complete track and conflict
messages are captured directly from Kafka so the acceptance artifact is not
limited by REST pagination.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import cv2
from datetime import UTC, datetime
import hashlib
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

from scripts.bootstrap_mp4new_sources import ALL_LOCAL_REPLAY_CATALOG  # noqa: E402
from utils_local.event_evidence import CONFLICT_EVIDENCE_KINDS  # noqa: E402


def source_catalog() -> dict[str, dict]:
    """Return every registered local replay source profile."""
    result: dict[str, dict] = {}
    for intersection in ALL_LOCAL_REPLAY_CATALOG:
        shared = {
            key: value
            for key, value in intersection.items()
            if key not in {"sources", "test_coordinate"}
        }
        for source in intersection["sources"]:
            result[source["profile_id"]] = {**shared, **source}
    return result


def resolve_replay_imgsz(requested: int | None, *, adaptive_imgsz: bool) -> int:
    """Keep historical fixed replay at 640 and production adaptive fallback at 960."""
    if requested is not None:
        return int(requested)
    return 960 if adaptive_imgsz else 640


def video_fps(path: Path) -> float:
    """Read the source FPS used to derive a stable temporal sample rate."""
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"cannot open video for FPS probe: {path}")
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS))
    finally:
        capture.release()
    if not fps or fps <= 0:
        raise RuntimeError(f"invalid video FPS: {path}")
    return fps


def validate_source_assets(source: dict, digest_cache: dict[Path, str] | None = None) -> dict:
    """Verify immutable local source facts when a catalog manifest is available."""
    cache = digest_cache if digest_cache is not None else {}
    manifest = source.get("source_manifest") or {}
    checked = {}
    for kind, key in (("video", "video"), ("telemetry", "telemetry")):
        path = (ROOT / source[key]).resolve()
        if not path.is_file():
            raise RuntimeError(f"missing {kind}: {source[key]}")
        expected_size = manifest.get(f"{kind}_size_bytes")
        if expected_size is not None and path.stat().st_size != int(expected_size):
            raise RuntimeError(f"{kind} size mismatch for {source['profile_id']}")
        expected_digest = manifest.get(f"{kind}_sha256")
        if expected_digest:
            if path not in cache:
                digest = hashlib.sha256()
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
                cache[path] = digest.hexdigest()
            if cache[path] != expected_digest:
                raise RuntimeError(f"{kind} sha256 mismatch for {source['profile_id']}")
            checked[f"{kind}_sha256"] = cache[path]
    return checked


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
        evidence = data.get("evidence_files")
        evidence_kinds = tuple(
            item.get("kind") for item in evidence if isinstance(item, dict)
        ) if isinstance(evidence, list) else ()
        evidence_complete = (
            data.get("evidence_status") == "complete"
            and evidence_kinds == CONFLICT_EVIDENCE_KINDS
            and all(
                item.get("storage_backend") == "managed"
                and isinstance(item.get("storage_key"), str)
                and item["storage_key"].startswith("objects/")
                and not Path(item["storage_key"]).is_absolute()
                and isinstance(item.get("sha256"), str)
                and len(item["sha256"]) == 64
                and item["storage_key"].endswith(item["sha256"])
                and isinstance(item.get("size_bytes"), int)
                and item["size_bytes"] > 0
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
    pipeline_samples = []
    fps = []
    imgsz_counts: Counter[str] = Counter()
    for message in messages:
        data = message.get("data") or {}
        if isinstance(data.get("inference_ms"), (int, float)):
            samples.append(float(data["inference_ms"]))
        if isinstance(data.get("pipeline_processing_ms"), (int, float)):
            pipeline_samples.append(float(data["pipeline_processing_ms"]))
        if isinstance(data.get("fps"), (int, float)):
            fps.append(float(data["fps"]))
        imgsz = (data.get("inference_context") or {}).get("effective_imgsz")
        if isinstance(imgsz, (int, float)):
            imgsz_counts[str(int(imgsz))] += 1
    if not samples:
        return {
            "samples": 0,
            "inference_ms": None,
            "pipeline_processing_ms": None,
            "imgsz_counts": dict(imgsz_counts),
            "fps_median": None,
        }

    def distribution(values: list[float]) -> dict | None:
        if not values:
            return None
        ordered = sorted(values)
        p95_index = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
        return {
            "min": round(min(values), 1),
            "median": round(statistics.median(values), 1),
            "p95": round(ordered[p95_index], 1),
            "max": round(max(values), 1),
        }

    return {
        "samples": len(samples),
        "inference_ms": distribution(samples),
        "pipeline_processing_ms": distribution(pipeline_samples),
        "imgsz_counts": dict(sorted(imgsz_counts.items())),
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

    rejection_keys = (
        "speed_missing",
        "speed_below_min",
        "history_insufficient",
        "displacement_insufficient",
        "distance_filtered",
        "prediction_failed",
        "scene_filtered",
        "evidence_failed",
        "severity_filtered",
        "deduplicated",
    )
    funnel_rejections = {
        key: sum(_count(item, key) for item in diagnostics)
        for key in rejection_keys
    }

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
        "funnel_rejections": {
            key: value for key, value in funnel_rejections.items() if value > 0
        },
    }


def candidate_isolation_summary(messages: list[dict]) -> dict:
    """Aggregate bounded candidate/quality evidence from compact Stats captures."""
    reason_counts: Counter[str] = Counter()
    candidate_frames = 0
    candidate_peak = 0
    point_alignment_failures = 0
    telemetry_observed = 0
    telemetry_verified = 0
    formal_frames = 0
    active_formal_peak = 0
    cars_peak = 0.0
    conflicts = 0
    road_activity_frames = 0
    lane_stats_frames = 0
    for message in messages:
        data = message.get("data") or {}
        candidate_count = int(data.get("candidate_tracks") or 0)
        candidate_peak = max(candidate_peak, candidate_count)
        candidate_frames += candidate_count > 0
        point_alignment_failures += int(data.get("candidate_alignment_failures") or 0)
        reason_counts.update(str(reason) for reason in data.get("quality_reasons") or [])
        geo_quality = data.get("geo_reference_quality") or {}
        telemetry = geo_quality.get("telemetry") if isinstance(geo_quality, dict) else None
        telemetry_status = telemetry.get("status") if isinstance(telemetry, dict) else None
        telemetry_observed += telemetry_status not in {None, "missing", "unavailable"}
        telemetry_verified += telemetry_status == "verified"
        formal_frames += bool(data.get("formal_analytics_eligible"))
        active_formal_peak = max(active_formal_peak, int(data.get("active_tracks") or 0))
        try:
            cars_peak = max(cars_peak, float(data.get("cars") or 0))
        except (TypeError, ValueError):
            pass
        conflicts += int(data.get("conflict_count") or 0)
        road_activity_frames += bool(data.get("roads_activity"))
        lane_stats_frames += bool(data.get("lane_stats"))
    total = len(messages)
    return {
        "stats_samples": total,
        "frames_with_candidates": candidate_frames,
        "candidate_tracks_peak": candidate_peak,
        "candidate_point_alignment_failures": point_alignment_failures,
        "quality_reason_counts": dict(sorted(reason_counts.items())),
        "telemetry_observed_samples": telemetry_observed,
        "telemetry_coverage_ratio": round(telemetry_observed / total, 4) if total else 0.0,
        "telemetry_verified_samples": telemetry_verified,
        "telemetry_verified_ratio": round(telemetry_verified / total, 4) if total else 0.0,
        "formal_frames": formal_frames,
        "active_formal_tracks_peak": active_formal_peak,
        "cars_peak": cars_peak,
        "conflict_count": conflicts,
        "road_activity_frames": road_activity_frames,
        "lane_stats_frames": lane_stats_frames,
    }


def completed_trajectory_summary(messages: list[dict]) -> dict:
    """Validate the index-aligned pixel-first completed trajectory contract."""
    alignment_failures = 0
    pixel_trajectory_count = 0
    eligible_completed_tracks = 0
    geo_complete_tracks = 0
    failure_message_ids = []
    for message in messages:
        data = message.get("data") or {}
        pixels = data.get("trajectory_px")
        timestamps = data.get("trajectory_timestamps_sec")
        frame_nums = data.get("trajectory_frame_nums")
        enu = data.get("trajectory_enu_m")
        gcj02 = data.get("trajectory_gcj02")
        point_count = len(pixels) if isinstance(pixels, list) else 0
        aligned = bool(
            point_count > 0
            and isinstance(timestamps, list) and len(timestamps) == point_count
            and isinstance(frame_nums, list) and len(frame_nums) == point_count
            and isinstance(enu, list) and len(enu) == point_count
            and isinstance(gcj02, list) and len(gcj02) == point_count
        )
        if point_count:
            pixel_trajectory_count += 1
        if data.get("trajectory_output_eligible") is True and point_count:
            eligible_completed_tracks += 1
        if aligned and sum(point is not None for point in gcj02) >= 2:
            geo_complete_tracks += 1
        if not aligned:
            alignment_failures += 1
            failure_message_ids.append(message.get("message_id"))
    return {
        "completed_tracks": len(messages),
        "eligible_completed_tracks": eligible_completed_tracks,
        "pixel_trajectory_count": pixel_trajectory_count,
        "geo_complete_tracks": geo_complete_tracks,
        "point_alignment_failures": alignment_failures,
        "failure_message_ids": failure_message_ids[:50],
    }


def formal_business_leakage(result: dict) -> dict:
    candidate = result.get("candidate_isolation") or {}
    tcc = result.get("tcc_diagnostics") or {}
    counts = {
        "formal_frames": int(candidate.get("formal_frames") or 0),
        "cars_peak": float(candidate.get("cars_peak") or 0),
        "road_activity_frames": int(candidate.get("road_activity_frames") or 0),
        "lane_stats_frames": int(candidate.get("lane_stats_frames") or 0),
        "stats_conflicts": int(candidate.get("conflict_count") or 0),
        "conflict_events": int(result.get("tcc_event_count") or 0),
        "tcc_business_events": int(tcc.get("business_events_emitted") or 0),
    }
    return {
        **counts,
        "total": (
            counts["formal_frames"]
            + counts["road_activity_frames"]
            + counts["lane_stats_frames"]
        ),
    }


def source_result_passed(result: dict) -> bool:
    """Apply the per-source functional acceptance contract."""
    base = bool(
        result.get("return_code") == 0
        and not result.get("error")
        and int(result.get("stats_count") or 0) > 0
        and not result.get("invalid_tcc_events")
        and int((result.get("tcc_diagnostics") or {}).get("samples") or 0) > 0
        and result.get("natural_eof", True)
        and (result.get("road9_reconciliation") or {"matched": True}).get("matched", False)
    )
    trajectory = result.get("trajectory_output")
    if trajectory is None:
        trajectory = {
            "eligible_completed_tracks": int(result.get("trajectory_count") or 0),
            "point_alignment_failures": 0,
        }
    if result.get("acceptance_mode") in {"roadless_trajectory", "candidate_isolation"}:
        isolation = result.get("candidate_isolation") or {}
        leakage = result.get("formal_business_leakage") or formal_business_leakage(result)
        return bool(
            base
            and int(isolation.get("active_formal_tracks_peak") or 0) > 0
            and int(isolation.get("candidate_point_alignment_failures") or 0) == 0
            and int(trajectory.get("eligible_completed_tracks") or 0) > 0
            and int(trajectory.get("point_alignment_failures") or 0) == 0
            and float(leakage.get("total") or 0) == 0
        )
    return bool(
        base
        and int(trajectory.get("eligible_completed_tracks") or 0) > 0
        and int(trajectory.get("point_alignment_failures") or 0) == 0
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

    def runtime_bundle(self, source: dict, *, required: bool = True) -> dict | None:
        maps = self.request(
            "GET", f"/api/v1/calibration/channelized-maps?inter_id={source['inter_id']}"
        )
        eligible = sorted(
            (item for item in maps if item.get("status") == "lane_verified"),
            key=lambda item: int(item.get("version_no") or 0),
            reverse=True,
        )
        for selected in eligible:
            bundle = self.request(
                "GET",
                f"/api/v1/calibration/channelized-maps/{selected['id']}/runtime-bundle",
            )
            return bundle
        if not required:
            return None
        raise RuntimeError(
            "stage-1 gate blocked: no lane_verified map for "
            f"{source['inter_id']}"
        )

    def register(
        self,
        source: dict,
        camera_id: int,
        video_port: int,
        runtime_bundle: dict | None,
        tracking_profile: str = "hover_cruise_v1",
    ) -> dict:
        return self.request(
            "POST",
            "/api/v1/pipelines/register",
            {
                "drone_id": source["drone_id"],
                "intersection_id": source["inter_id"],
                "source_profile_id": source["profile_id"],
                "inter_id": source["inter_id"],
                "video_src": source["video"],
                "map_version_id": runtime_bundle["map_version_id"] if runtime_bundle else None,
                "road_data_version": runtime_bundle["road_data_version"] if runtime_bundle else None,
                "camera_id": camera_id,
                "video_port": video_port,
                "video_stream_url": f"http://127.0.0.1:{video_port}/video",
                "topic_name": f"uav_statistics_{camera_id}",
                "tracking_profile": tracking_profile,
                "candidate_only": False,
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
                and 5701 <= int(pipeline.get("camera_id") or 0) <= 5712
                and 15701 <= int(pipeline.get("video_port") or 0) <= 15712
            ):
                self.stop(pipeline["pipeline_id"])
                stopped.append(pipeline["pipeline_id"])
        return stopped


def _candidate_capture(data: dict) -> dict:
    candidates = data.get("candidate_trajectories")
    if not isinstance(candidates, list):
        candidates = []
    reasons: set[str] = set()
    alignment_failures = 0
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        reasons.update(str(reason) for reason in candidate.get("quality_reasons") or [])
        base = candidate.get("trajectory_px")
        if not isinstance(base, list):
            continue
        for key in ("trajectory_enu_m", "trajectory_timestamps_sec", "trajectory_frame_nums"):
            values = candidate.get(key)
            if isinstance(values, list) and len(values) != len(base):
                alignment_failures += 1
    geo_quality = data.get("geo_reference_quality")
    if isinstance(geo_quality, dict):
        reasons.update(str(reason) for reason in geo_quality.get("reasons") or [])
    return {
        "candidate_tracks": len(candidates),
        "candidate_alignment_failures": alignment_failures,
        "quality_reasons": sorted(reasons),
    }


def _capture_message(buckets: dict[str, list[dict]], message, pipeline_id: str) -> bool:
    payload = message.value
    if not isinstance(payload, dict) or (payload.get("data") or {}).get("pipeline_id") != pipeline_id:
        return False
    if payload.get("msg_type") == "uav_stats":
        data = payload.get("data") or {}
        candidate = _candidate_capture(data)
        buckets["stats"].append(
            {
                "message_id": payload.get("message_id"),
                "occurred_at": payload.get("occurred_at"),
                "data": {
                    "pipeline_id": data.get("pipeline_id"),
                    "source_profile_id": data.get("source_profile_id"),
                    "inference_ms": data.get("inference_ms"),
                    "pipeline_processing_ms": data.get("pipeline_processing_ms"),
                    "inference_context": data.get("inference_context"),
                    "fps": data.get("fps"),
                    "active_tracks": data.get("eligible_active_tracks", data.get("active_tracks")),
                    "candidate_tracks": candidate["candidate_tracks"],
                    "candidate_alignment_failures": candidate["candidate_alignment_failures"],
                    "quality_reasons": candidate["quality_reasons"],
                    "cars": data.get("cars"),
                    "conflict_count": data.get("conflict_count"),
                    "tcc_diagnostics": data.get("tcc_diagnostics"),
                    "flight_phase": data.get("flight_phase"),
                    "geo_reference_quality": data.get("geo_reference_quality"),
                    "formal_analytics_eligible": data.get("formal_analytics_eligible"),
                    "trajectory_output_eligible": data.get("trajectory_output_eligible"),
                    "geo_analytics_eligible": data.get("geo_analytics_eligible"),
                    "road_analytics_eligible": data.get("road_analytics_eligible"),
                    "tcc_analytics_eligible": data.get("tcc_analytics_eligible"),
                },
            }
        )
    elif payload.get("msg_type") == "uav_track_complete":
        buckets["tracks"].append(payload)
    elif payload.get("msg_type") == "uav_conflict":
        buckets["conflicts"].append(payload)
    elif payload.get("msg_type") == "uav_telemetry":
        buckets["telemetry"].append(
            {
                "message_id": payload.get("message_id"),
                "occurred_at": payload.get("occurred_at"),
                "quality_status": payload.get("quality_status"),
            }
        )
    return True


async def _road9_counts(source_profile_id: str, pipeline_id: str) -> dict[str, int]:
    from sqlalchemy import distinct, func, select

    from app.core.database import async_session_maker
    from app.models.metrics import ConflictEvent, TelemetryMetric, TrackEvent, TrafficMetric

    async with async_session_maker() as session:
        counts = {}
        for key, model in (
            ("stats", TrafficMetric),
            ("tracks", TrackEvent),
            ("conflicts", ConflictEvent),
            ("telemetry", TelemetryMetric),
        ):
            counts[key] = int(
                (
                    await session.execute(
                        select(func.count(distinct(model.source_message_id))).where(
                            model.source_profile_id == source_profile_id,
                            model.pipeline_id == pipeline_id,
                        )
                    )
                ).scalar_one()
            )
        return counts


async def _wait_for_road9(
    source_profile_id: str,
    pipeline_id: str,
    expected: dict[str, int],
    timeout_sec: float = 30.0,
) -> dict:
    deadline = time.monotonic() + timeout_sec
    actual = {key: 0 for key in expected}
    while True:
        actual = await _road9_counts(source_profile_id, pipeline_id)
        if all(actual.get(key, 0) == value for key, value in expected.items()):
            break
        if time.monotonic() >= deadline:
            break
        await asyncio.sleep(0.5)
    mismatches = {
        key: {"kafka": value, "road9": actual.get(key, 0)}
        for key, value in expected.items()
        if actual.get(key, 0) != value
    }
    return {
        "source_profile_id": source_profile_id,
        "pipeline_id": pipeline_id,
        "kafka": expected,
        "road9": actual,
        "mismatches": mismatches,
        "matched": not mismatches,
    }


async def _reconcile_road9_once(
    source_profile_id: str,
    pipeline_id: str,
    expected: dict[str, int],
) -> dict:
    """Run one reconciliation loop and release loop-bound asyncpg connections."""
    from app.core.database import close_db

    try:
        return await _wait_for_road9(source_profile_id, pipeline_id, expected)
    finally:
        await close_db()


def reconcile_road9(source_profile_id: str, pipeline_id: str, buckets: dict) -> dict:
    expected = {key: len(buckets[key]) for key in ("stats", "tracks", "conflicts", "telemetry")}
    try:
        return asyncio.run(_reconcile_road9_once(source_profile_id, pipeline_id, expected))
    except Exception as exc:
        return {
            "source_profile_id": source_profile_id,
            "pipeline_id": pipeline_id,
            "kafka": expected,
            "road9": None,
            "mismatches": {"query": str(exc)},
            "matched": False,
        }


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def hydra_string(value: str) -> str:
    """Quote a path as one Hydra string value, including spaces and CJK."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def telemetry_overrides(source: dict) -> list[str]:
    """Build explicit Hydra telemetry overrides without borrowing another flight's OSD."""
    if not source.get("telemetry_enabled", True):
        return ["telemetry.enabled=false"]
    return [
        "telemetry.enabled=true",
        f"telemetry.source={source.get('telemetry_type', 'file')}",
        f"telemetry.file_path={hydra_string(source['telemetry'])}",
        f"telemetry.time_offset_sec={source['time_offset_sec']}",
        f"telemetry.sync_tolerance_sec={source.get('sync_tolerance_sec', 2.5)}",
    ]


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
    input_fps: float,
    sample_fps: float,
    imgsz: int,
    adaptive_imgsz: bool,
    drain_seconds: float,
    tracking_profile: str,
    show_in_web: bool = False,
    save_video: bool = False,
) -> dict:
    camera_id = 5700 + index
    video_port = 15700 + index
    configured_mode = source.get("acceptance_mode", "formal_world_trajectory")
    runtime_bundle = client.runtime_bundle(
        source,
        required=configured_mode not in {"roadless_trajectory", "candidate_isolation"},
    )
    telemetry_enabled = source.get("telemetry_enabled", True)
    if not telemetry_enabled:
        runtime_bundle = None
    acceptance_mode = "formal_world_trajectory" if runtime_bundle is not None else "roadless_trajectory"
    registered = client.register(
        source,
        camera_id,
        video_port,
        runtime_bundle,
        tracking_profile=tracking_profile,
    )
    pipeline_id = registered["pipeline_id"]
    run_id = f"native-mps-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{source['profile_id']}"
    topics = [
        f"uav_statistics_{camera_id}",
        f"uav_track_complete_{camera_id}",
        f"uav_conflicts_{camera_id}",
        f"uav_telemetry_{camera_id}",
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
    env.pop("RUNTIME_GEO_REGISTRATION_JSON", None)
    env.pop("RUNTIME_MAP_BUNDLE_JSON", None)
    env.update(
        {
            "VIDEO_SRC": str((ROOT / source["video"]).resolve()),
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
            "ROAD_DATA_VERSION": runtime_bundle["road_data_version"] if runtime_bundle else "",
            "ROAD_CONTEXT_STATUS": "lane_verified" if runtime_bundle else "missing",
            "QUALITY_STATUS": "verified" if runtime_bundle else "degraded",
            "TRACKING_PROFILE": tracking_profile,
            "FRAME_STRIDE": str(frame_stride),
            "KAFKA_SPOOL_DIR": str(source_dir / "kafka-spool"),
            "PYTORCH_ENABLE_MPS_FALLBACK": "1",
        }
    )
    if runtime_bundle:
        env["RUNTIME_MAP_BUNDLE_JSON"] = json.dumps(
            runtime_bundle, ensure_ascii=False, separators=(",", ":")
        )
    command = [
        sys.executable,
        str(ROOT / "main_optimized.py"),
        f"pipeline.show_in_web={'true' if show_in_web else 'false'}",
        f"pipeline.save_video={'true' if save_video else 'false'}",
        "pipeline.send_info_kafka=true",
        f"video_saver_node.out_folder={hydra_string(str(source_dir))}",
        "video_saver_node.save_conflict_clips=false",
        "kafka_producer_node.hover_annotation_snapshot_enabled=false",
        "detection_node.device=mps",
        f"detection_node.imgsz={imgsz}",
        f"detection_node.adaptive_imgsz.enabled={'true' if adaptive_imgsz else 'false'}",
        f"tracking_profile={tracking_profile}",
    ]
    command.extend(telemetry_overrides(source))
    buckets: dict[str, list[dict]] = {
        "stats": [],
        "tracks": [],
        "conflicts": [],
        "telemetry": [],
    }
    started = time.monotonic()
    log_path = source_dir / "pipeline.log"
    return_code = None
    error = None
    road9 = None
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
        # Keep the external pipeline registration alive until Platform has
        # consumed every Kafka message observed by this acceptance consumer.
        # Unregistering first can make the final EOF-adjacent stats envelope
        # fail the active-pipeline identity gate, leaving road9 one row short.
        road9 = reconcile_road9(source["profile_id"], pipeline_id, buckets)
        try:
            client.stop(pipeline_id)
        except Exception as exc:
            error = error or f"pipeline unregister failed: {exc}"

    invalid_tcc = validate_tcc_events(buckets["conflicts"])
    _write_json(source_dir / "tracks.json", buckets["tracks"])
    _write_json(source_dir / "tcc-events.json", buckets["conflicts"])
    _write_json(source_dir / "stats.json", buckets["stats"])
    _write_json(source_dir / "telemetry.json", buckets["telemetry"])
    candidate = candidate_isolation_summary(buckets["stats"])
    trajectory_output = completed_trajectory_summary(buckets["tracks"])
    result = {
        "profile_id": source["profile_id"],
        "pipeline_id": pipeline_id,
        "run_id": run_id,
        "map_version_id": runtime_bundle["map_version_id"] if runtime_bundle else None,
        "road_data_version": runtime_bundle["road_data_version"] if runtime_bundle else None,
        "road_context_status": "lane_verified" if runtime_bundle else "missing",
        "quality_status": "verified" if runtime_bundle else "degraded",
        "acceptance_mode": acceptance_mode,
        "video": source["video"],
        "telemetry": source["telemetry"],
        "telemetry_enabled": telemetry_enabled,
        "time_offset_sec": source["time_offset_sec"],
        "camera_id": camera_id,
        "frame_stride": frame_stride,
        "input_fps": round(input_fps, 3),
        "sample_fps": round(sample_fps, 3),
        "imgsz": imgsz,
        "adaptive_imgsz": adaptive_imgsz,
        "tracking_profile": tracking_profile,
        "show_in_web": show_in_web,
        "save_video": save_video,
        "return_code": return_code,
        "natural_eof": return_code == 0,
        "elapsed_sec": round(time.monotonic() - started, 3),
        "stats_count": len(buckets["stats"]),
        "trajectory_count": len(buckets["tracks"]),
        "tcc_event_count": len(buckets["conflicts"]),
        "telemetry_message_count": len(buckets["telemetry"]),
        "invalid_tcc_events": invalid_tcc,
        "tcc_diagnostics": tcc_diagnostics_summary(buckets["stats"]),
        "candidate_isolation": candidate,
        "trajectory_output": trajectory_output,
        "eligible_completed_tracks": trajectory_output["eligible_completed_tracks"],
        "road9_reconciliation": road9,
        "performance": inference_summary(buckets["stats"]),
        "error": error,
    }
    result["formal_business_leakage"] = formal_business_leakage(result)
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
    parser.add_argument("--frame-stride", type=int, help="fixed override; otherwise derived from --sample-fps")
    parser.add_argument("--sample-fps", type=float, default=3.0)
    parser.add_argument(
        "--imgsz",
        type=int,
        default=None,
        help="fixed size (default 640), or adaptive missing-telemetry fallback (default 960)",
    )
    parser.add_argument(
        "--adaptive-imgsz",
        action="store_true",
        help="enable production altitude-aware 640/960/1280 inference tiers; fixed --imgsz is the default",
    )
    parser.add_argument(
        "--tracking-profile",
        choices=("hover_cruise_v1", "hover_only_legacy"),
        default="hover_cruise_v1",
        help="explicit Mission tracking profile recorded by Platform and the detector",
    )
    parser.add_argument("--drain-seconds", type=float, default=5.0)
    parser.add_argument(
        "--show-in-web",
        action="store_true",
        help="serve the MJPEG stream during an interactive browser acceptance run",
    )
    parser.add_argument(
        "--save-video",
        action="store_true",
        help="save the production ShowNode output beside the replay result",
    )
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--resume", action="store_true", help="reuse completed source artifacts")
    parser.add_argument("--skip-preflight", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.frame_stride is not None and args.frame_stride < 1:
        raise SystemExit("--frame-stride must be >= 1")
    if args.sample_fps <= 0:
        raise SystemExit("--sample-fps must be > 0")
    catalog = source_catalog()
    selected = args.source or list(catalog)
    unknown = [profile_id for profile_id in selected if profile_id not in catalog]
    if unknown:
        raise SystemExit(f"unknown source profile(s): {', '.join(unknown)}")
    device = verify_native_mps() if not args.skip_preflight else {"skipped": True}
    digest_cache: dict[Path, str] = {}
    source_integrity = {}
    for profile_id in selected:
        source = catalog[profile_id]
        try:
            source_integrity[profile_id] = validate_source_assets(source, digest_cache)
        except RuntimeError as exc:
            raise SystemExit(str(exc)) from exc
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
    effective_imgsz = resolve_replay_imgsz(
        args.imgsz,
        adaptive_imgsz=args.adaptive_imgsz,
    )
    for index, profile_id in enumerate(selected, start=1):
        existing_path = output_dir / profile_id / "result.json"
        if args.resume and existing_path.is_file():
            existing = json.loads(existing_path.read_text(encoding="utf-8"))
            recoverable_cleanup_error = str(existing.get("error") or "").startswith(
                "pipeline unregister failed:"
            )
            if recoverable_cleanup_error and existing.get("return_code") == 0:
                existing["error"] = None
                existing["cleanup_recovered_on_resume"] = True
                existing["passed"] = source_result_passed(existing)
                _write_json(existing_path, existing)
            if existing.get("passed"):
                results.append(existing)
                print(f"[{index}/{len(selected)}] resumed {profile_id}", flush=True)
                continue
        print(f"[{index}/{len(selected)}] running {profile_id}", flush=True)
        input_fps = video_fps(ROOT / catalog[profile_id]["video"])
        frame_stride = args.frame_stride or max(1, int(round(input_fps / args.sample_fps)))
        result = run_source(
            client,
            catalog[profile_id],
            index=index,
            output_dir=output_dir,
            kafka_bootstrap=args.kafka_bootstrap,
            frame_stride=frame_stride,
            input_fps=input_fps,
            sample_fps=input_fps / frame_stride,
            imgsz=effective_imgsz,
            adaptive_imgsz=args.adaptive_imgsz,
            drain_seconds=args.drain_seconds,
            tracking_profile=args.tracking_profile,
            show_in_web=args.show_in_web,
            save_video=args.save_video,
        )
        result["source_integrity"] = source_integrity[profile_id]
        result["source_input_complete"] = not bool(catalog[profile_id].get("known_degradation"))
        _write_json(output_dir / profile_id / "result.json", result)
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        if not result["passed"]:
            break
    engineering_passed = len(results) == len(selected) and all(item["passed"] for item in results)
    source_inputs_complete = len(results) == len(selected) and all(
        item.get("source_input_complete", True) for item in results
    )
    summary = {
        "schema_version": "uav.native-mps-replay-acceptance/v2",
        "generated_at": datetime.now(UTC).isoformat(),
        "device": device,
        "selected_sources": selected,
        "completed_sources": len(results),
        "tracking_profile": args.tracking_profile,
        "trajectory_count": sum(item["trajectory_count"] for item in results),
        "tcc_event_count": sum(item["tcc_event_count"] for item in results),
        "candidate_frames": sum(
            int((item.get("candidate_isolation") or {}).get("frames_with_candidates") or 0)
            for item in results
        ),
        "source_inputs_complete": source_inputs_complete,
        "accuracy_metrics": {
            "idf1": "not_evaluated",
            "hota": "not_evaluated",
            "id_switches": "not_evaluated",
            "position_rmse": "not_evaluated",
            "speed_mae": "not_evaluated",
        },
        "results": results,
        "engineering_passed": engineering_passed,
        "acceptance_status": (
            "passed" if engineering_passed and source_inputs_complete
            else "partial" if engineering_passed
            else "failed"
        ),
        "passed": engineering_passed,
    }
    _write_json(output_dir / "summary.json", summary)
    print(f"summary: {output_dir / 'summary.json'}", flush=True)
    return 0 if engineering_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
