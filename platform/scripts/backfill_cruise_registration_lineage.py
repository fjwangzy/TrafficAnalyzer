"""Backfill verified visual-registration pose lineage from immutable capture evidence.

The command is deliberately target-explicit and dry-run by default.  It never
changes a homography, map geometry, lane binding, or publication status.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
from shapely.geometry import mapping, shape
from shapely.ops import unary_union
from sqlalchemy import select

PLATFORM_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = PLATFORM_DIR.parent
for path in (PLATFORM_DIR, PROJECT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from utils_local.coordinates import normalize_telemetry_position  # noqa: E402
from utils_local.homography import compute_homography_from_telemetry  # noqa: E402

from app.core.database import async_session_maker, close_db  # noqa: E402
from app.models.mission import (  # noqa: E402
    ChannelizedMapVersion,
    VisualLaneBinding,
    VisualRegistration,
)
from app.models.survey import SurveyCaptureBatch, SurveyFrame  # noqa: E402

CAMERA_INTRINSICS = {
    "focal_length_mm": 4.5,
    "sensor_width_mm": 6.4,
    "sensor_height_mm": 3.6,
}
DIST_COEFFS: list[float] = []


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _difference_paths(left: object, right: object, path: str = "$") -> list[str]:
    """Return compact JSON paths for a refused lineage replacement."""
    if isinstance(left, dict) and isinstance(right, dict):
        differences = []
        for key in sorted(set(left) | set(right)):
            child_path = f"{path}.{key}"
            if key not in left or key not in right:
                differences.append(child_path)
            else:
                differences.extend(_difference_paths(left[key], right[key], child_path))
        return differences
    if isinstance(left, list) and isinstance(right, list):
        differences = []
        if len(left) != len(right):
            differences.append(f"{path}.length")
        for index, (left_item, right_item) in enumerate(zip(left, right, strict=False)):
            differences.extend(
                _difference_paths(left_item, right_item, f"{path}[{index}]")
            )
        return differences
    if (
        isinstance(left, (int, float))
        and not isinstance(left, bool)
        and isinstance(right, (int, float))
        and not isinstance(right, bool)
        and math.isclose(float(left), float(right), rel_tol=1e-12, abs_tol=1e-12)
    ):
        return []
    return [] if left == right else [f"{path} ({left!r} != {right!r})"]


def _camera_calibration() -> dict:
    facts = {
        "camera_intrinsics": CAMERA_INTRINSICS,
        "dist_coeffs": DIST_COEFFS,
        "model": "pinhole_brown_conrady",
    }
    return {
        **facts,
        "version": "xqh-source-profile-camera/v1",
        "sha256": hashlib.sha256(_canonical(facts).encode()).hexdigest(),
    }


def _map_coverage(lanes: list[VisualLaneBinding]) -> dict:
    geometries = []
    for lane in lanes:
        raw = lane.geometry_enu_m
        if isinstance(raw, str):
            raw = json.loads(raw)
        if raw:
            geometries.append(shape(raw))
    if not geometries:
        raise RuntimeError("verified map has no lane coverage geometry")
    coverage = unary_union(geometries)
    if coverage.is_empty or not coverage.is_valid:
        coverage = coverage.buffer(0)
    if coverage.is_empty or not coverage.is_valid:
        raise RuntimeError("verified lane coverage cannot form a valid geometry")
    return json.loads(json.dumps(mapping(coverage)))


def _registration_pose(frame: SurveyFrame) -> dict:
    telemetry = normalize_telemetry_position(dict(frame.telemetry or {})) or {}
    position = telemetry.get("position_gcj02") or {}
    if position.get("longitude") is None or position.get("latitude") is None:
        raise RuntimeError("capture frame has no canonical GCJ-02 position")
    local_h = compute_homography_from_telemetry(
        telemetry,
        CAMERA_INTRINSICS,
        (int(frame.image_width), int(frame.image_height)),
    )
    if np.asarray(local_h).shape != (3, 3) or not np.isfinite(local_h).all():
        raise RuntimeError("capture frame telemetry homography is invalid")
    return {
        "source_frame_id": frame.id,
        "source_frame_number": int(frame.frame_number),
        "source_timestamp_sec": float(frame.timestamp_sec),
        "position_gcj02": [
            float(position["longitude"]),
            float(position["latitude"]),
        ],
        "altitude_agl": float(telemetry["altitude_agl"]),
        "gimbal_yaw": float(telemetry.get("gimbal_yaw") or 0.0),
        "gimbal_pitch": float(telemetry.get("gimbal_pitch") or -90.0),
        "gimbal_roll": float(telemetry.get("gimbal_roll") or 0.0),
        "zoom_factor": float(telemetry.get("zoom_factor") or 1.0),
        "telemetry_homography_pixel_to_local_enu": np.asarray(
            local_h, dtype=np.float64
        ).tolist(),
        "telemetry_homography_version": "telemetry-pinhole/v1",
    }


async def backfill(
    *,
    map_version_id: str,
    source_profile_id: str,
    capture_frame_id: str,
    apply: bool,
) -> dict:
    async with async_session_maker() as session:
        channelized_map = await session.get(ChannelizedMapVersion, map_version_id)
        registration = (
            await session.execute(
                select(VisualRegistration).where(
                    VisualRegistration.map_version_id == map_version_id,
                    VisualRegistration.source_profile_id == source_profile_id,
                )
            )
        ).scalar_one_or_none()
        frame = await session.get(SurveyFrame, capture_frame_id)
        if channelized_map is None or channelized_map.status != "lane_verified":
            raise RuntimeError("target map is not lane_verified")
        if registration is None or registration.status != "verified":
            raise RuntimeError("target visual registration is not verified")
        if frame is None or not frame.selected:
            raise RuntimeError("capture frame is missing or not selected")
        batch = await session.get(SurveyCaptureBatch, frame.batch_id)
        if batch is None or batch.source_profile_id != source_profile_id:
            raise RuntimeError("capture frame does not belong to target source profile")
        if capture_frame_id not in Path(registration.source_image_path).name:
            raise RuntimeError("registration source image does not match capture frame")
        lanes = (
            await session.execute(
                select(VisualLaneBinding).where(
                    VisualLaneBinding.map_version_id == map_version_id,
                    VisualLaneBinding.status == "lane_verified",
                )
            )
        ).scalars().all()

        pose = _registration_pose(frame)
        camera = _camera_calibration()
        coverage = _map_coverage(list(lanes))
        proposed = {
            "registration_pose": pose,
            "camera_calibration": camera,
            "map_coverage_enu_m": coverage,
        }
        existing = {
            "registration_pose": registration.registration_pose or {},
            "camera_calibration": registration.camera_calibration or {},
            "map_coverage_enu_m": registration.map_coverage_enu_m or {},
        }
        for key, value in existing.items():
            differing_paths = _difference_paths(value, proposed[key])[:8]
            if value and differing_paths:
                raise RuntimeError(
                    f"refusing to replace existing {key}; differing paths: "
                    + ", ".join(differing_paths)
                )

        changed = any(not value for value in existing.values())
        if apply and changed:
            registration.registration_pose = pose
            registration.camera_calibration = camera
            registration.map_coverage_enu_m = coverage
            await session.commit()
        bounds = shape(coverage).bounds
        return {
            "schema_version": "uav.registration-lineage-backfill/v1",
            "mode": "apply" if apply else "dry_run",
            "map_version_id": map_version_id,
            "source_profile_id": source_profile_id,
            "registration_id": registration.id,
            "capture_frame_id": frame.id,
            "capture_timestamp_sec": frame.timestamp_sec,
            "camera_calibration_sha256": camera["sha256"],
            "coverage_geometry_type": coverage["type"],
            "coverage_bounds_enu_m": [round(float(value), 3) for value in bounds],
            "verified_lane_count": len(lanes),
            "changed": changed and apply,
            "would_change": changed,
        }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--map-version-id", required=True)
    parser.add_argument("--source-profile-id", required=True)
    parser.add_argument("--capture-frame-id", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        result = await backfill(
            map_version_id=args.map_version_id,
            source_profile_id=args.source_profile_id,
            capture_frame_id=args.capture_frame_id,
            apply=args.apply,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
