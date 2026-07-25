"""Run a reproducible detector/tracker acceptance on the xqh hover/departure tail.

This is an engineering acceptance, not a substitute for the annotated IDF1/HOTA
production dataset.  It proves the real MP4+SRT path, MPS inference, flight-phase
transition, image-motion ByteTrack placement, quality isolation, and natural EOF.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import math
import os
import platform
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np
import torch
from omegaconf import OmegaConf
from ultralytics.utils import LOGGER as ULTRALYTICS_LOGGER


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLATFORM_DIR = PROJECT_ROOT / "platform"
for path in (PROJECT_ROOT, PLATFORM_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from elements.FrameElement import FrameElement  # noqa: E402
from elements.VideoEndBreakElement import VideoEndBreakElement  # noqa: E402
from nodes.AutoLaneInferenceNode import AutoLaneInferenceNode  # noqa: E402
from nodes.CalcStatisticsNode import CalcStatisticsNode  # noqa: E402
from nodes.ConflictDetectionNode import ConflictDetectionNode  # noqa: E402
from nodes.DetectionNode import DetectionNode  # noqa: E402
from nodes.DirectionFlowNode import DirectionFlowNode  # noqa: E402
from nodes.FlightGeoReferenceNode import FlightGeoReferenceNode  # noqa: E402
from nodes.GroundTrajectoryTrackerNode import GroundTrajectoryTrackerNode  # noqa: E402
from nodes.HomographyCalibrationNode import HomographyCalibrationNode  # noqa: E402
from nodes.ImageMotionEstimationNode import ImageMotionEstimationNode  # noqa: E402
from nodes.LaneAnalysisNode import LaneAnalysisNode  # noqa: E402
from nodes.LaneDetectionNode import LaneDetectionNode  # noqa: E402
from nodes.MotionCompensationNode import MotionCompensationNode  # noqa: E402
from nodes.PostTrackingWorldProjectionNode import PostTrackingWorldProjectionNode  # noqa: E402
from nodes.RoadMapMatchingNode import RoadMapMatchingNode  # noqa: E402
from nodes.ShowNode import ShowNode  # noqa: E402
from nodes.SpeedEstimationNode import SpeedEstimationNode  # noqa: E402
from nodes.TrackerInfoUpdateNode import TrackerInfoUpdateNode  # noqa: E402
from nodes.TrajectoryNode import TrajectoryNode  # noqa: E402
from services.SrtTelemetryParser import SrtTelemetryParser  # noqa: E402
DEFAULT_VIDEO = (
    PROJECT_ROOT
    / "test_videos/inter_xqh/DJI_20260403142902_0001_V小清河北路与水屯路路口.mp4"
)
DEFAULT_SRT = PROJECT_ROOT / "test_videos/inter_xqh/telemetry.srt"
DEFAULT_INTER_ID = "011wwe0z19700001"
DEFAULT_MAP_ID = "CMV-b83a25740598430bb996f75d"
DEFAULT_SOURCE_PROFILE_ID = "SRC-INTER-XQH-0403-PM"


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    return round(float(np.percentile(values, percentile)), 3)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


async def _load_runtime_bundle(inter_id: str, map_version_id: str) -> dict:
    from app.core.database import async_session_maker, close_db
    from app.models.mission import ChannelizedMapVersion
    from app.services.road_context import Road9RoadContextAdapter

    try:
        async with async_session_maker() as session:
            channelized_map = await session.get(ChannelizedMapVersion, map_version_id)
            if channelized_map is None:
                raise RuntimeError(f"map not found: {map_version_id}")
            road_data_version = channelized_map.road_data_version
        result = await Road9RoadContextAdapter(async_session_maker).get(
            inter_id, road_data_version
        )
        if result is None or result.map_version_id != map_version_id:
            raise RuntimeError("requested lane_verified map is not the active road context")
        bundle = result.runtime_map_bundle or {}
        registration = bundle.get("visual_registration") or {}
        for key in (
            "registration_pose",
            "camera_calibration",
            "map_coverage_enu_m",
        ):
            if not registration.get(key):
                raise RuntimeError(f"runtime registration is missing {key}")
        return bundle
    finally:
        await close_db()


def _load_config(
    *,
    video: Path,
    srt: Path,
    source_profile_id: str,
    bundle: dict,
    device: str,
    stride: int,
    shadow_report: Path,
) -> dict:
    os.environ.update(
        {
            "VIDEO_SRC": str(video),
            "TOPIC_NAME": "uav_statistics_xqh_acceptance",
            "CAMERA_ID": "991",
            "SOURCE_PROFILE_ID": source_profile_id,
            "FRAME_STRIDE": str(stride),
        }
    )
    config = OmegaConf.to_container(
        OmegaConf.load(PROJECT_ROOT / "configs/app_config.yaml"),
        resolve=True,
    )
    assert isinstance(config, dict)
    config["pipeline"] = {
        "save_video": False,
        "show_in_web": False,
        "send_info_kafka": False,
    }
    config["tracking_profile"] = "hover_cruise_v1"
    config["telemetry"].update(
        {
            "enabled": True,
            "source": "srt",
            "file_path": str(srt),
            "sync_tolerance_sec": 0.1,
            "time_offset_sec": 0.0,
        }
    )
    config["detection_node"]["device"] = device
    config["video_reader"]["frame_stride"] = stride
    config["road_map_matching"]["runtime_map_bundle"] = bundle
    config["tracking_shadow"].update(
        {
            "enabled": True,
            "offline_only": True,
            "report_path": str(shadow_report),
        }
    )
    config["lane_detection"]["enabled"] = False
    return config


def _append_segment(
    segments: list[dict],
    *,
    timestamp: float,
    value: object,
    key: str,
) -> None:
    if not segments or segments[-1][key] != value:
        segments.append(
            {
                "start_offset_sec": round(timestamp, 3),
                "end_offset_sec": round(timestamp, 3),
                key: value,
            }
        )
    else:
        segments[-1]["end_offset_sec"] = round(timestamp, 3)


def _track_lengths_aligned(track: object) -> bool:
    px = list(getattr(track, "ground_contact_points_px", []) or [])
    center = list(getattr(track, "trajectory_points", []) or [])
    enu = list(getattr(track, "trajectory_enu_m", []) or [])
    gcj = list(getattr(track, "trajectory_gcj02", []) or [])
    timestamps = list(getattr(track, "trajectory_timestamps_sec", []) or [])
    frame_nums = list(getattr(track, "trajectory_frame_nums", []) or [])
    return bool(px) and len(px) == len(center) == len(enu) == len(gcj) == len(timestamps) == len(frame_nums)


def _completed_lengths_aligned(track: dict) -> bool:
    px = track.get("trajectory_px") or []
    center = track.get("trajectory_bbox_center_px") or []
    enu = track.get("trajectory_enu_m") or []
    gcj = track.get("trajectory_gcj02") or []
    timestamps = track.get("trajectory_timestamps_sec") or []
    frame_nums = track.get("trajectory_frame_nums") or []
    return bool(px) and len(px) == len(center) == len(enu) == len(gcj) == len(timestamps) == len(frame_nums)


def _candidate_geometry_metrics(element: FrameElement) -> dict:
    """Measure candidate coordinate lineage without promoting it to business data."""
    alignment_failures = 0
    endpoint_bbox_residual_px: list[float] = []
    tracked = {
        int(track_id): box
        for track_id, box in zip(
            element.id_list or [], element.tracked_xyxy or [], strict=False
        )
    }
    for candidate in element.candidate_trajectories or []:
        px = candidate.get("trajectory_px") or []
        display = candidate.get("trajectory_display_px") or []
        timestamps = candidate.get("trajectory_timestamps_sec") or []
        frame_nums = candidate.get("trajectory_frame_nums") or []
        lineage = candidate.get("point_quality_lineage") or []
        enu = candidate.get("trajectory_enu_m") or []
        aligned = (
            bool(px)
            and bool(display)
            and len(display) <= len(px)
            and len(px) == len(timestamps) == len(frame_nums) == len(lineage)
        )
        if enu:
            aligned = aligned and len(enu) == len(px)
        alignment_failures += int(not aligned)

        try:
            track_id = int(candidate.get("track_id"))
        except (TypeError, ValueError):
            continue
        bbox = tracked.get(track_id)
        if bbox is not None and display:
            endpoint = np.asarray(display[-1], dtype=np.float64)
            ground = np.asarray(
                [(float(bbox[0]) + float(bbox[2])) / 2.0, float(bbox[3])],
                dtype=np.float64,
            )
            if endpoint.shape == (2,) and np.isfinite(endpoint).all():
                endpoint_bbox_residual_px.append(float(np.linalg.norm(endpoint - ground)))
    return {
        "alignment_failures": alignment_failures,
        "endpoint_bbox_residual_px": endpoint_bbox_residual_px,
    }


def _draw_evidence(frame: np.ndarray, element: FrameElement) -> np.ndarray:
    rendered = frame.copy()
    formal_ids = set(element.formal_track_ids or [])
    for index, box in enumerate(element.tracked_xyxy or []):
        track_id = element.id_list[index] if index < len(element.id_list or []) else -1
        formal = track_id in formal_ids
        color = (40, 190, 60) if formal else (0, 170, 255)
        x1, y1, x2, y2 = [int(value) for value in box]
        cv2.rectangle(rendered, (x1, y1), (x2, y2), color, 3)
        cv2.putText(
            rendered,
            f"ID {track_id}",
            (x1, max(30, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            color,
            2,
            cv2.LINE_AA,
        )
    quality = element.geo_reference_quality or {}
    reasons = ", ".join(quality.get("reasons") or []) or "none"
    lines = [
        f"t={element.timestamp:.3f}s phase={element.flight_phase}",
        f"formal={element.formal_analytics_eligible} tracks={len(element.id_list or [])} "
        f"formal_tracks={len(element.formal_track_ids or [])}",
        f"geo={quality.get('status')} reasons={reasons[:150]}",
    ]
    panel_height = 46 * len(lines) + 18
    overlay = rendered.copy()
    cv2.rectangle(overlay, (0, 0), (rendered.shape[1], panel_height), (10, 10, 10), -1)
    cv2.addWeighted(overlay, 0.72, rendered, 0.28, 0, rendered)
    for index, line in enumerate(lines):
        cv2.putText(
            rendered,
            line,
            (24, 42 + index * 46),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (245, 245, 245),
            2,
            cv2.LINE_AA,
        )
    target_width = 1600
    if rendered.shape[1] > target_width:
        scale = target_width / rendered.shape[1]
        rendered = cv2.resize(
            rendered,
            (target_width, round(rendered.shape[0] * scale)),
            interpolation=cv2.INTER_AREA,
        )
    return rendered


def _render_show_node_evidence(
    frame: np.ndarray,
    element: FrameElement,
    config: dict,
) -> tuple[np.ndarray, int]:
    """Render with the production ShowNode and measure trail-only pixels."""
    rendered_variants: list[np.ndarray] = []
    for show_trace_trails in (True, False):
        render_config = copy.deepcopy(config)
        render_config["show_node"].update(
            {
                "draw_fps_info": False,
                "show_roi": False,
                "show_info_statistics": False,
                "imshow": False,
                "show_trace_trails": show_trace_trails,
            }
        )
        render_element = copy.copy(element)
        render_element.frame = frame.copy()
        render_element.frame_result = None
        rendered_element = ShowNode(render_config).process(render_element)
        rendered_variants.append(rendered_element.frame_result)

    with_trails, without_trails = rendered_variants
    diff = cv2.absdiff(with_trails, without_trails)
    trail_pixels = int(np.count_nonzero(np.any(diff > 0, axis=2)))
    return with_trails, trail_pixels


def _nodes(
    config: dict,
) -> tuple[
    list[object],
    GroundTrajectoryTrackerNode,
    PostTrackingWorldProjectionNode,
    TrackerInfoUpdateNode,
]:
    ground_tracker = GroundTrajectoryTrackerNode(config)
    world_projection = PostTrackingWorldProjectionNode(config)
    track_info = TrackerInfoUpdateNode(config)
    nodes = [
        ImageMotionEstimationNode(config),
        ground_tracker,
        HomographyCalibrationNode(config),
        MotionCompensationNode(config),
        FlightGeoReferenceNode(config),
        world_projection,
        track_info,
        SpeedEstimationNode(config),
        DirectionFlowNode(config),
        LaneDetectionNode(config),
        TrajectoryNode(config),
        RoadMapMatchingNode(config),
        LaneAnalysisNode(config),
        AutoLaneInferenceNode(config),
        ConflictDetectionNode(config),
        CalcStatisticsNode(config),
    ]
    return nodes, ground_tracker, world_projection, track_info


def run(args: argparse.Namespace, bundle: dict) -> dict:
    # The installed Ultralytics build emits the same `half` deprecation warning
    # on every predict call.  Preserve the production FP16 parameter while
    # keeping the acceptance log useful; all measured values remain in JSON.
    ULTRALYTICS_LOGGER.setLevel("ERROR")
    shadow_report = args.shadow_report or Path(
        f"/private/tmp/TrafficAnalyzer-xqh-tracking-shadow-{os.getpid()}.jsonl"
    )
    if shadow_report.exists():
        raise RuntimeError(f"refusing to append to existing shadow report: {shadow_report}")
    config = _load_config(
        video=args.video,
        srt=args.srt,
        source_profile_id=args.source_profile_id,
        bundle=bundle,
        device=args.device,
        stride=args.stride,
        shadow_report=shadow_report,
    )
    telemetry = SrtTelemetryParser(
        str(args.srt),
        sync_tolerance_sec=float(config["telemetry"]["sync_tolerance_sec"]),
    )
    detector = DetectionNode(config)
    nodes, ground_tracker, world_projection, track_info = _nodes(config)

    capture = cv2.VideoCapture(str(args.video))
    if not capture.isOpened():
        raise RuntimeError(f"cannot open video: {args.video}")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    source_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_sec = source_frames / fps
    start_frame = max(0, math.ceil(args.start_offset_sec * fps))
    end_offset = min(args.end_offset_sec or duration_sec, duration_sec)
    end_frame = min(source_frames - 1, math.floor(end_offset * fps))
    capture.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

    inference_ms: list[float] = []
    frame_wall_ms: list[float] = []
    phase_counts: Counter[str] = Counter()
    window_counts: dict[str, Counter[str]] = defaultdict(Counter)
    phase_segments: list[dict] = []
    formal_segments: list[dict] = []
    quality_reason_counts: Counter[str] = Counter()
    track_observations: dict[int, list[float]] = defaultdict(list)
    completed_tracks: dict[int, dict] = {}
    representative_targets = {
        "hover_verified": 880.0,
        "hover_exit_quality_break": 901.2,
        "departure_cruise": 907.0,
        "departure_degraded": 942.0,
    }
    representative_saved: dict[str, dict] = {}
    telemetry_hits = 0
    processed_frames = 0
    detected_frames = 0
    total_detections = 0
    raw_detections = 0
    invalid_detection_geometry_count = 0
    total_associations = 0
    camera_warp_frames = 0
    visual_verified_frames = 0
    formal_visual_valid_frames = 0
    formal_frames = 0
    formal_hover_frames = 0
    formal_track_observations = 0
    candidate_track_observations = 0
    departure_candidate_track_observations = 0
    degraded_business_leaks = 0
    alignment_failures = 0
    completed_alignment_failures = 0
    candidate_alignment_failures = 0
    candidate_endpoint_bbox_residual_px: list[float] = []
    shadow_frames = 0
    shadow_matched = 0
    shadow_unmatched_image_v2 = 0
    shadow_unmatched_legacy = 0
    termination_reason_counts: Counter[str] = Counter()
    hover_exit_quality_break_observed = False
    last_timestamp = args.start_offset_sec
    started_at = time.perf_counter()
    args.screenshots_dir.mkdir(parents=True, exist_ok=True)
    frame_index = start_frame
    while frame_index <= end_frame:
        ok = capture.grab()
        if not ok:
            break
        if (frame_index - start_frame) % args.stride != 0:
            frame_index += 1
            continue
        ok, frame = capture.retrieve()
        if not ok:
            raise RuntimeError(f"failed to retrieve source frame {frame_index}")
        timestamp = frame_index / fps
        last_timestamp = timestamp
        element = FrameElement(
            str(args.video), frame, timestamp, frame_index, {}
        )
        element.telemetry = telemetry.get_nearest(timestamp)
        if element.telemetry is not None:
            telemetry_hits += 1
        frame_started = time.perf_counter()
        element = detector.process(element)
        for node in nodes:
            element = node.process(element)
        frame_wall_ms.append((time.perf_counter() - frame_started) * 1000.0)
        inference_ms.append(float(element.inference_ms))
        processed_frames += 1
        detection_count = len(element.detected_xyxy or [])
        detection_diagnostics = element.detection_diagnostics or {}
        raw_detections += int(
            detection_diagnostics.get("raw_detection_count") or detection_count
        )
        invalid_detection_geometry_count += int(
            detection_diagnostics.get("invalid_geometry_count") or 0
        )
        association_count = len(element.id_list or [])
        total_detections += detection_count
        total_associations += association_count
        detected_frames += int(detection_count > 0)
        phase_counts[element.flight_phase] += 1
        window = "hover_tail" if timestamp < args.departure_offset_sec else "departure"
        window_counts[window][element.flight_phase] += 1
        _append_segment(
            phase_segments,
            timestamp=timestamp,
            value=element.flight_phase,
            key="phase",
        )
        _append_segment(
            formal_segments,
            timestamp=timestamp,
            value=bool(element.formal_analytics_eligible),
            key="formal_analytics_eligible",
        )
        quality = element.geo_reference_quality or {}
        quality_reason_counts.update(quality.get("reasons") or [])
        visual_status = (quality.get("visual_warp") or {}).get("status")
        visual_verified_frames += int(visual_status in {"verified", "bootstrap"})
        camera_warp_frames += int(element.camera_motion_warp is not None)
        formal_frames += int(element.formal_analytics_eligible)
        formal_visual_valid_frames += int(
            element.formal_analytics_eligible
            and visual_status in {"verified", "bootstrap"}
        )
        formal_hover_frames += int(
            element.formal_analytics_eligible
            and element.flight_phase == "hover_verified"
            and timestamp < args.departure_offset_sec
        )
        formal_track_observations += len(element.formal_track_ids or [])
        candidate_track_observations += len(element.candidate_trajectories or [])
        candidate_geometry = _candidate_geometry_metrics(element)
        candidate_alignment_failures += candidate_geometry["alignment_failures"]
        candidate_endpoint_bbox_residual_px.extend(
            candidate_geometry["endpoint_bbox_residual_px"]
        )
        if timestamp >= args.departure_offset_sec:
            departure_candidate_track_observations += len(
                element.candidate_trajectories or []
            )
        for track_id in element.id_list or []:
            track_observations[int(track_id)].append(timestamp)
        termination_reason = (element.tracking_diagnostics or {}).get(
            "termination_reason"
        )
        if termination_reason:
            termination_reason_counts[termination_reason] += 1
        if (
            args.departure_offset_sec - 2.0
            <= timestamp
            <= args.departure_offset_sec + 2.0
            and not element.formal_analytics_eligible
            and element.flight_phase
            in {"transition", "unsupported_pose", "cruise_nadir"}
        ):
            hover_exit_quality_break_observed = True

        if element.formal_analytics_eligible:
            alignment_failures += sum(
                not _track_lengths_aligned(track)
                for track in (element.buffer_tracks or {}).values()
            )
        else:
            info = element.info or {}
            leak = bool(
                (element.formal_track_ids or [])
                or (element.buffer_tracks or {})
                or (element.conflict_events or [])
                or info.get("cars_amount") is not None
            )
            degraded_business_leaks += int(leak)

        for completed in element.completed_tracks or []:
            completed_tracks[int(completed["track_id"])] = completed
            completed_alignment_failures += int(
                not _completed_lengths_aligned(completed)
            )
        shadow = (element.tracking_diagnostics or {}).get("shadow_comparison")
        if shadow:
            shadow_frames += 1
            shadow_matched += len(shadow.get("matched_by_iou") or [])
            shadow_unmatched_image_v2 += len(
                shadow.get("unmatched_image_v2") or []
            )
            shadow_unmatched_legacy += len(shadow.get("unmatched_legacy") or [])

        for label, target in representative_targets.items():
            if label in representative_saved:
                continue
            if abs(timestamp - target) <= (args.stride / fps) / 2 + 1e-6:
                path = args.screenshots_dir / f"xqh-hover-departure-{label}.jpg"
                show_node_path = (
                    args.screenshots_dir
                    / f"xqh-hover-departure-{label}-show-node.jpg"
                )
                cv2.imwrite(
                    str(path),
                    _draw_evidence(frame, element),
                    [cv2.IMWRITE_JPEG_QUALITY, 90],
                )
                show_node_frame, candidate_trace_pixels = (
                    _render_show_node_evidence(frame, element, config)
                )
                cv2.imwrite(
                    str(show_node_path),
                    show_node_frame,
                    [cv2.IMWRITE_JPEG_QUALITY, 90],
                )
                representative_saved[label] = {
                    "timestamp_sec": round(timestamp, 3),
                    "path": str(path.resolve()),
                    "show_node_path": str(show_node_path.resolve()),
                    "flight_phase": element.flight_phase,
                    "formal_analytics_eligible": bool(
                        element.formal_analytics_eligible
                    ),
                    "detections": detection_count,
                    "tracks": association_count,
                    "candidate_trace_pixels": candidate_trace_pixels,
                }
        if processed_frames % args.progress_every == 0:
            elapsed = time.perf_counter() - started_at
            print(
                json.dumps(
                    {
                        "progress_frames": processed_frames,
                        "source_timestamp_sec": round(timestamp, 3),
                        "elapsed_sec": round(elapsed, 1),
                        "last_phase": element.flight_phase,
                        "last_detections": detection_count,
                        "last_tracks": association_count,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
        frame_index += 1
    capture.release()

    eof = VideoEndBreakElement(str(args.video), last_timestamp)
    eof = ground_tracker.process(eof)
    eof = world_projection.process(eof)
    tracker_flush = world_projection.last_flush_result or {}
    flush_frame = track_info.flush(
        timestamp=last_timestamp,
        reason=tracker_flush.get("termination_reason", "natural_eof"),
        terminated_track_ids=tracker_flush.get("terminated_track_ids"),
    )
    if flush_frame is not None:
        for completed in flush_frame.completed_tracks or []:
            completed_tracks[int(completed["track_id"])] = completed
            completed_alignment_failures += int(
                not _completed_lengths_aligned(completed)
            )
    wall_sec = time.perf_counter() - started_at

    steady_inference = inference_ms[min(3, len(inference_ms)) :]
    track_lifetimes = [
        max(times) - min(times) for times in track_observations.values() if len(times) >= 2
    ]
    telemetry_coverage = telemetry_hits / processed_frames if processed_frames else 0.0
    detection_coverage = detected_frames / processed_frames if processed_frames else 0.0
    visual_valid_ratio = visual_verified_frames / processed_frames if processed_frames else 0.0
    formal_visual_valid_ratio = (
        formal_visual_valid_frames / formal_frames if formal_frames else 0.0
    )
    source_sample_hz = fps / args.stride
    steady_p95 = _percentile(steady_inference, 95)
    frame_p95 = _percentile(frame_wall_ms[min(3, len(frame_wall_ms)) :], 95)
    endpoint_bbox_p95 = _percentile(candidate_endpoint_bbox_residual_px, 95)
    lineage = bundle["visual_registration"]
    candidate_trail_evidence = [
        evidence
        for evidence in representative_saved.values()
        if not evidence["formal_analytics_eligible"]
        and evidence["candidate_trace_pixels"] > 0
    ]
    gates = {
        "mps_runtime_available": args.device != "mps" or torch.backends.mps.is_available(),
        "source_sample_hz_gte_6": source_sample_hz >= 6.0,
        "steady_detector_p95_lte_1s": steady_p95 is not None and steady_p95 <= 1000.0,
        "single_process_frame_p95_lte_1s": frame_p95 is not None and frame_p95 <= 1000.0,
        "telemetry_coverage_gte_95pct": telemetry_coverage >= 0.95,
        "detections_present": total_detections > 0 and detection_coverage >= 0.95,
        "zero_invalid_detection_geometry": invalid_detection_geometry_count == 0,
        "hover_verified_observed": phase_counts["hover_verified"] > 0,
        "hover_exit_quality_break_observed": hover_exit_quality_break_observed,
        "quality_break_terminates_formal_tracks": (
            termination_reason_counts["mode_transition_quality_break"] > 0
        ),
        "departure_motion_phase_observed": (
            phase_counts["cruise_nadir"] + phase_counts["unsupported_pose"] > 0
        ),
        "formal_hover_observed": formal_hover_frames > 0,
        "formal_visual_valid_ratio_gte_95pct": formal_visual_valid_ratio >= 0.95,
        "candidate_departure_observed": departure_candidate_track_observations > 0,
        "zero_degraded_business_leak": degraded_business_leaks == 0,
        "active_trajectory_point_alignment": alignment_failures == 0,
        "completed_trajectory_point_alignment": completed_alignment_failures == 0,
        "candidate_trajectory_point_alignment": candidate_alignment_failures == 0,
        "image_only_association_method_active": (
            GroundTrajectoryTrackerNode.tracking_method
            == "motion_compensated_image_v2"
        ),
        "candidate_endpoint_bbox_residual_p95_lte_5px": (
            endpoint_bbox_p95 is not None and endpoint_bbox_p95 <= 5.0
        ),
        "runtime_pose_lineage_present": all(
            lineage.get(key)
            for key in (
                "registration_pose",
                "camera_calibration",
                "map_coverage_enu_m",
            )
        ),
        "natural_eof_flush": tracker_flush.get("termination_reason") == "natural_eof",
        "candidate_output_trail_rendered": bool(candidate_trail_evidence),
        "representative_evidence_complete": set(representative_saved)
        == set(representative_targets),
    }
    engineering_passed = all(gates.values())
    return {
        "schema_version": "uav.xqh-hover-departure-acceptance/v1",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "acceptance_scope": {
            "type": "engineering_real_video_acceptance",
            "production_accuracy_gate": "not_evaluated_no_ground_truth",
            "annotation_work_package": "out_of_scope",
            "claims": [
                "real MP4+SRT detector execution",
                "MPS steady-state timing",
                "hover-to-departure phase and quality transition",
                "pre-georeference image-motion ByteTrack and legacy shadow comparison",
                "production ShowNode candidate-trail rendering",
                "zero degraded trajectory leakage into formal statistics/TCC",
                "natural EOF and per-point trajectory alignment",
                "MPS detection geometry and post-ID image/world coordinate alignment",
            ],
            "non_claims": ["IDF1", "HOTA", "world-position RMSE", "speed MAE"],
        },
        "result": {
            "engineering_passed": engineering_passed,
            "production_release_gate": "engineering_only_accuracy_not_claimed",
            "gate_results": gates,
        },
        "source": {
            "video": str(args.video.resolve()),
            "video_size_bytes": args.video.stat().st_size,
            "srt": str(args.srt.resolve()),
            "srt_sha256": _sha256(args.srt),
            "source_profile_id": args.source_profile_id,
            "inter_id": args.inter_id,
            "map_version_id": args.map_version_id,
            "map_status": bundle.get("map_status"),
            "registration_id": lineage.get("id"),
            "registration_frame_id": (lineage.get("registration_pose") or {}).get(
                "source_frame_id"
            ),
            "camera_calibration_sha256": (
                lineage.get("camera_calibration") or {}
            ).get("sha256"),
        },
        "profile": {
            "tracking_profile": "hover_cruise_v1",
            "device": args.device,
            "machine": platform.machine(),
            "torch_version": torch.__version__,
            "mps_available": torch.backends.mps.is_available(),
            "weight": config["detection_node"]["weight_pth"],
            "model_id": detector.yolo_model_id,
            "imgsz": config["detection_node"]["imgsz"],
            "confidence": config["detection_node"]["confidence"],
            "stride": args.stride,
            "source_fps": round(fps, 6),
            "source_sample_hz": round(source_sample_hz, 6),
            "start_offset_sec": args.start_offset_sec,
            "departure_offset_sec": args.departure_offset_sec,
            "end_offset_sec": round(end_offset, 3),
        },
        "performance": {
            "processed_frames": processed_frames,
            "wall_sec": round(wall_sec, 3),
            "cold_inference_ms": inference_ms[0] if inference_ms else None,
            "steady_inference_p50_ms": _percentile(steady_inference, 50),
            "steady_inference_p95_ms": steady_p95,
            "steady_inference_max_ms": round(max(steady_inference), 3)
            if steady_inference
            else None,
            "single_process_frame_p50_ms": _percentile(
                frame_wall_ms[min(3, len(frame_wall_ms)) :], 50
            ),
            "single_process_frame_p95_ms": frame_p95,
        },
        "detection_tracking": {
            "detected_frames": detected_frames,
            "detection_coverage": round(detection_coverage, 6),
            "total_detections": total_detections,
            "raw_detections": raw_detections,
            "invalid_detection_geometry_count": invalid_detection_geometry_count,
            "mean_detections_per_frame": round(
                total_detections / processed_frames, 3
            ),
            "total_associations": total_associations,
            "unique_track_ids": len(track_observations),
            "median_observed_track_lifetime_sec": round(
                statistics.median(track_lifetimes), 3
            )
            if track_lifetimes
            else None,
            "p95_observed_track_lifetime_sec": _percentile(track_lifetimes, 95),
            "formal_track_observations": formal_track_observations,
            "candidate_track_observations": candidate_track_observations,
            "departure_candidate_track_observations": (
                departure_candidate_track_observations
            ),
            "completed_tracks": len(completed_tracks),
            "camera_motion_warp_frames": camera_warp_frames,
            "shadow": {
                "frames": shadow_frames,
                "matched_by_iou": shadow_matched,
                "unmatched_image_v2": shadow_unmatched_image_v2,
                "unmatched_legacy": shadow_unmatched_legacy,
                "report_path": str(shadow_report),
                "note": "count comparison is diagnostic and is not IDF1/HOTA",
            },
        },
        "quality": {
            "telemetry_coverage": round(telemetry_coverage, 6),
            "visual_valid_ratio": round(visual_valid_ratio, 6),
            "formal_visual_valid_ratio": round(formal_visual_valid_ratio, 6),
            "formal_frames": formal_frames,
            "formal_hover_frames": formal_hover_frames,
            "degraded_business_leaks": degraded_business_leaks,
            "active_alignment_failures": alignment_failures,
            "completed_alignment_failures": completed_alignment_failures,
            "candidate_alignment_failures": candidate_alignment_failures,
            "candidate_endpoint_bbox_residual_p95_px": endpoint_bbox_p95,
            "candidate_endpoint_bbox_residual_max_px": (
                round(max(candidate_endpoint_bbox_residual_px), 3)
                if candidate_endpoint_bbox_residual_px
                else None
            ),
            "quality_reason_counts": dict(quality_reason_counts),
            "termination_reason_counts": dict(termination_reason_counts),
            "transition_phase_observed": phase_counts["transition"] > 0,
        },
        "flight_phase_counts": dict(phase_counts),
        "window_phase_counts": {
            key: dict(value) for key, value in window_counts.items()
        },
        "flight_phase_segments": phase_segments,
        "formal_eligibility_segments": formal_segments,
        "representative_evidence": representative_saved,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, default=DEFAULT_VIDEO)
    parser.add_argument("--srt", type=Path, default=DEFAULT_SRT)
    parser.add_argument("--inter-id", default=DEFAULT_INTER_ID)
    parser.add_argument("--map-version-id", default=DEFAULT_MAP_ID)
    parser.add_argument("--source-profile-id", default=DEFAULT_SOURCE_PROFILE_ID)
    parser.add_argument("--start-offset-sec", type=float, default=840.0)
    parser.add_argument("--departure-offset-sec", type=float, default=902.0)
    parser.add_argument("--end-offset-sec", type=float, default=None)
    parser.add_argument("--stride", type=int, default=4)
    parser.add_argument("--device", choices=("mps", "cpu", "cuda"), default="mps")
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "docs/generated/xqh-hover-departure-acceptance.json",
    )
    parser.add_argument(
        "--screenshots-dir",
        type=Path,
        default=PROJECT_ROOT / "docs/test-screenshots",
    )
    parser.add_argument("--shadow-report", type=Path)
    parser.add_argument("--progress-every", type=int, default=100)
    args = parser.parse_args()
    if args.stride < 1:
        parser.error("--stride must be >= 1")
    if args.start_offset_sec >= args.departure_offset_sec:
        parser.error("start offset must precede departure offset")
    if not args.video.is_file() or not args.srt.is_file():
        parser.error("video and SRT assets must exist")
    return args


def main() -> None:
    args = parse_args()
    bundle = asyncio.run(_load_runtime_bundle(args.inter_id, args.map_version_id))
    report = run(args, bundle)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report["result"], ensure_ascii=False, indent=2), flush=True)
    print(f"report={args.output.resolve()}", flush=True)
    if not report["result"]["engineering_passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
