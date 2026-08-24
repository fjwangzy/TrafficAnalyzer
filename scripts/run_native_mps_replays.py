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
import re
import signal
import statistics
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from kafka import KafkaConsumer, TopicPartition
from kafka.errors import (
    KafkaConnectionError,
    NoBrokersAvailable,
    NodeNotReadyError,
    RequestTimedOutError,
    UnrecognizedBrokerVersion,
)


ROOT = Path(__file__).resolve().parents[1]
PLATFORM_DIR = ROOT / "platform"
RUNNER_CAMERA_ID_MIN = 30000
RUNNER_CAMERA_ID_MAX = 35500
RUNNER_VIDEO_PORT_MIN = 16000
LEGACY_RUNNER_CAMERA_ID_MIN = 5701
LEGACY_RUNNER_CAMERA_ID_MAX = 5712
LEGACY_RUNNER_VIDEO_PORT_MIN = 15701
LEGACY_RUNNER_VIDEO_PORT_MAX = 15712
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
    """Use the production 960 fallback unless fixed-size diagnostics are explicit."""
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


def validate_source_time_stride(
    frame_stride: int,
    input_fps: float,
    *,
    max_frame_gap_sec: float = 0.5,
) -> float:
    """Reject replay sampling that would intentionally terminate every ID."""
    source_gap_sec = float(frame_stride) / float(input_fps)
    if source_gap_sec > max_frame_gap_sec:
        raise ValueError(
            f"frame stride creates {source_gap_sec:.6f}s source-time gap; "
            f"tracker maximum is {max_frame_gap_sec:.6f}s"
        )
    return source_gap_sec


def choose_runner_camera_id_base(used_camera_ids: set[int], source_count: int) -> int:
    """Reserve a contiguous never-before-used camera/topic range for one replay.

    road9's inbox intentionally treats ``topic + partition + offset`` as
    immutable. Reusing a numeric camera id would therefore make Kafka offset
    zero from a later replay collide with a prior run. The reserved range keeps
    the topic identity unique while still leaving regular production camera ids
    untouched.
    """
    if source_count < 1:
        raise ValueError("source_count must be positive")
    last_base = RUNNER_CAMERA_ID_MAX - source_count + 1
    for base in range(RUNNER_CAMERA_ID_MIN, last_base + 1):
        if all(camera_id not in used_camera_ids for camera_id in range(base + 1, base + source_count + 1)):
            return base
    raise RuntimeError("no unused reserved camera/topic ids remain for native replay")


def replay_video_port_base(camera_id_base: int) -> int:
    """Map a reserved replay camera range to its equally isolated MJPEG ports."""
    if RUNNER_CAMERA_ID_MIN <= camera_id_base <= RUNNER_CAMERA_ID_MAX:
        return RUNNER_VIDEO_PORT_MIN + (camera_id_base - RUNNER_CAMERA_ID_MIN)
    return LEGACY_RUNNER_VIDEO_PORT_MIN - 1


def _assign_topics_to_end(
    consumer: KafkaConsumer,
    topics: list[str],
    timeout_sec: float = 15.0,
) -> list[TopicPartition]:
    """Manually assign capture topics and avoid a long-lived group heartbeat.

    The acceptance reader never commits offsets and owns a unique, read-once
    capture window.  Group coordination only adds a heartbeat thread which can
    race kafka-python's socket cleanup during long native-MPS runs.
    """
    deadline = time.monotonic() + timeout_sec
    partitions: list[TopicPartition] = []
    while time.monotonic() < deadline:
        partitions = sorted(
            (
                TopicPartition(topic, partition)
                for topic in topics
                for partition in (consumer.partitions_for_topic(topic) or set())
            ),
            key=lambda item: (item.topic, item.partition),
        )
        if partitions:
            break
        consumer.poll(timeout_ms=500)
    if not partitions:
        raise RuntimeError(f"Kafka topic metadata timed out: {topics}")
    consumer.assign(partitions)
    consumer.seek_to_end(*partitions)
    return partitions


