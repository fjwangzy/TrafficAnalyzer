"""MP4 + DJI SRT capture-batch processor."""

from __future__ import annotations

import bisect
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from app.services.survey_geometry import compute_homography_from_telemetry, create_bev


@dataclass
class ProcessedFrame:
    frame_number: int
    timestamp_sec: float
    image: bytes
    bev: bytes
    image_width: int
    image_height: int
    homography: list | None
    view_transform: list
    telemetry: dict
    quality: dict


@dataclass
class ProcessedBatch:
    duration_sec: float
    fps: float
    frame_count: int
    telemetry_coverage: float
    quality_checks: dict
    frames: list[ProcessedFrame]


def _srt_seconds(value: str) -> float:
    hours, minutes, rest = value.split(":")
    seconds, millis = rest.split(",")
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000


def parse_dji_srt(path: str | Path) -> list[dict]:
    records: list[dict] = []
    for block in Path(path).read_text(encoding="utf-8", errors="replace").strip().split("\n\n"):
        lines = block.strip().splitlines()
        if len(lines) < 4 or "-->" not in lines[1]:
            continue
        try:
            timestamp = _srt_seconds(lines[1].split("-->")[0].strip())
        except (ValueError, IndexError):
            continue
        meta = " ".join(lines[3:])
        pairs = dict(re.findall(r"([a-z_]+):\s*(-?\d+(?:\.\d+)?)", meta, re.I))
        try:
            rel_alt = float(pairs.get("rel_alt", 0))
            zoom_ratio = float(pairs.get("dzoom_ratio", 1))
            records.append(
                {
                    "timestamp": timestamp,
                    "latitude": float(pairs.get("latitude", 0)),
                    "longitude": float(pairs.get("longitude", 0)),
                    "altitude_agl": rel_alt,
                    "gimbal_yaw": float(pairs.get("gb_yaw", 0)),
                    "gimbal_pitch": float(pairs.get("gb_pitch", -90)),
                    "gimbal_roll": float(pairs.get("gb_roll", 0)),
                    "zoom_factor": 1 / zoom_ratio if zoom_ratio > 0 else 1,
                }
            )
        except ValueError:
            continue
    return records


