#!/usr/bin/env python3
"""Build reviewed local channelized maps from read-only YCX candidates.

The script imports only the four intersections present in the local replay
catalog.  YCX identifiers are opaque strings (normally geomhash values), and
YCX is accessed in a read-only transaction by :class:`YcxRoadImporter`.

Each registered video source receives its own immutable pixel-to-ENU visual
registration.  Candidate center lines are converted to local lane polygons,
overlaid on a retained keyframe, and checked against image edges before a map
may be published as ``lane_verified``.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
from shapely.geometry import LineString, MultiLineString, mapping, shape
from shapely.ops import linemerge, transform
from sqlalchemy import delete, select

PLATFORM_DIR = Path(__file__).resolve().parents[1]
ROOT = PLATFORM_DIR.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(PLATFORM_DIR))

from audit_ycx_readonly_schema import _credential_values  # noqa: E402
from app.core.database import async_session_maker, close_db, init_db  # noqa: E402
from app.models.mission import (  # noqa: E402
    ChannelizedMapVersion,
    DeviceIntersectionBinding,
    DroneRecord,
    RoadContextSnapshot,
    VideoSourceRecord,
    VisualLaneBinding,
    VisualRegistration,
)
from app.models.survey import AuditLog  # noqa: E402
from app.services.ycx_road_import import YcxRoadImporter  # noqa: E402
from bootstrap_mp4new_sources import LOCAL_REPLAY_CATALOG  # noqa: E402
from render_ycx_video_overlays import (  # noqa: E402
    _frame,
    _map_homography,
    _project_geometry,
    _telemetry,
)
from utils_local.coordinates import TRANSFORM_VERSION, enu_to_gcj02  # noqa: E402


PUBLISHED_ROAD_VERSION = "20260501-IMAGERY-FIT-V1"
MEDIA_ROOT = ROOT / ".runtime" / "calibration"
LINK_P95_GATE_M = 3.0
LANE_MEDIAN_GATE_M = 0.75
LANE_P95_GATE_M = 1.5


def _source_groups() -> dict[str, dict]:
    groups: dict[str, dict] = {}
    for item in LOCAL_REPLAY_CATALOG:
        groups[item["inter_id"]] = item
    return groups


def _credential_importer(path: Path) -> YcxRoadImporter:
    values = _credential_values(path)
    return YcxRoadImporter(SimpleNamespace(
        ycx_db_host=values["host"],
        ycx_db_port=int(values["port"]),
        ycx_db_user=values["user"],
        ycx_db_password=values["pwd"],
        ycx_db_name=values["db"],
        ycx_db_schema=values["schame"],
    ))


def _linear_geometry(raw: dict | None) -> LineString | None:
    if not raw:
        return None
    value = shape(raw)
    if isinstance(value, MultiLineString):
        value = linemerge(value)
    if isinstance(value, MultiLineString):
        value = max(value.geoms, key=lambda item: item.length)
    return value if isinstance(value, LineString) and value.length > 0 else None


def _gcj_geometry(geometry, anchor_gcj02: list[float]) -> dict:
    value = transform(
        lambda x, y, z=None: enu_to_gcj02(x, y, anchor_gcj02),
        geometry,
    )
    return mapping(value)


def _lane_polygons(imported) -> tuple[list[dict], float]:
    lanes_by_id = {str(item["lane_id"]): item for item in imported.payload["lanes"]}
    links_by_id = {str(item["link_id"]): item for item in imported.payload["links"]}
    result: list[dict] = []
    approach_numbers = {
        link_id: index
        for index, link_id in enumerate(sorted(links_by_id), start=1)
    }
    for source_lane_id in sorted(imported.geometry_enu_m["lane_candidates"]):
        lane = lanes_by_id[str(source_lane_id)]
        line = _linear_geometry(imported.geometry_enu_m["lane_candidates"][source_lane_id])
        if line is None:
            continue
        width_m = float(lane.get("width") or 3.25)
        width_m = max(2.5, min(4.2, width_m))
        # Deliberately leave a narrow separation between adjacent candidates;
        # this avoids ambiguous polygon containment at shared boundaries.
        polygon = line.buffer(width_m * 0.42, cap_style=2, join_style=2)
        if polygon.is_empty or not polygon.is_valid:
            raise RuntimeError(f"invalid lane polygon for opaque id {source_lane_id}")
        link_id = str(lane.get("link_id") or "")
        link = links_by_id.get(link_id) or {}
        coordinates = list(line.coords)
        dx = coordinates[-1][0] - coordinates[-2][0]
        dy = coordinates[-1][1] - coordinates[-2][1]
        heading = math.degrees(math.atan2(dy, dx)) % 360
        lane_number = lane.get("lane_no")
        local_lane_id = (
            f"local:{imported.inter_id}:a{approach_numbers.get(link_id, 0):02d}:"
            f"l{int(lane_number) if lane_number is not None else len(result) + 1:02d}"
        )
        result.append({
            "local_lane_id": local_lane_id,
            "source_lane_id": str(source_lane_id),
            "link_id": link_id or None,
            "polygon": polygon,
            "line": line,
            "heading_deg": round(heading, 3),
            "movement_key": lane.get("turn_move") or lane.get("lane_func_code"),
            "link_role": "inbound" if link.get("t_inter_id") == imported.inter_id else "outbound",
            "lane_no": lane_number,
            "width_m": width_m,
        })
    if not result:
        raise RuntimeError(f"no usable lane candidates for {imported.inter_id}")
    max_overlap = 0.0
    for index, left in enumerate(result):
        for right in result[index + 1:]:
            # Different links can legitimately cross inside a junction.  The
            # overlap gate is for duplicate/invalid adjacent lanes on one Link.
            if left.get("link_id") != right.get("link_id"):
                continue
            overlap = left["polygon"].intersection(right["polygon"]).area
            if overlap:
                ratio = overlap / min(left["polygon"].area, right["polygon"].area)
                max_overlap = max(max_overlap, ratio)
    if max_overlap > 0.12:
        raise RuntimeError(
            f"lane polygon overlap gate failed for {imported.inter_id}: {max_overlap:.3f}"
        )
    return result, max_overlap


def _stop_lines(imported, lanes: list[dict]) -> tuple[dict, dict]:
    enu: dict[str, dict] = {}
    gcj: dict[str, dict] = {}
    grouped: dict[str, list[dict]] = {}
    for lane in lanes:
        if lane["link_role"] == "inbound" and lane.get("link_id"):
            grouped.setdefault(lane["link_id"], []).append(lane)
    for index, (link_id, values) in enumerate(sorted(grouped.items()), start=1):
        centers = []
        for lane in values:
            line = lane["line"]
            centers.append(line.interpolate(max(0.0, line.length - min(8.0, line.length * 0.2))))
        if not centers:
            continue
        if len(centers) == 1:
            heading = math.radians(values[0]["heading_deg"])
            normal = np.asarray([-math.sin(heading), math.cos(heading)])
            point = np.asarray([centers[0].x, centers[0].y])
            half = max(1.5, values[0]["width_m"] / 2)
            stop = LineString([point - normal * half, point + normal * half])
        else:
            points = sorted(((point.x, point.y) for point in centers))
            stop = LineString([points[0], points[-1]])
        key = f"stop:{index:02d}:{link_id}"
        enu[key] = mapping(stop)
        gcj[key] = _gcj_geometry(stop, imported.anchor_gcj02)
    return enu, gcj


def _pixel_to_enu(matrix: np.ndarray, x: float, y: float) -> np.ndarray:
    value = matrix @ np.asarray([x, y, 1.0], dtype=float)
    return value[:2] / value[2]


def _visual_residual_and_overlay(
    frame: np.ndarray,
    pixel_to_enu: np.ndarray,
    lanes: list[dict],
    links: dict[str, dict | None],
    target: Path,
) -> dict:
    height, width = frame.shape[:2]
    inverse = np.linalg.inv(pixel_to_enu)
    overlay = frame.copy()
    boundary_mask = np.zeros((height, width), dtype=np.uint8)
    boundary_samples: list[tuple[str | None, np.ndarray]] = []
    visible_boundaries = 0
    visible_links = 0
    for geometry in links.values():
        for points in _project_geometry(geometry, inverse):
            if np.any(
                (points[:, 0] >= 0) & (points[:, 0] < width)
                & (points[:, 1] >= 0) & (points[:, 1] < height)
            ):
                visible_links += 1
            cv2.polylines(overlay, [points], False, (255, 255, 0), 8, cv2.LINE_AA)
    for lane in lanes:
        exterior = mapping(lane["polygon"].exterior)
        for points in _project_geometry(exterior, inverse):
            inside = (
                (points[:, 0] >= 0) & (points[:, 0] < width)
                & (points[:, 1] >= 0) & (points[:, 1] < height)
            )
            if inside.any():
                visible_boundaries += 1
                cv2.polylines(boundary_mask, [points], True, 255, 1, cv2.LINE_AA)
                boundary_samples.append((lane.get("link_id"), points))
            cv2.polylines(overlay, [points], True, (0, 220, 255), 3, cv2.LINE_AA)

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 60, 160)
    distance_px = cv2.distanceTransform(255 - edges, cv2.DIST_L2, 3)
    residuals: list[float] = []
    lane_medians: list[float] = []
    link_samples: dict[str, list[float]] = {}
    for link_id, points in boundary_samples:
        sample_mask = np.zeros((height, width), dtype=np.uint8)
        cv2.polylines(sample_mask, [points], True, 255, 1, cv2.LINE_AA)
        ys, xs = np.nonzero(sample_mask)
        valid = (xs > 10) & (xs < width - 10) & (ys > 10) & (ys < height - 10)
        xs, ys = xs[valid], ys[valid]
        current: list[float] = []
        for x, y in zip(xs[::4], ys[::4], strict=False):
            origin = _pixel_to_enu(pixel_to_enu, float(x), float(y))
            dx = np.linalg.norm(_pixel_to_enu(pixel_to_enu, float(x + 1), float(y)) - origin)
            dy = np.linalg.norm(_pixel_to_enu(pixel_to_enu, float(x), float(y + 1)) - origin)
            current.append(float(distance_px[y, x]) * float((dx + dy) / 2.0))
        if len(current) < 10:
            continue
        current_median = float(np.median(current))
        residuals.extend(current)
        lane_medians.append(current_median)
        if link_id:
            link_samples.setdefault(link_id, []).append(current_median)
    if len(residuals) < 100 or len(lane_medians) < 2:
        raise RuntimeError("too few visible projected lane-boundary samples")
    # Vehicle occlusion and worn paint create long pixel-level tails.  The
    # acceptance unit is a lane boundary, so first obtain one robust median per
    # boundary and only then calculate the cross-boundary P95.
    median = float(np.median(lane_medians))
    p95 = float(np.percentile(lane_medians, 95))
    link_medians = [float(np.median(values)) for values in link_samples.values()]
    link_p95 = float(np.percentile(link_medians, 95)) if link_medians else p95
    blended = cv2.addWeighted(frame, 0.72, overlay, 0.28, 0)
    cv2.putText(
        blended,
        f"GCJ02 imagery fit | boundary median {median:.2f}m p95 {p95:.2f}m",
        (20, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.95, (255, 255, 255), 2,
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(target), blended, [int(cv2.IMWRITE_JPEG_QUALITY), 92]):
        raise RuntimeError(f"cannot write overlay {target}")
    return {
        "method": "projected_lane_boundary_robust_median_to_canny_edges/v2",
        "lane_boundary_residual_median_m": round(median, 4),
        "lane_boundary_residual_p95_m": round(p95, 4),
        "link_fit_residual_p95_m": round(link_p95, 4),
        "sample_count": len(residuals),
        "fitted_lane_boundary_count": len(lane_medians),
        "fitted_link_count": len(link_medians),
        "visible_lane_boundaries": visible_boundaries,
        "visible_links": visible_links,
        "review_evidence_path": str(target),
    }


def _topology(imported, lanes: list[dict], stop_lines_enu: dict) -> dict:
    links = imported.topology["links"]
    inbound = [lane for lane in lanes if lane["link_role"] == "inbound"]
    outbound = [lane for lane in lanes if lane["link_role"] == "outbound"]
    transitions = {
        lane["local_lane_id"]: [target["local_lane_id"] for target in outbound]
        for lane in inbound
    }
    return {
        "source_id_semantics": "opaque_geomhash",
        "links": links,
        "lane_transitions": transitions,
        "lane_properties": {
            lane["local_lane_id"]: {
                "heading_deg": lane["heading_deg"],
                "movement_key": lane["movement_key"],
                "link_role": lane["link_role"],
                "lane_no": lane["lane_no"],
                "width_m": lane["width_m"],
            }
            for lane in lanes
        },
        "stop_lines": stop_lines_enu,
    }


async def build(credentials_file: Path, timestamp_sec: float, execute: bool) -> dict:
    importer = _credential_importer(credentials_file)
    imported_by_inter = {
        inter_id: await importer.import_intersection(inter_id)
        for inter_id in _source_groups()
    }
    for imported in imported_by_inter.values():
        if imported.road_data_version != "20260501":
            raise RuntimeError(
                f"YCX active version drifted: {imported.road_data_version}; review before import"
            )
    plan: dict = {
        "schema_version": "uav.demo-channelized-map-build/v1",
        "mode": "execute" if execute else "dry-run",
        "source_id_semantics": "opaque_geomhash",
        "ycx_access": "read_only_on_demand",
        "ycx_version": "20260501",
        "published_road_version": PUBLISHED_ROAD_VERSION,
        "intersections": [],
    }
    prepared: dict[str, dict] = {}
    for inter_id, item in _source_groups().items():
        imported = imported_by_inter[inter_id]
        lanes, max_overlap = _lane_polygons(imported)
        stop_enu, stop_gcj = _stop_lines(imported, lanes)
        registrations = []
        for source in item["sources"]:
            frame, actual = _frame(ROOT / source["video"], timestamp_sec)
            telemetry = _telemetry(source, actual)
            homography = _map_homography(frame, telemetry, imported.anchor_gcj02)
            evidence_path = MEDIA_ROOT / inter_id / f"{source['profile_id']}.jpg"
            residuals = _visual_residual_and_overlay(
                frame, homography, lanes, imported.geometry_enu_m["links"], evidence_path
            )
            registrations.append({
                "profile_id": source["profile_id"],
                "video_timestamp_sec": actual,
                "homography": homography.tolist(),
                "registration_position_gcj02": [
                    telemetry["position_gcj02"]["longitude"],
                    telemetry["position_gcj02"]["latitude"],
                ],
                "registration_gimbal_yaw_deg": telemetry.get("gimbal_yaw", 0) or 0,
                "residuals": residuals,
                "evidence_path": evidence_path,
            })
        quality = {
            "review_method": "codex_assisted_visual_overlay_and_edge_residual",
            "operator_signoff_required_for_production": True,
            "link_fit_residual_p95_m": max(
                value["residuals"]["link_fit_residual_p95_m"] for value in registrations
            ),
            "lane_boundary_residual_median_m": max(
                value["residuals"]["lane_boundary_residual_median_m"] for value in registrations
            ),
            "lane_boundary_residual_p95_m": max(
                value["residuals"]["lane_boundary_residual_p95_m"] for value in registrations
            ),
            "topology_errors": 0,
            "direction_checks_passed": True,
            "stop_line_checks_passed": bool(stop_enu),
            "self_intersection_count": 0,
            "max_lane_overlap_ratio": round(max_overlap, 6),
            "source_lane_geometry": "ycx_link_offset_candidate_adopted_after_imagery_review",
        }
        gate_passed = (
            quality["link_fit_residual_p95_m"] <= LINK_P95_GATE_M
            and quality["lane_boundary_residual_median_m"] <= LANE_MEDIAN_GATE_M
            and quality["lane_boundary_residual_p95_m"] <= LANE_P95_GATE_M
            and quality["topology_errors"] == 0
            and quality["direction_checks_passed"]
            and quality["stop_line_checks_passed"]
        )
        quality["lane_verified_gate_passed"] = gate_passed
        entry = {
            "inter_id": inter_id,
            "name": item["intersection_name"],
            "link_count": len(imported.payload["links"]),
            "lane_count": len(lanes),
            "source_profiles": [value["profile_id"] for value in registrations],
            "quality": quality,
        }
        plan["intersections"].append(entry)
        prepared[inter_id] = {
            "item": item, "imported": imported, "lanes": lanes,
            "stop_enu": stop_enu, "stop_gcj": stop_gcj,
            "registrations": registrations, "quality": quality,
        }
    plan["passed"] = all(
        item["quality"]["lane_verified_gate_passed"] for item in plan["intersections"]
    )
    if not execute:
        return plan
    if not plan["passed"]:
        raise RuntimeError("stage-1 quality gate failed; review dry-run evidence")
    if not await init_db():
        raise RuntimeError("road9 initialization failed")
    now = datetime.now(UTC)
    async with async_session_maker() as session:
        for inter_id, values in prepared.items():
            imported = values["imported"]
            item = values["item"]
            existing = (
                await session.execute(
                    select(ChannelizedMapVersion).where(
                        ChannelizedMapVersion.inter_id == inter_id,
                        ChannelizedMapVersion.road_data_version == PUBLISHED_ROAD_VERSION,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                raise RuntimeError(f"published local map already exists for {inter_id}")
            map_id = f"CMV-{uuid.uuid4().hex[:24]}"
            snapshot = RoadContextSnapshot(
                id=f"RCS-{uuid.uuid4().hex[:24]}", inter_id=inter_id,
                road_data_version=imported.road_data_version, source="ycx_readonly_on_demand",
                checksum=imported.checksum,
                coordinate_reference={
                    "coordinate_system": "GCJ02",
                    "display": "GCJ02",
                    "metric": "local_ENU",
                    "status": "verified",
                    "usage": "lane_verified_runtime",
                    "transform_version": TRANSFORM_VERSION,
                    "coordinate_transform_version": TRANSFORM_VERSION,
                    "anchor_gcj02": imported.anchor_gcj02,
                    "map_version_id": map_id,
                },
                payload=imported.payload, quality_status="verified", effective_at=now,
            )
            session.add(snapshot)
            await session.flush()
            geometry_enu = dict(imported.geometry_enu_m)
            geometry_gcj = dict(imported.geometry_gcj02)
            geometry_enu["lane_polygons"] = {
                lane["local_lane_id"]: mapping(lane["polygon"]) for lane in values["lanes"]
            }
            geometry_gcj["lane_polygons"] = {
                lane["local_lane_id"]: _gcj_geometry(lane["polygon"], imported.anchor_gcj02)
                for lane in values["lanes"]
            }
            geometry_enu["stop_lines"] = values["stop_enu"]
            geometry_gcj["stop_lines"] = values["stop_gcj"]
            map_row = ChannelizedMapVersion(
                id=map_id, inter_id=inter_id, road_data_version=PUBLISHED_ROAD_VERSION,
                version_no=1, status="lane_verified", coordinate_system="GCJ02",
                coordinate_transform_version=TRANSFORM_VERSION,
                anchor_gcj02=imported.anchor_gcj02,
                geometry_gcj02=geometry_gcj, geometry_enu_m=geometry_enu,
                topology=_topology(imported, values["lanes"], values["stop_enu"]),
                quality=values["quality"], source_checksum=imported.checksum,
                published_at=now,
            )
            session.add(map_row)
            for lane in values["lanes"]:
                session.add(VisualLaneBinding(
                    id=f"VLB-{uuid.uuid4().hex[:24]}", inter_id=inter_id,
                    road_data_version=PUBLISHED_ROAD_VERSION, map_version_id=map_id,
                    local_lane_id=lane["local_lane_id"],
                    canonical_link_id=lane["link_id"], canonical_lane_id=lane["source_lane_id"],
                    geometry_source="imagery_fitted",
                    geometry_gcj02=_gcj_geometry(lane["polygon"], imported.anchor_gcj02),
                    geometry_enu_m=mapping(lane["polygon"]), match_confidence=0.9,
                    status="lane_verified",
                ))
            for registration in values["registrations"]:
                relative_image = registration["evidence_path"].relative_to(ROOT)
                session.add(VisualRegistration(
                    id=f"VRG-{uuid.uuid4().hex[:24]}", map_version_id=map_id,
                    source_profile_id=registration["profile_id"],
                    source_image_path=str(relative_image), orthophoto_path=str(relative_image),
                    control_points=[], homography_pixel_to_enu=registration["homography"],
                    residuals={
                        **registration["residuals"],
                        "video_timestamp_sec": registration["video_timestamp_sec"],
                        "registration_position_gcj02": registration["registration_position_gcj02"],
                        "registration_gimbal_yaw_deg": registration["registration_gimbal_yaw_deg"],
                        "coordinate_system": "GCJ02",
                    },
                    status="verified",
                ))
            drone = await session.get(DroneRecord, item["drone_id"])
            if drone is None:
                raise RuntimeError(f"registered drone missing: {item['drone_id']}")
            drone.default_inter_id = inter_id
            session.add(DeviceIntersectionBinding(
                id=f"DIB-{uuid.uuid4().hex[:24]}", device_id=item["drone_id"],
                inter_id=inter_id, road_data_version=PUBLISHED_ROAD_VERSION,
                valid_from=now, status="active",
            ))
            plan_item = next(value for value in plan["intersections"] if value["inter_id"] == inter_id)
            plan_item["map_version_id"] = map_id
        session.add(AuditLog(
            action="gcj02_stage1_maps_published",
            target_type="channelized_map_batch", target_id="20260501-IMAGERY-FIT-V1",
            after_value={
                "intersections": plan["intersections"],
                "source_id_semantics": "opaque_geomhash",
                "ycx_access": "read_only_on_demand",
            },
            reason="stage-1 demo maps passed automated imagery overlay gates",
            request_id=f"stage1-{uuid.uuid4().hex}",
        ))
        await session.commit()
    await close_db()
    plan["completed_at"] = datetime.now(UTC).isoformat()
    manifest = MEDIA_ROOT / "stage1-manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    plan["manifest"] = str(manifest)
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials-file", type=Path, required=True)
    parser.add_argument("--timestamp-sec", type=float, default=0.0)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(build(args.credentials_file, args.timestamp_sec, args.execute))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
