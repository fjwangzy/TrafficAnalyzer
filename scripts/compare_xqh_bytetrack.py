#!/usr/bin/env python3
"""Compare the pre-gate ByteTrack baseline with the current tracker.

YOLO runs exactly once per sampled frame.  The resulting detections are then
fed to both trackers, so the report isolates association behavior from detector
variance.  This is an engineering regression without external identity truth;
it must not be reported as IDF1, HOTA, or formal ID-switch accuracy.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import types
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

import cv2
import numpy as np
import torch
import yaml
from ultralytics import YOLO


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from byte_tracker.byte_tracker_model import BYTETracker  # noqa: E402
from utils_local.detection_geometry import (  # noqa: E402
    configure_safe_mps_box_clipping,
    extract_valid_detections,
)
from utils_local.image_motion import (  # noqa: E402
    ImageMotionEstimator,
    ImageMotionObservation,
)


DEFAULT_VIDEO = (
    PROJECT_ROOT
    / "test_videos/inter_xqh/DJI_20260403142902_0001_V小清河北路与水屯路路口.mp4"
)
DEFAULT_BASELINE_COMMIT = "23252d662b49a9c2c08de24bb98f71d091e41f6c"
DEFAULT_CENTER_ROI = (1400.0, 450.0, 2400.0, 1650.0)


def _load_baseline_tracker(commit: str):
    try:
        source = subprocess.check_output(
            [
                "git",
                "show",
                f"{commit}:byte_tracker/byte_tracker_model.py",
            ],
            cwd=PROJECT_ROOT,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"cannot load ByteTrack baseline from commit {commit}"
        ) from exc
    module = types.ModuleType("xqh_bytetrack_baseline")
    exec(compile(source, "xqh_bytetrack_baseline.py", "exec"), module.__dict__)
    return module.BYTETracker


def _resolve_device(requested: str) -> torch.device:
    if requested != "auto":
        return torch.device(requested)
    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def _tracker_kwargs(config: dict) -> dict:
    tracking = config["tracking_node"]
    return {
        "fps": 30,
        "first_track_thresh": float(tracking["first_track_thresh"]),
        "second_track_thresh": float(tracking["second_track_thresh"]),
        "match_thresh": float(tracking["match_thresh"]),
        "track_buffer": int(tracking["track_buffer"]),
        "resize_width_height": 1,
    }


def _current_tracker(config: dict) -> BYTETracker:
    tracking = config["tracking_node"]
    non_motor_ids = {
        int(value)
        for value in config.get("vehicle_classification", {}).get(
            "non_motor_class_ids", [0, 1, 2, 6, 7, 9]
        )
    }
    next_track_id = 0

    def allocate_track_id() -> int:
        nonlocal next_track_id
        next_track_id += 1
        return next_track_id

    return BYTETracker(
        **_tracker_kwargs(config),
        max_lost_sec=float(tracking.get("max_lost_sec", 2.0)),
        track_id_allocator=allocate_track_id,
        class_group_resolver=lambda class_id: (
            "non_motor" if int(class_id) in non_motor_ids else "motor"
        ),
        class_switch_confirm_frames=int(
            tracking.get("class_switch_confirm_frames", 3)
        ),
        large_object_area_px2=(
            float(tracking["large_object_area_px2"])
            if tracking.get("large_object_area_px2") is not None
            else None
        ),
        large_object_init_thresh=(
            float(tracking["large_object_init_thresh"])
            if tracking.get("large_object_init_thresh") is not None
            else None
        ),
    )


def _motion_estimator(config: dict) -> ImageMotionEstimator:
    quality = config.get("geo_reference", {})
    tracking = config["tracking_node"]
    return ImageMotionEstimator(
        visual_max_width=quality.get("visual_max_width", 960),
        min_background_points=quality.get("min_background_points", 40),
        min_inlier_ratio=quality.get("min_inlier_ratio", 0.5),
        max_reprojection_p95_px=quality.get("max_reprojection_p95_px", 3.0),
        max_frame_gap_sec=tracking.get("max_frame_gap_sec", 0.5),
        forward_backward_max_error_px=quality.get(
            "forward_backward_max_error_px", 1.5
        ),
    )


def _empty_stats() -> dict:
    return {
        "observations": 0,
        "center_observations": 0,
        "track_observations": Counter(),
        "center_track_observations": Counter(),
    }


def _observe_tracks(stats: dict, tracks, roi: tuple[float, float, float, float]) -> None:
    x1, y1, x2, y2 = roi
    stats["observations"] += len(tracks)
    for track in tracks:
        track_id = int(track.track_id)
        box = np.asarray(track.tlbr, dtype=np.float64)
        center_x = float((box[0] + box[2]) / 2.0)
        center_y = float((box[1] + box[3]) / 2.0)
        stats["track_observations"][track_id] += 1
        if x1 <= center_x <= x2 and y1 <= center_y <= y2:
            stats["center_observations"] += 1
            stats["center_track_observations"][track_id] += 1


def _summarize(stats: dict, frame_count: int) -> dict:
    all_lifetimes = list(stats["track_observations"].values())
    center_lifetimes = list(stats["center_track_observations"].values())
    return {
        "mean_tracks_per_frame": round(stats["observations"] / frame_count, 3),
        "unique_track_ids": len(all_lifetimes),
        "median_observations_per_track": (
            float(statistics.median(all_lifetimes)) if all_lifetimes else 0.0
        ),
        "center_mean_tracks_per_frame": round(
            stats["center_observations"] / frame_count, 3
        ),
        "center_unique_track_ids": len(center_lifetimes),
        "center_median_observations_per_track": (
            float(statistics.median(center_lifetimes))
            if center_lifetimes
            else 0.0
        ),
    }


def run(args: argparse.Namespace) -> dict:
    config = yaml.safe_load(
        (PROJECT_ROOT / "configs/app_config.yaml").read_text(encoding="utf-8")
    )
    detection = config["detection_node"]
    device = _resolve_device(args.device)
    configure_safe_mps_box_clipping(device)
    model = YOLO(str(PROJECT_ROOT / detection["weight_pth"]), task="detect")
    half = bool(detection.get("half", False)) and device.type in {"mps", "cuda"}

    BaselineTracker = _load_baseline_tracker(args.baseline_commit)
    baseline = BaselineTracker(**_tracker_kwargs(config))
    current = _current_tracker(config)
    motion = _motion_estimator(config)
    stats = {"baseline": _empty_stats(), "current": _empty_stats()}
    shadow_rejected_pairs = 0
    shadow_stranded_tracks = 0
    warp_statuses: Counter[str] = Counter()
    detection_count = 0

    capture = cv2.VideoCapture(str(args.video))
    if not capture.isOpened():
        raise RuntimeError(f"cannot open video: {args.video}")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    capture.set(cv2.CAP_PROP_POS_MSEC, args.start_offset_sec * 1000.0)
    frame_count = 0
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        frame_num = int(capture.get(cv2.CAP_PROP_POS_FRAMES)) - 1
        timestamp = frame_num / fps
        if timestamp > args.end_offset_sec:
            break
        if frame_num % args.stride:
            continue

        result = model.predict(
            frame,
            imgsz=int(detection["imgsz"]),
            conf=float(detection["confidence"]),
            iou=float(detection["iou"]),
            classes=list(detection["classes_to_detect"]),
            device=device,
            half=half,
            agnostic_nms=False,
            verbose=False,
        )[0]
        validated = extract_valid_detections(
            result.boxes,
            class_names=model.names,
            frame_shape=frame.shape,
        )
        rows = np.asarray(
            [
                [*box, validated.confidences[index], validated.class_ids[index]]
                for index, box in enumerate(validated.xyxy)
            ],
            dtype=np.float32,
        ).reshape((-1, 6))
        detection_count += len(rows)

        observation = motion.observe(
            ImageMotionObservation(
                timestamp_sec=timestamp,
                frame_num=frame_num,
                frame_bgr=frame,
                detected_xyxy=tuple(tuple(map(float, row[:4])) for row in rows),
            )
        )
        warp_statuses[observation.status] += 1
        warp = (
            observation.previous_to_current_pixel_warp
            if observation.usable_for_tracking
            else None
        )

        baseline_tracks = baseline.update(torch.from_numpy(rows), xyxy=True)
        current_tracks = current.update(
            rows,
            xyxy=True,
            camera_warp=warp,
            timestamp=timestamp,
        )
        _observe_tracks(stats["baseline"], baseline_tracks, args.center_roi)
        _observe_tracks(stats["current"], current_tracks, args.center_roi)
        shadow_rejected_pairs += current.last_association_diagnostics[
            "would_reject_eligible_pair_count"
        ]
        shadow_stranded_tracks += current.last_association_diagnostics[
            "would_strand_track_count"
        ]
        frame_count += 1
        if args.progress_every and frame_count % args.progress_every == 0:
            print(
                f"processed={frame_count} source_timestamp={timestamp:.3f}",
                file=sys.stderr,
                flush=True,
            )
    capture.release()
    if frame_count == 0:
        raise RuntimeError("the requested source window produced no sampled frames")

    baseline_metrics = _summarize(stats["baseline"], frame_count)
    current_metrics = _summarize(stats["current"], frame_count)
    baseline_center_mean = baseline_metrics["center_mean_tracks_per_frame"]
    current_center_mean = current_metrics["center_mean_tracks_per_frame"]
    center_density_ratio = (
        current_center_mean / baseline_center_mean
        if baseline_center_mean > 0
        else 0.0
    )
    gates = {
        "center_track_density_gte_95pct_of_same_detection_baseline": (
            center_density_ratio >= 0.95
        ),
        "center_unique_track_ids_lte_80": (
            current_metrics["center_unique_track_ids"] <= 80
        ),
        "center_median_observations_per_track_gte_30": (
            current_metrics["center_median_observations_per_track"] >= 30
        ),
    }
    return {
        "schema_version": "uav.xqh-bytetrack-regression/v1",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "result": {
            "engineering_passed": all(gates.values()),
            "production_accuracy": "not_evaluated_no_external_ground_truth",
            "gate_results": gates,
        },
        "source": {
            "video": str(args.video.resolve()),
            "start_offset_sec": args.start_offset_sec,
            "end_offset_sec": args.end_offset_sec,
            "source_fps": round(fps, 6),
            "stride": args.stride,
            "processed_frames": frame_count,
            "center_roi_xyxy": list(args.center_roi),
        },
        "detector": {
            "execution_count_per_sampled_frame": 1,
            "total_detections": detection_count,
            "mean_detections_per_frame": round(detection_count / frame_count, 3),
            "weight": detection["weight_pth"],
            "imgsz": detection["imgsz"],
            "confidence": detection["confidence"],
            "device": str(device),
            "half": half,
        },
        "association": {
            "baseline_commit": args.baseline_commit,
            "baseline": baseline_metrics,
            "current": current_metrics,
            "current_over_baseline_center_track_density": round(
                center_density_ratio, 6
            ),
            "mahalanobis_shadow": {
                "would_reject_eligible_pair_count": shadow_rejected_pairs,
                "would_strand_track_count": shadow_stranded_tracks,
            },
            "camera_motion_status_counts": dict(warp_statuses),
        },
        "non_claims": ["IDF1", "HOTA", "formal ID switch", "position RMSE", "speed MAE"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument("--start-offset-sec", type=float, default=400.0)
    parser.add_argument("--end-offset-sec", type=float, default=430.0)
    parser.add_argument("--stride", type=int, default=5)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--baseline-commit", default=DEFAULT_BASELINE_COMMIT)
    parser.add_argument("--center-roi", type=float, nargs=4, default=DEFAULT_CENTER_ROI)
    parser.add_argument("--progress-every", type=int, default=30)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--allow-gate-failure", action="store_true")
    args = parser.parse_args()
    if args.stride < 1:
        parser.error("--stride must be >= 1")
    if args.start_offset_sec >= args.end_offset_sec:
        parser.error("--start-offset-sec must precede --end-offset-sec")
    if not args.video.is_file():
        parser.error("--video must point to an existing file")
    args.center_roi = tuple(args.center_roi)

    report = run(args)
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    else:
        print(encoded)
    if not report["result"]["engineering_passed"] and not args.allow_gate_failure:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
