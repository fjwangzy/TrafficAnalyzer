"""Pure evaluation of detector-to-tracker engineering coverage.

The ratios in this module compare same-frame detector and tracker output counts.
They are operational coverage signals, not accuracy metrics: without approved
external truth they cannot be interpreted as precision, recall, IDF1, or HOTA.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
import math
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = "uav.detection-tracking-evaluation/v1"
_QUANTILES = {"p05": 0.05, "p25": 0.25, "p50": 0.5, "p75": 0.75, "p95": 0.95}


def _payload(message: Mapping[str, Any]) -> Mapping[str, Any]:
    data = message.get("data")
    return data if isinstance(data, Mapping) else message


def _ratio(emitted: int, detected: int) -> float | None:
    if detected <= 0:
        return None
    return round(emitted / detected, 4)


def _counts(detected: int, emitted: int) -> dict[str, int | float | None]:
    return {
        "detected": int(detected),
        "emitted": int(emitted),
        "ratio": _ratio(emitted, detected),
    }


def _quantile(values: Sequence[float], position: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    index = (len(ordered) - 1) * position
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return round(ordered[lower], 4)
    weight = index - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 4)


def _quantiles(values: Sequence[float]) -> dict[str, float | None]:
    result = {
        name: _quantile(values, position) for name, position in _QUANTILES.items()
    }
    result["min"] = round(min(values), 4) if values else None
    result["max"] = round(max(values), 4) if values else None
    return result


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _class_conversion(
    detected: Mapping[str, int], emitted: Mapping[str, int]
) -> dict[str, dict[str, int | float | None]]:
    return {
        class_name: _counts(
            int(detected.get(class_name, 0)), int(emitted.get(class_name, 0))
        )
        for class_name in sorted(set(detected) | set(emitted))
    }


def _aggregate_diagnostics(
    diagnostics: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    detected = 0
    emitted = 0
    small_detected = 0
    small_emitted = 0
    invalid_geometry = 0
    detected_classes: Counter[str] = Counter()
    emitted_classes: Counter[str] = Counter()
    small_detected_classes: Counter[str] = Counter()
    small_emitted_classes: Counter[str] = Counter()
    frame_ratios: list[float] = []
    small_frame_ratios: list[float] = []

    for diagnostic in diagnostics:
        frame_detected = int(diagnostic.get("valid_yolo_detection_count", 0) or 0)
        frame_emitted = int(diagnostic.get("emitted_image_track_count", 0) or 0)
        frame_small_detected = int(
            diagnostic.get("small_yolo_detection_count", 0) or 0
        )
        frame_small_emitted = int(
            diagnostic.get("small_emitted_track_count", 0) or 0
        )
        detected += frame_detected
        emitted += frame_emitted
        small_detected += frame_small_detected
        small_emitted += frame_small_emitted
        invalid_geometry += int(
            diagnostic.get("invalid_detector_geometry_count", 0) or 0
        )
        detected_classes.update(diagnostic.get("yolo_class_counts") or {})
        emitted_classes.update(diagnostic.get("emitted_track_class_counts") or {})
        small_detected_classes.update(
            diagnostic.get("small_yolo_class_counts") or {}
        )
        small_emitted_classes.update(
            diagnostic.get("small_emitted_track_class_counts") or {}
        )
        if frame_detected > 0:
            frame_ratios.append(frame_emitted / frame_detected)
        if frame_small_detected > 0:
            small_frame_ratios.append(frame_small_emitted / frame_small_detected)

    return {
        "overall": _counts(detected, emitted),
        "small_targets": _counts(small_detected, small_emitted),
        "by_class": _class_conversion(detected_classes, emitted_classes),
        "small_targets_by_class": _class_conversion(
            small_detected_classes, small_emitted_classes
        ),
        "frame_ratio_quantiles": _quantiles(frame_ratios),
        "small_frame_ratio_quantiles": _quantiles(small_frame_ratios),
        "invalid_detector_geometry_count": invalid_geometry,
    }


def _duration_band(duration: float) -> str:
    if duration < 2:
        return "lt_2s"
    if duration < 3:
        return "2_to_3s"
    if duration < 5:
        return "3_to_5s"
    if duration < 10:
        return "5_to_10s"
    if duration < 30:
        return "10_to_30s"
    return "30s_plus"


def _track_lifetimes(track_messages: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    durations: list[float] = []
    observation_counts: list[float] = []
    serialized_point_counts: list[float] = []
    classes: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    bands: Counter[str] = Counter()
    numeric_class_name_count = 0
    for message in track_messages:
        track = _payload(message)
        duration = float(track.get("duration_sec", 0) or 0)
        serialized_point_count = len(track.get("trajectory_px") or [])
        observation_count = track.get("trajectory_length")
        if observation_count is None:
            observation_count = serialized_point_count
        class_name = str(track.get("yolo_class_name") or "unknown")
        reason = str(track.get("termination_reason") or "missing")
        durations.append(duration)
        observation_counts.append(float(observation_count or 0))
        serialized_point_counts.append(float(serialized_point_count))
        classes[class_name] += 1
        reasons[reason] += 1
        bands[_duration_band(duration)] += 1
        if class_name.isdigit():
            numeric_class_name_count += 1

    band_names = ("lt_2s", "2_to_3s", "3_to_5s", "5_to_10s", "10_to_30s", "30s_plus")
    return {
        "track_count": len(track_messages),
        "duration_sec_quantiles": _quantiles(durations),
        "observation_count_quantiles": _quantiles(observation_counts),
        "serialized_point_count_quantiles": _quantiles(serialized_point_counts),
        "duration_bands": {name: bands[name] for name in band_names},
        "class_counts": dict(sorted(classes.items())),
        "termination_reason_counts": dict(sorted(reasons.items())),
        "numeric_class_name_count": numeric_class_name_count,
    }


def evaluate_detection_tracking(
    stats_messages: Sequence[Mapping[str, Any]],
    track_messages: Sequence[Mapping[str, Any]],
    *,
    lifecycle_audit: Mapping[str, Any] | None = None,
    segments: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Evaluate engineering coverage from already-captured production messages."""

    timed_diagnostics: list[tuple[float, Mapping[str, Any]]] = []
    diagnostic_messages: list[Mapping[str, Any]] = []
    timestamps = [_timestamp(message.get("occurred_at")) for message in stats_messages]
    valid_timestamps = [value for value in timestamps if value is not None]
    origin = min(valid_timestamps) if valid_timestamps else None

    for message, occurred_at in zip(stats_messages, timestamps):
        diagnostic = _payload(message).get("recognition_diagnostics")
        if not isinstance(diagnostic, Mapping):
            continue
        diagnostic_messages.append(diagnostic)
        if origin is not None and occurred_at is not None:
            timed_diagnostics.append(((occurred_at - origin).total_seconds(), diagnostic))

    conversion = _aggregate_diagnostics(diagnostic_messages)
    segment_results: dict[str, Any] = {}
    for segment in segments or []:
        name = str(segment["name"])
        start = float(segment["start_sec"])
        end = float(segment["end_sec"])
        selected = [
            diagnostic
            for offset, diagnostic in timed_diagnostics
            if start <= offset < end
        ]
        aggregate = _aggregate_diagnostics(selected)
        segment_results[name] = {
            "start_sec": start,
            "end_sec": end,
            "diagnostic_frame_count": len(selected),
            "overall": aggregate["overall"],
            "small_targets": aggregate["small_targets"],
            "by_class": aggregate["by_class"],
            "small_targets_by_class": aggregate["small_targets_by_class"],
        }

    track_lifetimes = _track_lifetimes(track_messages)
    numeric_emitted_class_labels = {
        class_name: metrics["emitted"]
        for class_name, metrics in conversion["by_class"].items()
        if class_name.isdigit() and metrics["emitted"]
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "methodology": {
            "conversion_metric": "same_frame_tracker_output_count_divided_by_valid_yolo_detection_count",
            "warning": "engineering_coverage_not_accuracy_or_detection_association_lineage",
            "small_target_definition": "bbox_area_px2_lte_diagnostic_threshold",
        },
        "truth_metrics": {
            "status": "not_evaluated",
            "reason": "approved_external_truth_unavailable",
            "precision": None,
            "recall": None,
            "idf1": None,
            "hota": None,
            "formal_id_switches": None,
        },
        "coverage": {
            "stats_message_count": len(stats_messages),
            "diagnostic_frame_count": len(diagnostic_messages),
            "diagnostic_frame_ratio": _ratio(
                len(diagnostic_messages), len(stats_messages)
            ),
            "invalid_detector_geometry_count": conversion.pop(
                "invalid_detector_geometry_count"
            ),
            "source_time_origin": origin.isoformat() if origin is not None else None,
        },
        "data_quality": {
            "numeric_emitted_class_label_count": sum(
                numeric_emitted_class_labels.values()
            ),
            "numeric_emitted_class_labels": numeric_emitted_class_labels,
            "numeric_completed_class_label_count": track_lifetimes[
                "numeric_class_name_count"
            ],
        },
        "conversion": conversion,
        "segments": segment_results,
        "track_lifetimes": track_lifetimes,
        "lifecycle_audit": dict(lifecycle_audit or {}),
    }
