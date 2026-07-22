#!/usr/bin/env python3
"""Render read-only YCX Link/lane candidates over registered drone frames.

This is a stage-1 review helper. It writes only local PNG evidence and never
modifies YCX or road9.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
PLATFORM = ROOT / "platform"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(PLATFORM))

from audit_ycx_readonly_schema import _credential_values  # noqa: E402
from app.services.ycx_road_import import YcxRoadImporter  # noqa: E402
from bootstrap_mp4new_sources import LOCAL_REPLAY_CATALOG  # noqa: E402
from services.SrtTelemetryParser import SrtTelemetryParser  # noqa: E402
from services.TelemetryFileReader import TelemetryFileReader  # noqa: E402
from utils_local.coordinates import gcj02_to_enu, normalize_telemetry_position  # noqa: E402
from utils_local.homography import compute_homography_from_telemetry  # noqa: E402


YCX_IDS = {
    "011wwe0z19700001": ("011wwe0z19700001",),
    "011wwe28dm500001": ("011wwe28dm500001",),
    # The eastern YCX node is the one visible in the registered Lishi videos.
    "011wwe28dr400003": ("011wwe28dr400003",),
    "011wwe29k1q00001": ("011wwe29k1q00001",),
}


def _default_source(item: dict) -> dict:
    return next((source for source in item["sources"] if source.get("default")), item["sources"][0])


def _frame(path: Path, timestamp_sec: float) -> tuple[np.ndarray, float]:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"cannot open video: {path}")
    try:
        capture.set(cv2.CAP_PROP_POS_MSEC, timestamp_sec * 1000.0)
        ok, frame = capture.read()
        if not ok:
            raise RuntimeError(f"cannot read video frame: {path}@{timestamp_sec}")
        actual = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
        return frame, actual
    finally:
        capture.release()


def _telemetry(source: dict, timestamp_sec: float) -> dict:
    path = ROOT / source["telemetry"]
    parser = (
        SrtTelemetryParser(
            str(path), sync_tolerance_sec=1.0,
            time_offset_sec=float(source.get("time_offset_sec", 0)),
        )
        if source.get("telemetry_type") == "srt"
        else TelemetryFileReader(
            str(path), sync_tolerance_sec=1.0,
            time_offset_sec=float(source.get("time_offset_sec", 0)),
        )
    )
    value = parser.get_nearest(timestamp_sec)
    if value is None:
        raise RuntimeError(f"telemetry unavailable: {path}@{timestamp_sec}")
    return normalize_telemetry_position(value)


def _map_homography(frame: np.ndarray, telemetry: dict, anchor_gcj02: list[float]) -> np.ndarray:
    intrinsics = {
        "focal_length_mm": 4.5,
        "sensor_width_mm": 6.4,
        "sensor_height_mm": 3.6,
    }
    height, width = frame.shape[:2]
    local_h = compute_homography_from_telemetry(telemetry, intrinsics, (width, height))
    position = telemetry["position_gcj02"]
    east, north = gcj02_to_enu(
        position["longitude"], position["latitude"], anchor_gcj02
    )
    translation = np.asarray([[1.0, 0.0, east], [0.0, 1.0, north], [0.0, 0.0, 1.0]])
    return translation @ local_h


def _project_geometry(geometry: dict | None, inverse_h: np.ndarray) -> list[np.ndarray]:
    if not geometry:
        return []
    coordinates = geometry.get("coordinates") or []
    if geometry.get("type") in {"LineString", "LinearRing"}:
        lines = [coordinates]
    elif geometry.get("type") == "MultiLineString":
        lines = coordinates
    elif geometry.get("type") == "Polygon":
        lines = coordinates
    elif geometry.get("type") == "MultiPolygon":
        lines = [ring for polygon in coordinates for ring in polygon]
    else:
        return []
    projected = []
    for line in lines:
        if len(line) < 2:
            continue
        points = np.asarray([[float(point[0]), float(point[1]), 1.0] for point in line]).T
        pixels = inverse_h @ points
        valid = np.abs(pixels[2]) > 1e-9
        if not valid.any():
            continue
        pixels = (pixels[:2, valid] / pixels[2, valid]).T
        projected.append(np.rint(pixels).astype(np.int32))
    return projected


async def render(credentials_file: Path, output_dir: Path, timestamp_sec: float) -> dict:
    values = _credential_values(credentials_file)
    importer = YcxRoadImporter(SimpleNamespace(
        ycx_db_host=values["host"], ycx_db_port=int(values["port"]),
        ycx_db_user=values["user"], ycx_db_password=values["pwd"],
        ycx_db_name=values["db"], ycx_db_schema=values["schame"],
    ))
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = []
    for item in LOCAL_REPLAY_CATALOG:
        source = _default_source(item)
        frame, actual = _frame(ROOT / source["video"], timestamp_sec)
        telemetry = _telemetry(source, actual)
        roads = [
            await importer.import_intersection(inter_id)
            for inter_id in YCX_IDS[item["inter_id"]]
        ]
        road = roads[0]
        pixel_to_enu = _map_homography(frame, telemetry, road.anchor_gcj02)
        overlay = frame.copy()
        visible_links = visible_lanes = 0
        height, width = frame.shape[:2]
        for candidate in roads:
            inverse = np.linalg.inv(
                _map_homography(frame, telemetry, candidate.anchor_gcj02)
            )
            for geometry in candidate.geometry_enu_m["links"].values():
                for points in _project_geometry(geometry, inverse):
                    if np.any((points[:, 0] >= 0) & (points[:, 0] < width) & (points[:, 1] >= 0) & (points[:, 1] < height)):
                        visible_links += 1
                    cv2.polylines(overlay, [points], False, (255, 255, 0), 10, cv2.LINE_AA)
            for geometry in candidate.geometry_enu_m["lane_candidates"].values():
                for points in _project_geometry(geometry, inverse):
                    if np.any((points[:, 0] >= 0) & (points[:, 0] < width) & (points[:, 1] >= 0) & (points[:, 1] < height)):
                        visible_lanes += 1
                    cv2.polylines(overlay, [points], False, (0, 220, 255), 5, cv2.LINE_AA)
        blended = cv2.addWeighted(frame, 0.7, overlay, 0.3, 0)
        label = (
            f"{item['intersection_name']} | {'+'.join(YCX_IDS[item['inter_id']])} | "
            f"links {visible_links} lanes {visible_lanes}"
        )
        cv2.rectangle(blended, (0, 0), (width, 70), (10, 10, 10), -1)
        cv2.putText(blended, label, (20, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
        target = output_dir / f"{item['inter_id']}.jpg"
        cv2.imwrite(str(target), blended, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
        summary.append({
            "local_inter_id": item["inter_id"], "ycx_inter_ids": list(YCX_IDS[item["inter_id"]]),
            "name": item["intersection_name"], "source_profile_id": source["profile_id"],
            "video_timestamp_sec": actual, "anchor_gcj02": road.anchor_gcj02,
            "position_gcj02": telemetry["position_gcj02"],
            "homography_pixel_to_enu": pixel_to_enu.tolist(),
            "visible_links": visible_links, "visible_lane_candidates": visible_lanes,
            "overlay": str(target),
        })
    manifest = {"schema_version": "uav.ycx-video-overlay/v1", "items": summary}
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--credentials-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--timestamp-sec", type=float, default=0.0)
    args = parser.parse_args()
    result = asyncio.run(render(args.credentials_file, args.output_dir, args.timestamp_sec))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