def parse_dji_json(path: str | Path) -> list[dict]:
    """Parse DJI Cloud API JSON exports (including files with a .txt suffix)."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("DJI telemetry JSON must contain a data array")
    decoded: list[tuple[datetime, dict]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            recorded_at = datetime.strptime(str(row["time"]), "%Y-%m-%d %H:%M:%S.%f")
            value = row.get("value", {})
            value = json.loads(value) if isinstance(value, str) else value
            if not isinstance(value, dict):
                continue
            decoded.append((recorded_at, value))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
    decoded.sort(key=lambda item: item[0])
    if not decoded:
        return []
    origin = decoded[0][0]
    records: list[dict] = []
    for recorded_at, value in decoded:
        camera = value.get("99-0-0", {}) if isinstance(value.get("99-0-0"), dict) else {}
        records.append(
            {
                "timestamp": (recorded_at - origin).total_seconds(),
                "recorded_at": recorded_at.isoformat(),
                "latitude": value.get("latitude"),
                "longitude": value.get("longitude"),
                "altitude_agl": float(value.get("height") or 0),
                "attitude_head": float(value.get("attitude_head") or 0),
                "attitude_pitch": float(value.get("attitude_pitch") or 0),
                "gimbal_yaw": float(camera.get("gimbal_yaw") or 0),
                "gimbal_pitch": float(camera.get("gimbal_pitch") if camera.get("gimbal_pitch") is not None else -90),
                "gimbal_roll": float(camera.get("gimbal_roll") or 0),
                "zoom_factor": float(camera.get("zoom_factor") or 1),
            }
        )
    return records


def _nearest(
    records: list[dict], timestamps: list[float], timestamp: float, tolerance_sec: float | None = None
) -> dict:
    if not records:
        return {}
    index = bisect.bisect_left(timestamps, timestamp)
    candidates = [i for i in (index - 1, index, index + 1) if 0 <= i < len(records)]
    nearest_index = min(candidates, key=lambda i: abs(timestamps[i] - timestamp))
    if tolerance_sec is not None and abs(timestamps[nearest_index] - timestamp) > tolerance_sec:
        return {}
    return records[nearest_index]


def _jpeg(frame: np.ndarray, quality: int = 88) -> bytes:
    ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError("failed to encode survey frame")
    return encoded.tobytes()


def process_event_keyframe(
    image: bytes,
    telemetry_path: str | Path,
    timestamp_sec: float,
    *,
    telemetry_type: str = "srt",
    time_offset_sec: float = 0.0,
    sync_tolerance_sec: float = 0.5,
    frame_number: int = 0,
) -> ProcessedFrame:
    """Build a metric BEV frame from an immutable event image and its source telemetry."""
    decoded = cv2.imdecode(np.frombuffer(image, dtype=np.uint8), cv2.IMREAD_COLOR)
    if decoded is None or decoded.size == 0:
        raise ValueError("event keyframe cannot be decoded")
    height, width = decoded.shape[:2]
    telemetry_records = (
        parse_dji_srt(telemetry_path)
        if telemetry_type == "srt"
        else parse_dji_json(telemetry_path)
    )
    telemetry = _nearest(
        telemetry_records,
        [record["timestamp"] for record in telemetry_records],
        timestamp_sec + time_offset_sec,
        sync_tolerance_sec,
    )
    homography = compute_homography_from_telemetry(telemetry, (width, height))
    if homography is None or abs(np.linalg.det(homography)) <= 1e-10:
        raise ValueError("event keyframe has no synchronized metric transform")
    bev, image_to_view = create_bev(decoded, homography)
    gray = cv2.cvtColor(decoded, cv2.COLOR_BGR2GRAY)
    return ProcessedFrame(
        frame_number=frame_number,
        timestamp_sec=timestamp_sec,
        image=image,
        bev=_jpeg(bev),
        image_width=width,
        image_height=height,
        homography=homography.tolist(),
        view_transform=image_to_view.tolist(),
        telemetry=telemetry,
        quality={
            "clarity_laplacian": round(float(cv2.Laplacian(gray, cv2.CV_64F).var()), 3),
            "exposure_mean": round(float(gray.mean()), 3),
            "positioning": "unverified",
            "homography": "unverified",
            "source": "event_keyframe",
        },
    )


def process_mp4_telemetry(
    video_path: str | Path,
    telemetry_path: str | Path,
    keyframe_count: int = 6,
    telemetry_type: str = "srt",
    time_offset_sec: float = 0.0,
    sync_tolerance_sec: float = 0.5,
) -> ProcessedBatch:
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise ValueError("video cannot be opened")
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    if fps <= 0 or frame_count <= 0 or width <= 0 or height <= 0:
        capture.release()
        raise ValueError("video metadata is incomplete")
    duration = frame_count / fps
    telemetry_records = (
        parse_dji_srt(telemetry_path)
        if telemetry_type == "srt"
        else parse_dji_json(telemetry_path)
    )
    telemetry_timestamps = [record["timestamp"] for record in telemetry_records]
    if keyframe_count == 1:
        frame_numbers = [frame_count // 2]
    else:
        frame_numbers = np.linspace(int(frame_count * 0.05), int(frame_count * 0.95), keyframe_count, dtype=int).tolist()

    processed: list[ProcessedFrame] = []
    clarity_values: list[float] = []
    exposure_values: list[float] = []
    homography_count = 0
    for frame_number in frame_numbers:
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        ok, frame = capture.read()
        if not ok:
            continue
        timestamp = frame_number / fps
        telemetry = _nearest(
            telemetry_records,
            telemetry_timestamps,
            timestamp + time_offset_sec,
            sync_tolerance_sec,
        )
        homography = compute_homography_from_telemetry(telemetry, (width, height))
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        clarity = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        exposure = float(gray.mean())
        clarity_values.append(clarity)
        exposure_values.append(exposure)
        if homography is not None and abs(np.linalg.det(homography)) > 1e-10:
            bev, image_to_view = create_bev(frame, homography)
            homography_count += 1
            homography_value = homography.tolist()
            transform_value = image_to_view.tolist()
        else:
            bev = frame.copy()
            homography_value = None
            transform_value = np.eye(3).tolist()
        processed.append(
            ProcessedFrame(
                frame_number=frame_number,
                timestamp_sec=timestamp,
                image=_jpeg(frame),
                bev=_jpeg(bev),
                image_width=width,
                image_height=height,
                homography=homography_value,
                view_transform=transform_value,
                telemetry=telemetry,
                quality={
                    "clarity_laplacian": round(clarity, 3),
                    "exposure_mean": round(exposure, 3),
                    "positioning": "unverified" if telemetry else "unavailable",
                    "homography": "unverified" if homography_value else "unavailable",
                },
            )
        )
    capture.release()
    sample_count = min(1000, max(1, int(duration) + 1))
    sample_times = np.linspace(0, duration, sample_count)
    matched = sum(
        bool(
            _nearest(
                telemetry_records,
                telemetry_timestamps,
                float(sample_time) + time_offset_sec,
                sync_tolerance_sec,
            )
        )
        for sample_time in sample_times
    )
    coverage = matched / sample_count
    return ProcessedBatch(
        duration_sec=duration,
        fps=fps,
        frame_count=frame_count,
        telemetry_coverage=coverage,
        quality_checks={
            "status": "unverified",
            "telemetry_coverage": round(coverage, 6),
            "keyframes_extracted": len(processed),
            "homography_available": homography_count,
            "clarity_laplacian_mean": round(float(np.mean(clarity_values)), 3) if clarity_values else None,
            "exposure_mean": round(float(np.mean(exposure_values)), 3) if exposure_values else None,
            "rtk_status": "unavailable",
            "spatial_coverage": "unavailable",
        },
        frames=processed,
    )


def process_mp4_srt(video_path: str | Path, srt_path: str | Path, keyframe_count: int = 6) -> ProcessedBatch:
    """Backward-compatible wrapper for the original survey contract."""
    return process_mp4_telemetry(video_path, srt_path, keyframe_count, telemetry_type="srt")