class RecoveringKafkaCapture:
    """Capture a replay topic window and recover transient selector failures.

    kafka-python can surface ``Invalid file descriptor`` after a long-running
    broker connection is replaced or closed.  The acceptance reader is not the
    business consumer, so it must not terminate an otherwise healthy detector.
    Keep explicit next offsets and rebuild the manually assigned consumer from
    those offsets; this preserves the exact capture window without committing a
    group offset or skipping messages produced during recovery.
    """

    def __init__(
        self,
        kafka_bootstrap: str,
        topics: list[str],
        *,
        consumer_factory=KafkaConsumer,
        recovery_timeout_sec: float = 90.0,
        recovery_backoff_sec: float = 1.0,
    ) -> None:
        self.kafka_bootstrap = kafka_bootstrap
        self.topics = list(topics)
        self.consumer_factory = consumer_factory
        self.recovery_timeout_sec = recovery_timeout_sec
        self.recovery_backoff_sec = recovery_backoff_sec
        self.consumer = None
        self.next_offsets: dict[TopicPartition, int] = {}
        self.recovery_count = 0
        self._open(initial=True)

    def _new_consumer(self):
        return self.consumer_factory(
            bootstrap_servers=self.kafka_bootstrap,
            group_id=None,
            enable_auto_commit=False,
            auto_offset_reset="latest",
            consumer_timeout_ms=1000,
            value_deserializer=lambda raw: json.loads(raw.decode("utf-8")),
        )

    def _open(self, *, initial: bool) -> None:
        consumer = self._new_consumer()
        try:
            partitions = _assign_topics_to_end(consumer, self.topics)
            if initial:
                self.next_offsets = {
                    partition: int(consumer.position(partition))
                    for partition in partitions
                }
            else:
                for partition in partitions:
                    offset = self.next_offsets.get(partition)
                    if offset is None:
                        self.next_offsets[partition] = int(
                            consumer.position(partition)
                        )
                    else:
                        consumer.seek(partition, offset)
        except Exception:
            consumer.close()
            raise
        self.consumer = consumer

    @staticmethod
    def _recoverable(exc: Exception) -> bool:
        return (
            isinstance(exc, ValueError)
            and "Invalid file descriptor" in str(exc)
        ) or isinstance(
            exc,
            (
                KafkaConnectionError,
                NoBrokersAvailable,
                NodeNotReadyError,
                RequestTimedOutError,
                UnrecognizedBrokerVersion,
            ),
        )

    def _recover(self, *, deadline: float) -> None:
        if self.consumer is not None:
            try:
                self.consumer.close()
            except Exception:
                pass
            self.consumer = None
        while True:
            try:
                self._open(initial=False)
                self.recovery_count += 1
                return
            except Exception as exc:
                if not self._recoverable(exc) or time.monotonic() >= deadline:
                    raise
                time.sleep(self.recovery_backoff_sec)

    def poll(self, *, timeout_ms: int, max_records: int):
        deadline = time.monotonic() + self.recovery_timeout_sec
        while True:
            try:
                records = self.consumer.poll(
                    timeout_ms=timeout_ms,
                    max_records=max_records,
                )
                break
            except Exception as exc:
                if not self._recoverable(exc) or time.monotonic() >= deadline:
                    raise
                self._recover(deadline=deadline)
        for partition, messages in records.items():
            for message in messages:
                self.next_offsets[partition] = int(message.offset) + 1
        return records

    def close(self) -> None:
        if self.consumer is not None:
            self.consumer.close()


def used_replay_camera_ids(kafka_bootstrap: str) -> set[int]:
    """Read canonical Kafka topic names before allocating this run's topic ids."""
    consumer = KafkaConsumer(
        bootstrap_servers=kafka_bootstrap,
        consumer_timeout_ms=1000,
        api_version_auto_timeout_ms=10000,
    )
    try:
        topic_pattern = re.compile(r"^uav_(?:statistics|track_complete|conflicts|telemetry)_(\\d+)$")
        return {
            int(match.group(1))
            for topic in consumer.topics()
            if (match := topic_pattern.fullmatch(topic))
        }
    finally:
        consumer.close()


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


