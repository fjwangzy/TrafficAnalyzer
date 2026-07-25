"""Production-gate evaluation for image-associated UAV ground tracking.

The evaluator consumes explicit frame-level ground truth and predictions.  It
uses ENU distance for frame association, global identity assignment for IDF1,
and the HOTA definition over a position-similarity curve.  Candidate/degraded
predictions are retained for leak detection but never silently counted as
verified output.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from math import sqrt
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import linear_sum_assignment

from utils_local.cruise_acceptance_package import (
    audit_cruise_acceptance_package,
)


SPEED_BANDS = ((0, 3), (3, 6), (6, 9), (9, 12))
AGL_BANDS = ((60, 90), (90, 120), (120, 150))


def _point(item: dict[str, Any]) -> np.ndarray | None:
    value = item.get("enu_m")
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    point = np.asarray(value[:2], dtype=np.float64)
    return point if np.isfinite(point).all() else None


def _percentile(values: list[float], percentile: float) -> float | None:
    return round(float(np.percentile(values, percentile)), 4) if values else None


def _band_label(value: float | None, bands) -> str:
    if value is None:
        return "unknown"
    for lower, upper in bands:
        if lower <= value < upper or (value == upper and upper == bands[-1][1]):
            return f"{lower}-{upper}"
    return "out_of_range"


def _frame_assignment(frame: dict[str, Any], similarity_threshold: float, radius_m: float):
    ground_truth = frame.get("ground_truth") or []
    predictions = frame.get("predictions") or []
    if not ground_truth or not predictions:
        return [], len(ground_truth), len(predictions)
    distances = np.full((len(ground_truth), len(predictions)), np.inf, dtype=np.float64)
    similarities = np.zeros_like(distances)
    for gt_index, gt in enumerate(ground_truth):
        gt_point = _point(gt)
        if gt_point is None:
            continue
        for pred_index, prediction in enumerate(predictions):
            pred_point = _point(prediction)
            if pred_point is None:
                continue
            distance = float(np.linalg.norm(gt_point - pred_point))
            distances[gt_index, pred_index] = distance
            similarities[gt_index, pred_index] = max(0.0, 1.0 - distance / radius_m)
    rows, columns = linear_sum_assignment(-similarities)
    matches = [
        (row, column, float(distances[row, column]))
        for row, column in zip(rows, columns)
        if similarities[row, column] >= similarity_threshold
    ]
    return matches, len(ground_truth) - len(matches), len(predictions) - len(matches)


def _hota(frames: list[dict[str, Any]], radius_m: float) -> float:
    gt_detection_counts = Counter()
    pred_detection_counts = Counter()
    for frame in frames:
        mission = str(frame.get("mission_id") or "unknown")
        gt_detection_counts.update((mission, str(item.get("track_id"))) for item in frame.get("ground_truth") or [])
        pred_detection_counts.update((mission, str(item.get("track_id"))) for item in frame.get("predictions") or [])

    hota_values = []
    for alpha in np.arange(0.05, 1.0, 0.05):
        pair_counts = Counter()
        tp = fp = fn = 0
        for frame in frames:
            matches, frame_fn, frame_fp = _frame_assignment(frame, float(alpha), radius_m)
            mission = str(frame.get("mission_id") or "unknown")
            ground_truth = frame.get("ground_truth") or []
            predictions = frame.get("predictions") or []
            tp += len(matches)
            fn += frame_fn
            fp += frame_fp
            for gt_index, pred_index, _ in matches:
                pair_counts[(
                    mission,
                    str(ground_truth[gt_index].get("track_id")),
                    str(predictions[pred_index].get("track_id")),
                )] += 1
        detection_accuracy = tp / max(tp + fp + fn, 1)
        association_total = 0.0
        for (mission, gt_id, pred_id), pair_count in pair_counts.items():
            union = (
                gt_detection_counts[(mission, gt_id)]
                + pred_detection_counts[(mission, pred_id)]
                - pair_count
            )
            association_total += pair_count * pair_count / max(union, 1)
        association_accuracy = association_total / max(tp, 1)
        hota_values.append(sqrt(detection_accuracy * association_accuracy))
    return round(float(np.mean(hota_values)), 4) if hota_values else 0.0


def _idf1(pair_counts: Counter, total_gt: int, total_pred: int) -> float:
    gt_ids = sorted({pair[0:2] for pair in pair_counts})
    pred_ids = sorted({(pair[0], pair[2]) for pair in pair_counts})
    if not gt_ids or not pred_ids:
        return 0.0
    gt_index = {value: index for index, value in enumerate(gt_ids)}
    pred_index = {value: index for index, value in enumerate(pred_ids)}
    counts = np.zeros((len(gt_ids), len(pred_ids)), dtype=np.float64)
    for (mission, gt_id, pred_id), count in pair_counts.items():
        counts[gt_index[(mission, gt_id)], pred_index[(mission, pred_id)]] = count
    rows, columns = linear_sum_assignment(-counts)
    identity_tp = int(sum(counts[row, column] for row, column in zip(rows, columns)))
    return round(2 * identity_tp / max(total_gt + total_pred, 1), 4)


def evaluate_cruise_dataset(
    dataset: dict[str, Any],
    match_radius_m: float = 3.0,
    asset_root: Path | None = None,
) -> dict[str, Any]:
    if dataset.get("schema_version") != "uav.cruise-eval/v1":
        raise ValueError("dataset schema_version must be uav.cruise-eval/v1")
    frames = sorted(
        list(dataset.get("frames") or []),
        key=lambda item: (str(item.get("mission_id")), float(item.get("timestamp_sec", 0))),
    )
    pair_counts = Counter()
    position_errors: list[float] = []
    speed_errors: list[float] = []
    lane_correct = 0
    lane_total = 0
    total_gt = total_pred = 0
    last_prediction_by_gt: dict[tuple[str, str], str] = {}
    id_switches = 0
    quality_leaks = 0
    gt_times: dict[tuple[str, str], list[float]] = defaultdict(list)
    track_speed_samples: dict[tuple[str, str], list[float]] = defaultdict(list)
    track_agl_samples: dict[tuple[str, str], list[float]] = defaultdict(list)
    band_pair_counts: dict[str, Counter] = defaultdict(Counter)
    band_gt_counts = Counter()
    band_pred_counts = Counter()

    for frame in frames:
        mission = str(frame.get("mission_id") or "unknown")
        agl_m = float(frame["agl_m"]) if frame.get("agl_m") is not None else None
        uav_ground_speed_mps = (
            float(frame["uav_ground_speed_mps"])
            if frame.get("uav_ground_speed_mps") is not None
            else None
        )
        for gt in frame.get("ground_truth") or []:
            gt_key = (mission, str(gt.get("track_id")))
            if uav_ground_speed_mps is not None:
                track_speed_samples[gt_key].append(uav_ground_speed_mps)
            if agl_m is not None:
                track_agl_samples[gt_key].append(agl_m)
    track_speed_band = {
        key: _band_label(float(np.median(values)) if values else None, SPEED_BANDS)
        for key, values in track_speed_samples.items()
    }
    track_agl_band = {
        key: _band_label(float(np.median(values)) if values else None, AGL_BANDS)
        for key, values in track_agl_samples.items()
    }

    for frame in frames:
        mission = str(frame.get("mission_id") or "unknown")
        timestamp = float(frame.get("timestamp_sec", 0))
        ground_truth = frame.get("ground_truth") or []
        predictions = frame.get("predictions") or []
        total_gt += len(ground_truth)
        total_pred += len(predictions)
        quality_leaks += sum(
            1 for item in predictions
            if item.get("formal_analytics_eligible") is True
            and item.get("quality_status") in {"degraded", "unverified"}
        )
        matches, _, _ = _frame_assignment(frame, 0.000001, match_radius_m)
        for gt in ground_truth:
            gt_id = (mission, str(gt.get("track_id")))
            gt_times[gt_id].append(timestamp)
            band_gt_counts[track_speed_band.get(gt_id, "unknown")] += 1
        frame_uav_speed_mps = (
            float(frame["uav_ground_speed_mps"])
            if frame.get("uav_ground_speed_mps") is not None
            else None
        )
        for _prediction in predictions:
            band_pred_counts[
                _band_label(frame_uav_speed_mps, SPEED_BANDS)
            ] += 1
        for gt_index, pred_index, distance in matches:
            gt = ground_truth[gt_index]
            prediction = predictions[pred_index]
            gt_id = str(gt.get("track_id"))
            pred_id = str(prediction.get("track_id"))
            pair = (mission, gt_id, pred_id)
            pair_counts[pair] += 1
            band = track_speed_band.get((mission, gt_id), "unknown")
            band_pair_counts[band][pair] += 1
            position_errors.append(distance)
            previous = last_prediction_by_gt.get((mission, gt_id))
            if previous is not None and previous != pred_id:
                id_switches += 1
            last_prediction_by_gt[(mission, gt_id)] = pred_id
            if gt.get("speed_kmh") is not None and prediction.get("speed_kmh") is not None:
                speed_errors.append(abs(float(gt["speed_kmh"]) - float(prediction["speed_kmh"])))
            if gt.get("lane_id") is not None:
                lane_total += 1
                lane_correct += int(str(gt.get("lane_id")) == str(prediction.get("lane_id")))

    gt_track_minutes = sum(
        max(times) - min(times) for times in gt_times.values() if times
    ) / 60.0
    unique_speed_tracks = Counter(track_speed_band.values())
    unique_agl_tracks = Counter(track_agl_band.values())
    metrics = {
        "idf1": _idf1(pair_counts, total_gt, total_pred),
        "hota": _hota(frames, match_radius_m),
        "id_switches": id_switches,
        "id_switches_per_100_track_min": round(id_switches / max(gt_track_minutes, 1e-9) * 100, 4),
        "position_rmse_m": round(sqrt(float(np.mean(np.square(position_errors)))), 4) if position_errors else None,
        "position_p95_m": _percentile(position_errors, 95),
        "speed_mae_kmh": round(float(np.mean(speed_errors)), 4) if speed_errors else None,
        "speed_p95_kmh": _percentile(speed_errors, 95),
        "lane_accuracy": round(lane_correct / lane_total, 4) if lane_total else None,
        "lane_reviewed_points": lane_total,
        "quality_leak_count": quality_leaks,
        "idf1_by_speed_band": {
            band: _idf1(
                counts,
                band_gt_counts[band],
                band_pred_counts[band],
            )
            for band, counts in sorted(band_pair_counts.items())
        },
    }

    intersections = {str(frame.get("intersection_id")) for frame in frames if frame.get("intersection_id")}
    missions_by_intersection: dict[str, set[str]] = defaultdict(set)
    for frame in frames:
        if frame.get("intersection_id") and frame.get("mission_id"):
            missions_by_intersection[str(frame["intersection_id"])].add(str(frame["mission_id"]))
    evidence_audit = audit_cruise_acceptance_package(
        dataset, asset_root=asset_root
    )
    failures = list(evidence_audit["failures"])
    if len(intersections) < 3:
        failures.append("dataset_intersections_below_3")
    if any(len(missions_by_intersection[item]) < 2 for item in intersections) or not intersections:
        failures.append("dataset_missions_per_intersection_below_2")
    for lower, upper in SPEED_BANDS:
        if unique_speed_tracks[f"{lower}-{upper}"] < 100:
            failures.append(f"dataset_speed_band_{lower}_{upper}_tracks_below_100")
    for lower, upper in AGL_BANDS:
        if unique_agl_tracks[f"{lower}-{upper}"] < 100:
            failures.append(f"dataset_agl_band_{lower}_{upper}_tracks_below_100")

    def require_max(name: str, threshold: float, failure: str):
        value = metrics.get(name)
        if value is None or value > threshold:
            failures.append(failure)

    def require_min(name: str, threshold: float, failure: str):
        value = metrics.get(name)
        if value is None or value < threshold:
            failures.append(failure)

    require_min("idf1", 0.85, "idf1_below_0_85")
    require_min("hota", 0.65, "hota_below_0_65")
    require_max("id_switches_per_100_track_min", 2.0, "id_switch_rate_above_2")
    require_max("position_rmse_m", 1.5, "position_rmse_above_1_5m")
    require_max("position_p95_m", 3.0, "position_p95_above_3m")
    require_max("speed_mae_kmh", 3.0, "speed_mae_above_3kmh")
    require_max("speed_p95_kmh", 6.0, "speed_p95_above_6kmh")
    require_min("lane_accuracy", 0.95, "lane_accuracy_below_0_95")
    if lane_total < 100:
        failures.append("lane_reviewed_points_below_100")
    if quality_leaks:
        failures.append("degraded_formal_leak_nonzero")
    for lower, upper in SPEED_BANDS:
        value = metrics["idf1_by_speed_band"].get(f"{lower}-{upper}")
        if value is None or value < 0.80:
            failures.append(f"idf1_speed_band_{lower}_{upper}_below_0_80")

    quality_summary = dataset.get("quality_summary") or {}
    required_quality = {
        "telemetry_coverage_ratio": (0.95, "min"),
        "sync_error_p95_sec": (0.1, "max"),
        "visual_valid_ratio": (0.95, "min"),
        "visual_reprojection_p95_px": (3.0, "max"),
    }
    for field, (threshold, direction) in required_quality.items():
        value = quality_summary.get(field)
        if value is None:
            failures.append(f"{field}_missing")
        elif (direction == "min" and value < threshold) or (direction == "max" and value > threshold):
            failures.append(f"{field}_gate_failed")
    regression = dataset.get("hover_regression") or {}
    if regression.get("idf1_drop_points") is None or regression.get("position_rmse_increase_m") is None:
        failures.append("hover_regression_evidence_missing")
    else:
        if regression["idf1_drop_points"] > 0.01:
            failures.append("hover_idf1_regression_above_1_point")
        if regression["position_rmse_increase_m"] > 0.2:
            failures.append("hover_position_regression_above_0_2m")

    return {
        "schema_version": "uav.cruise-eval-report/v1",
        "dataset": {
            "frame_count": len(frames),
            "intersection_count": len(intersections),
            "mission_count": len({str(frame.get("mission_id")) for frame in frames}),
            "ground_truth_track_count": len(gt_times),
            "speed_band_tracks": dict(unique_speed_tracks),
            "agl_band_tracks": dict(unique_agl_tracks),
        },
        "metrics": metrics,
        "evidence_audit": evidence_audit,
        "gate": {
            "status": "production_signoff_passed" if not failures else "production_signoff_blocked",
            "failures": list(dict.fromkeys(failures)),
        },
    }
