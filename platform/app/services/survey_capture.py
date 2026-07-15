"""MP4 + DJI SRT capture-batch processor."""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass
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


def _nearest(records: list[dict], timestamps: list[float], timestamp: float) -> dict:
    if not records:
        return {}
    index = bisect.bisect_left(timestamps, timestamp)
    candidates = [i for i in (index - 1, index, index + 1) if 0 <= i < len(records)]
    return records[min(candidates, key=lambda i: abs(timestamps[i] - timestamp))]


def _jpeg(frame: np.ndarray, quality: int = 88) -> bytes:
    ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError("failed to encode survey frame")
    return encoded.tobytes()


def process_mp4_srt(video_path: str | Path, srt_path: str | Path, keyframe_count: int = 6) -> ProcessedBatch:
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
    telemetry_records = parse_dji_srt(srt_path)
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
        telemetry = _nearest(telemetry_records, telemetry_timestamps, timestamp)
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
    srt_duration = telemetry_timestamps[-1] - telemetry_timestamps[0] if len(telemetry_timestamps) > 1 else 0
    coverage = min(1.0, srt_duration / duration) if duration else 0.0
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