def recognition_summary(messages: list[dict]) -> dict:
    """Aggregate detector/track coverage while keeping truth metrics explicit."""
    samples = 0
    samples_with_detections = 0
    detected_total = 0
    tracked_total = 0
    unassociated_total = 0
    invalid_geometry_total = 0
    small_target_max_area_px2 = None
    small_detected_total = 0
    small_tracked_total = 0
    yolo_classes: Counter[str] = Counter()
    track_classes: Counter[str] = Counter()
    small_yolo_classes: Counter[str] = Counter()
    small_track_classes: Counter[str] = Counter()
    for message in messages:
        diagnostics = (message.get("data") or {}).get("recognition_diagnostics")
        if not isinstance(diagnostics, dict):
            continue
        samples += 1
        detected = int(diagnostics.get("valid_yolo_detection_count") or 0)
        tracked = int(diagnostics.get("emitted_image_track_count") or 0)
        detected_total += detected
        tracked_total += tracked
        if detected > 0:
            samples_with_detections += 1
        unassociated_total += int(
            diagnostics.get("unassociated_detection_count")
            or max(detected - tracked, 0)
        )
        invalid_geometry_total += int(
            diagnostics.get("invalid_detector_geometry_count") or 0
        )
        threshold = diagnostics.get("small_target_max_area_px2")
        if threshold is not None:
            small_target_max_area_px2 = int(threshold)
        small_detected_total += int(
            diagnostics.get("small_yolo_detection_count") or 0
        )
        small_tracked_total += int(
            diagnostics.get("small_emitted_track_count") or 0
        )
        yolo_classes.update(diagnostics.get("yolo_class_counts") or {})
        track_classes.update(diagnostics.get("emitted_track_class_counts") or {})
        small_yolo_classes.update(diagnostics.get("small_yolo_class_counts") or {})
        small_track_classes.update(
            diagnostics.get("small_emitted_track_class_counts") or {}
        )
    return {
        "truth_status": "not_evaluated",
        "truth_reason": "approved_external_truth_unavailable",
        "samples": samples,
        "samples_with_detections": samples_with_detections,
        "detection_frame_coverage_ratio": round(
            samples_with_detections / samples, 4
        ) if samples else None,
        "valid_yolo_detections": detected_total,
        "emitted_image_tracks": tracked_total,
        "unassociated_detections": unassociated_total,
        "same_frame_track_to_detection_ratio": round(
            tracked_total / detected_total, 4
        ) if detected_total else None,
        "invalid_detector_geometry_count": invalid_geometry_total,
        "small_target_max_area_px2": small_target_max_area_px2,
        "small_yolo_detections": small_detected_total,
        "small_emitted_tracks": small_tracked_total,
        "small_track_to_detection_ratio": round(
            small_tracked_total / small_detected_total, 4
        ) if small_detected_total else None,
        "small_yolo_class_counts": dict(sorted(small_yolo_classes.items())),
        "small_emitted_track_class_counts": dict(
            sorted(small_track_classes.items())
        ),
        "yolo_class_counts": dict(sorted(yolo_classes.items())),
        "emitted_track_class_counts": dict(sorted(track_classes.items())),
        "formal_precision": "not_evaluated",
        "formal_recall": "not_evaluated",
    }


def lifecycle_summary(messages: list[dict]) -> dict:
    """Aggregate lifecycle continuity without treating observed IDs as truth."""
    samples = 0
    active_max = 0
    mature_max = 0
    candidate_max = 0
    completed_total = 0
    regression_max = 0
    termination_reasons: Counter[str] = Counter()
    for message in messages:
        tracking = (message.get("data") or {}).get("tracking_diagnostics")
        lifecycle = tracking.get("lifecycle") if isinstance(tracking, dict) else None
        if not isinstance(lifecycle, dict):
            continue
        samples += 1
        active_max = max(active_max, int(lifecycle.get("active_track_count") or 0))
        mature_max = max(mature_max, int(lifecycle.get("mature_track_count") or 0))
        candidate_max = max(
            candidate_max, int(lifecycle.get("candidate_track_count") or 0)
        )
        completed_total += int(lifecycle.get("completed_track_count") or 0)
        regression_max = max(
            regression_max,
            int(lifecycle.get("same_id_mature_to_candidate_count") or 0),
        )
        reason = lifecycle.get("termination_reason")
        if reason:
            termination_reasons[str(reason)] += 1
    return {
        "samples": samples,
        "active_track_count_max": active_max,
        "mature_track_count_max": mature_max,
        "candidate_track_count_max": candidate_max,
        "completed_track_count_total": completed_total,
        "same_id_mature_to_candidate_count": regression_max,
        "termination_reason_counts": dict(sorted(termination_reasons.items())),
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
        "class_unstable",
        "participant_not_fully_visible",
        "participant_not_currently_observed",
        "heading_unreliable",
        "general_crossing_angle_too_shallow",
        "nested_cross_class_detection",
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


def tcc_eligibility_summary(messages: list[dict]) -> dict:
    """Keep TCC world-quality coverage distinct from map-dependent analytics."""
    samples = len(messages)
    eligible = sum(bool((message.get("data") or {}).get("tcc_analytics_eligible")) for message in messages)
    reasons: Counter[str] = Counter()
    for message in messages:
        data = message.get("data") or {}
        if data.get("tcc_analytics_eligible"):
            continue
        quality = data.get("geo_reference_quality") or {}
        reasons.update(str(reason) for reason in quality.get("geo_reasons") or quality.get("reasons") or [])
    return {
        "samples": samples,
        "eligible_samples": eligible,
        "coverage_ratio": round(eligible / samples, 4) if samples else 0.0,
        "ineligible_reason_counts": dict(sorted(reasons.items())),
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


def road_context_leakage(result: dict) -> dict:
    """Verify a mapless replay did not invent Lane/Link business facts."""
    candidate = result.get("candidate_isolation") or {}
    return {
        "road_activity_frames": int(candidate.get("road_activity_frames") or 0),
        "lane_stats_frames": int(candidate.get("lane_stats_frames") or 0),
        "total": int(candidate.get("road_activity_frames") or 0)
        + int(candidate.get("lane_stats_frames") or 0),
    }


def source_result_passed(result: dict) -> bool:
    """Apply the per-source functional acceptance contract."""
    recognition = result.get("recognition")
    recognition_ok = True
    if isinstance(recognition, dict):
        recognition_ok = bool(
            int(recognition.get("samples") or 0) > 0
            and int(recognition.get("valid_yolo_detections") or 0) > 0
            and int(recognition.get("small_yolo_detections") or 0) > 0
            and int(recognition.get("invalid_detector_geometry_count") or 0) == 0
        )
    lifecycle = result.get("lifecycle")
    lifecycle_ok = True
    if isinstance(lifecycle, dict):
        lifecycle_ok = bool(
            int(lifecycle.get("samples") or 0) > 0
            and int(lifecycle.get("same_id_mature_to_candidate_count") or 0) == 0
        )
    base = bool(
        result.get("return_code") == 0
        and not result.get("error")
        and int(result.get("stats_count") or 0) > 0
        and not result.get("invalid_tcc_events")
        and int((result.get("tcc_diagnostics") or {}).get("samples") or 0) > 0
        and result.get("natural_eof", True)
        and (result.get("road9_reconciliation") or {"matched": True}).get("matched", False)
        and recognition_ok
        and lifecycle_ok
    )
    trajectory = result.get("trajectory_output")
    if trajectory is None:
        trajectory = {
            "eligible_completed_tracks": int(result.get("trajectory_count") or 0),
            "point_alignment_failures": 0,
        }
    isolation = result.get("candidate_isolation") or {}
    if result.get("acceptance_mode") in {"roadless_trajectory", "candidate_isolation"}:
        leakage = result.get("formal_business_leakage") or formal_business_leakage(result)
        return bool(
            base
            and int(isolation.get("active_formal_tracks_peak") or 0) > 0
            and int(isolation.get("candidate_point_alignment_failures") or 0) == 0
            and int(trajectory.get("eligible_completed_tracks") or 0) > 0
            and int(trajectory.get("point_alignment_failures") or 0) == 0
            and float(leakage.get("total") or 0) == 0
        )
    if result.get("acceptance_mode") == "geo_tcc_validation":
        quality = result.get("tcc_eligibility") or {}
        min_coverage = float(result.get("min_tcc_eligible_coverage") or 0.90)
        road_leakage = result.get("road_context_leakage") or road_context_leakage(result)
        return bool(
            base
            and int(isolation.get("active_formal_tracks_peak") or 0) > 0
            and int(isolation.get("candidate_point_alignment_failures") or 0) == 0
            and int(trajectory.get("eligible_completed_tracks") or 0) > 0
            and int(trajectory.get("point_alignment_failures") or 0) == 0
            and float(quality.get("coverage_ratio") or 0.0) >= min_coverage
            and int(road_leakage.get("total") or 0) == 0
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
        frame_stride: int | None = None,
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
                "frame_stride": frame_stride,
                "candidate_only": False,
            },
        )

    def stop(self, pipeline_id: str) -> None:
        self.request("DELETE", f"/api/v1/pipelines/{pipeline_id}")

    def stop_stale_reserved(self) -> list[str]:
        """Stop stale registrations owned by this serial replay runner."""
        stopped = []
        for pipeline in self.request("GET", "/api/v1/pipelines"):
            camera_id = int(pipeline.get("camera_id") or 0)
            video_port = int(pipeline.get("video_port") or 0)
            is_legacy_reserved = (
                LEGACY_RUNNER_CAMERA_ID_MIN <= camera_id <= LEGACY_RUNNER_CAMERA_ID_MAX
                and LEGACY_RUNNER_VIDEO_PORT_MIN <= video_port <= LEGACY_RUNNER_VIDEO_PORT_MAX
            )
            is_current_reserved = (
                RUNNER_CAMERA_ID_MIN <= camera_id <= RUNNER_CAMERA_ID_MAX
                and RUNNER_VIDEO_PORT_MIN <= video_port <= RUNNER_VIDEO_PORT_MIN + (RUNNER_CAMERA_ID_MAX - RUNNER_CAMERA_ID_MIN)
            )
            if (
                pipeline.get("status") == "running"
                and (is_legacy_reserved or is_current_reserved)
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
                "source_time_raw": payload.get("source_time_raw"),
                "data": {
                    "pipeline_id": data.get("pipeline_id"),
                    "source_profile_id": data.get("source_profile_id"),
                    "inference_ms": data.get("inference_ms"),
                    "pipeline_processing_ms": data.get("pipeline_processing_ms"),
                    "inference_context": data.get("inference_context"),
                    "recognition_diagnostics": data.get("recognition_diagnostics"),
                    "tracking_diagnostics": data.get("tracking_diagnostics"),
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
    timeout_sec: float = 180.0,
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
    expected = {
        key: _distinct_message_count(buckets[key])
        for key in ("stats", "tracks", "conflicts", "telemetry")
    }
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


def _distinct_message_count(messages: list[dict]) -> int:
    """Count canonical messages under Kafka's at-least-once delivery contract."""
    message_ids: set[str] = set()
    missing_message_id = 0
    for message in messages:
        message_id = message.get("message_id") if isinstance(message, dict) else None
        if isinstance(message_id, str) and message_id:
            message_ids.add(message_id)
        else:
            # A malformed capture must not disappear from reconciliation merely
            # because it cannot participate in canonical message-id deduplication.
            missing_message_id += 1
    return len(message_ids) + missing_message_id


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
        f"telemetry.agl_policy={source.get('telemetry_agl_policy', 'legacy_height')}",
    ]


def flight_motion_overrides(source: dict) -> list[str]:
    """Enable roll only for a source that opts into full-pose visual validation."""
    if not source.get("allow_roll_with_visual_validation", False):
        return []
    return [
        "flight_motion.allow_roll_with_visual_validation=true",
        "flight_motion.max_roll_visual_validation_deg="
        f"{source.get('max_roll_visual_validation_deg', 15.0)}",
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
    camera_id_base: int,
    video_port_base: int,
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
    camera_id = camera_id_base + index
    video_port = video_port_base + index
    configured_mode = source.get("acceptance_mode", "formal_world_trajectory")
    runtime_bundle = client.runtime_bundle(
        source,
        required=configured_mode not in {"roadless_trajectory", "candidate_isolation", "geo_tcc_validation"},
    )
    telemetry_enabled = source.get("telemetry_enabled", True)
    if not telemetry_enabled:
        runtime_bundle = None
    acceptance_mode = (
        "formal_world_trajectory" if runtime_bundle is not None
        else configured_mode
    )
    registered = client.register(
        source,
        camera_id,
        video_port,
        runtime_bundle,
        tracking_profile=tracking_profile,
        frame_stride=frame_stride,
    )
    pipeline_id = registered["pipeline_id"]
    run_id = f"native-mps-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{source['profile_id']}"
    topics = [
        f"uav_statistics_{camera_id}",
        f"uav_track_complete_{camera_id}",
        f"uav_conflicts_{camera_id}",
        f"uav_telemetry_{camera_id}",
    ]
    try:
        capture = RecoveringKafkaCapture(kafka_bootstrap, topics)
    except Exception:
        client.stop(pipeline_id)
        raise

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
    command.extend(flight_motion_overrides(source))
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
                for messages in capture.poll(timeout_ms=1000, max_records=1000).values():
                    for message in messages:
                        _capture_message(buckets, message, pipeline_id)
            return_code = process.returncode
            quiet_since = time.monotonic()
            final_deadline = quiet_since + drain_seconds
            while time.monotonic() < final_deadline:
                matched = False
                for messages in capture.poll(timeout_ms=500, max_records=1000).values():
                    for message in messages:
                        matched = _capture_message(buckets, message, pipeline_id) or matched
                if matched:
                    quiet_since = time.monotonic()
                    final_deadline = quiet_since + drain_seconds
    except BaseException as exc:  # Preserve artifacts and unregister even on an interactive interrupt.
        error = f"{type(exc).__name__}: {exc}"
    finally:
        terminate_process_tree(process)
        capture.close()
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
        "configured_acceptance_mode": configured_mode,
        "min_tcc_eligible_coverage": source.get("min_tcc_eligible_coverage"),
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
        "tcc_eligibility": tcc_eligibility_summary(buckets["stats"]),
        "candidate_isolation": candidate,
        "trajectory_output": trajectory_output,
        "eligible_completed_tracks": trajectory_output["eligible_completed_tracks"],
        "road9_reconciliation": road9,
        "performance": inference_summary(buckets["stats"]),
        "recognition": recognition_summary(buckets["stats"]),
        "lifecycle": lifecycle_summary(buckets["stats"]),
        "error": error,
        "capture_recovery_count": capture.recovery_count,
    }
    result["formal_business_leakage"] = formal_business_leakage(result)
    result["road_context_leakage"] = road_context_leakage(result)
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
    sampling = parser.add_mutually_exclusive_group()
    sampling.add_argument(
        "--frame-stride",
        type=int,
        default=3,
        help="process every Nth source frame (default: 3)",
    )
    sampling.add_argument(
        "--sample-fps",
        type=float,
        default=None,
        help="derive stride from a requested processed FPS instead",
    )
    parser.add_argument(
        "--imgsz",
        type=int,
        default=None,
        help="adaptive missing-telemetry fallback (default 960), or explicit fixed diagnostic size",
    )
    parser.add_argument(
        "--adaptive-imgsz",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="use production altitude-aware 640/960/1280 tiers (default enabled; --no-adaptive-imgsz is diagnostic-only)",
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
    parser.add_argument(
        "--camera-id-base",
        type=int,
        default=None,
        help="optional camera/topic base; omit to reserve unused Kafka topic ids",
    )
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--resume", action="store_true", help="reuse completed source artifacts")
    parser.add_argument("--skip-preflight", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.frame_stride is not None and args.frame_stride < 1:
        raise SystemExit("--frame-stride must be >= 1")
    if args.sample_fps is not None and args.sample_fps <= 0:
        raise SystemExit("--sample-fps must be > 0")
    catalog = source_catalog()
    selected = args.source or list(catalog)
    unknown = [profile_id for profile_id in selected if profile_id not in catalog]
    if unknown:
        raise SystemExit(f"unknown source profile(s): {', '.join(unknown)}")
    if args.camera_id_base is not None and (args.camera_id_base < 0 or args.camera_id_base + len(selected) > 65535):
        raise SystemExit("--camera-id-base must keep generated camera IDs in 1..65535")
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
    camera_id_base = args.camera_id_base
    if camera_id_base is None:
        camera_id_base = choose_runner_camera_id_base(
            used_replay_camera_ids(args.kafka_bootstrap), len(selected)
        )
    video_port_base = replay_video_port_base(camera_id_base)
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
        frame_stride = (
            max(1, int(round(input_fps / args.sample_fps)))
            if args.sample_fps is not None
            else args.frame_stride
        )
        try:
            validate_source_time_stride(frame_stride, input_fps)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        result = run_source(
            client,
            catalog[profile_id],
            index=index,
            camera_id_base=camera_id_base,
            video_port_base=video_port_base,
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
