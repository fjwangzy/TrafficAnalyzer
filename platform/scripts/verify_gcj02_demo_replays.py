#!/usr/bin/env python3
"""Strict database/artifact verification for the two-stage GCJ-02 demo replay."""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
from pathlib import Path

from shapely.geometry import Point, shape
from sqlalchemy import select

PLATFORM_DIR = Path(__file__).resolve().parents[1]
ROOT = PLATFORM_DIR.parent
sys.path.insert(0, str(PLATFORM_DIR))
sys.path.insert(0, str(ROOT))

from app.core.database import async_session_maker, close_db  # noqa: E402
from app.models.metrics import TrackEvent  # noqa: E402
from app.models.mission import (  # noqa: E402
    ChannelizedMapVersion,
    MissionRecord,
    PipelineRecord,
    VisualLaneBinding,
    VisualRegistration,
)
from scripts.bootstrap_mp4new_sources import LOCAL_REPLAY_CATALOG  # noqa: E402
from utils_local.coordinates import enu_to_gcj02  # noqa: E402


FORBIDDEN_PUBLIC_KEYS = {
    "world_anchor_lat_lon",
    "trajectory_world_m",
    "trajectory_wgs84",
    "position_wgs84",
    "geometry_wgs84",
}


def _profiles() -> set[str]:
    return {
        source["profile_id"]
        for intersection in LOCAL_REPLAY_CATALOG
        for source in intersection["sources"]
    }


def _load_results(
    output_dir: Path,
    profile_ids: set[str] | None = None,
) -> dict[str, dict]:
    selected = profile_ids or _profiles()
    unknown = selected - _profiles()
    if unknown:
        raise RuntimeError(f"unknown replay sources: {', '.join(sorted(unknown))}")
    results = {}
    for profile_id in sorted(selected):
        path = output_dir / profile_id / "result.json"
        if not path.is_file():
            raise RuntimeError(f"missing result artifact: {profile_id}")
        result = json.loads(path.read_text(encoding="utf-8"))
        if not result.get("passed"):
            raise RuntimeError(f"failed result artifact: {profile_id}")
        results[profile_id] = result
    return results


def _forbidden_keys(value) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_PUBLIC_KEYS:
                found.add(key)
            found.update(_forbidden_keys(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_forbidden_keys(child))
    return found


def _sample_evenly(items: list, limit: int) -> list:
    if len(items) <= limit:
        return items
    return [items[math.floor(index * len(items) / limit)] for index in range(limit)]


def _coordinate_error_m(track: TrackEvent, anchor: list[float]) -> float | None:
    enu = track.trajectory_enu_m or []
    gcj = track.trajectory_gcj02 or []
    if not enu or len(enu) != len(gcj):
        return None
    errors = []
    for enu_point, gcj_point in zip(enu, gcj):
        if len(enu_point) < 2 or len(gcj_point) < 2:
            continue
        lon, lat = enu_to_gcj02(float(enu_point[0]), float(enu_point[1]), anchor)
        # Local equirectangular error is sufficient at intersection scale.
        dx = (lon - float(gcj_point[0])) * 111_320 * math.cos(math.radians(lat))
        dy = (lat - float(gcj_point[1])) * 110_540
        errors.append(math.hypot(dx, dy))
    return max(errors) if errors else None


async def verify(
    output_dir: Path,
    sample_per_source: int,
    *,
    profile_ids: set[str] | None = None,
    minimum_samples: int = 100,
) -> dict:
    results = _load_results(output_dir, profile_ids)
    selected_profiles = set(results)
    source_reports = []
    all_spatial_checks: list[bool] = []
    all_coordinate_errors: list[float] = []
    async with async_session_maker() as session:
        registrations = (await session.execute(
            select(VisualRegistration).where(VisualRegistration.status == "verified")
        )).scalars().all()
        registered_profiles = {item.source_profile_id for item in registrations}
        if not selected_profiles.issubset(registered_profiles):
            raise RuntimeError(
                "selected replay sources are missing verified registrations: "
                f"missing={sorted(selected_profiles - registered_profiles)}"
            )

        for profile_id, result in results.items():
            map_version = await session.get(ChannelizedMapVersion, result["map_version_id"])
            if map_version is None:
                raise RuntimeError(f"missing map version for {profile_id}")
            if map_version.status != "lane_verified" or map_version.coordinate_system != "GCJ02":
                raise RuntimeError(f"map is not lane_verified GCJ02: {profile_id}")
            bindings = (await session.execute(
                select(VisualLaneBinding).where(
                    VisualLaneBinding.map_version_id == map_version.id,
                    VisualLaneBinding.status == "lane_verified",
                )
            )).scalars().all()
            polygons = {
                binding.local_lane_id: shape(binding.geometry_enu_m)
                for binding in bindings
            }
            tracks = (await session.execute(
                select(TrackEvent)
                .where(
                    TrackEvent.pipeline_id == result["pipeline_id"],
                    TrackEvent.source_profile_id == profile_id,
                )
                .order_by(TrackEvent.ended_at, TrackEvent.track_id)
            )).scalars().all()
            if len(tracks) != int(result["trajectory_count"]):
                raise RuntimeError(
                    f"Kafka/DB mismatch for {profile_id}: "
                    f"capture={result['trajectory_count']} db={len(tracks)}"
                )
            missions = {track.mission_id for track in tracks}
            if len(missions) != 1 or None in missions:
                raise RuntimeError(f"tracks are not linked to one Mission: {profile_id}")
            mission = await session.get(MissionRecord, next(iter(missions)))
            if mission is None or mission.status != "completed":
                raise RuntimeError(f"completed Mission unavailable: {profile_id}")
            pipeline = await session.get(PipelineRecord, result["pipeline_id"])
            if (
                pipeline is None
                or pipeline.mission_id != mission.id
                or pipeline.observed_status != "stopped"
            ):
                raise RuntimeError(f"stopped Pipeline lineage unavailable: {profile_id}")
            provenance = mission.context_snapshot or {}
            if provenance.get("pipeline_id") != result["pipeline_id"]:
                raise RuntimeError(f"Mission pipeline provenance mismatch: {profile_id}")
            if provenance.get("runtime_map", {}).get("map_version_id") != map_version.id:
                raise RuntimeError(f"Mission map provenance mismatch: {profile_id}")
            for input_name in ("video", "telemetry"):
                if len(provenance.get("input_files", {}).get(input_name, {}).get("sha256", "")) != 64:
                    raise RuntimeError(f"Mission {input_name} hash unavailable: {profile_id}")
            if len(provenance.get("model", {}).get("sha256", "")) != 64:
                raise RuntimeError(f"Mission model hash unavailable: {profile_id}")

            forbidden = set().union(*(_forbidden_keys(track.payload) for track in tracks)) if tracks else set()
            if forbidden:
                raise RuntimeError(f"retired coordinate keys found for {profile_id}: {sorted(forbidden)}")
            coordinate_complete = [
                track for track in tracks
                if len(track.trajectory_enu_m or []) >= 2
                and len(track.trajectory_gcj02 or []) == len(track.trajectory_enu_m or [])
                and track.anchor_gcj02 == map_version.anchor_gcj02
                and track.map_version_id == map_version.id
            ]
            matched = [
                track for track in coordinate_complete
                if track.matched_lane_key in polygons
                and track.map_version_id == map_version.id
                and track.matched_link_id
                and track.source_lane_id
                and track.map_match_confidence is not None
            ]
            sampled = _sample_evenly(matched, sample_per_source)
            spatial_checks = []
            coordinate_errors = []
            sample_details = []
            for track in sampled:
                polygon = polygons[track.matched_lane_key]
                points = [Point(float(item[0]), float(item[1])) for item in track.trajectory_enu_m]
                # The event stores the last confirmed lane. A trajectory may end
                # after leaving it, so consistency means the path actually came
                # within the matcher search radius of that lane.
                minimum_lane_distance_m = min(polygon.distance(point) for point in points)
                spatial_checks.append(minimum_lane_distance_m <= 4.0)
                error = _coordinate_error_m(track, map_version.anchor_gcj02)
                if error is not None:
                    coordinate_errors.append(error)
                sample_details.append({
                    "track_event_id": track.id,
                    "track_id": track.track_id,
                    "started_at": track.started_at.isoformat() if track.started_at else None,
                    "ended_at": track.ended_at.isoformat() if track.ended_at else None,
                    "trajectory_point_count": len(track.trajectory_enu_m or []),
                    "matched_lane_key": track.matched_lane_key,
                    "source_lane_id": track.source_lane_id,
                    "matched_link_id": track.matched_link_id,
                    "movement_key": track.movement_key,
                    "map_match_confidence": track.map_match_confidence,
                    "minimum_lane_distance_m": round(minimum_lane_distance_m, 4),
                    "max_gcj02_roundtrip_error_m": round(error, 4) if error is not None else None,
                })
            all_spatial_checks.extend(spatial_checks)
            all_coordinate_errors.extend(coordinate_errors)
            source_reports.append({
                "profile_id": profile_id,
                "mission_id": mission.id,
                "pipeline_id": result["pipeline_id"],
                "map_version_id": map_version.id,
                "track_count": len(tracks),
                "coordinate_complete_tracks": len(coordinate_complete),
                "map_lineage_complete": len(coordinate_complete) == len(tracks),
                "matched_tracks": len(matched),
                "map_match_coverage": round(len(matched) / len(tracks), 4) if tracks else 0.0,
                "sampled_tracks": len(sampled),
                "samples": sample_details,
                "spatial_consistency": (
                    round(sum(spatial_checks) / len(spatial_checks), 4) if spatial_checks else 0.0
                ),
                "max_gcj02_roundtrip_error_m": (
                    round(max(coordinate_errors), 4) if coordinate_errors else None
                ),
                "input_hashes_present": True,
                "retired_coordinate_keys": [],
            })

    total_sampled = len(all_spatial_checks)
    consistency = sum(all_spatial_checks) / total_sampled if total_sampled else 0.0
    checks = {
        "all_selected_sources_passed": len(source_reports) == len(selected_profiles),
        "sample_size_meets_requested_minimum": total_sampled >= minimum_samples,
        "automated_spatial_consistency_at_least_95pct": consistency >= 0.95,
        "gcj02_roundtrip_error_at_most_0_5m": (
            bool(all_coordinate_errors) and max(all_coordinate_errors) <= 0.5
        ),
        "all_sources_have_tracks": all(item["track_count"] > 0 for item in source_reports),
        "all_tracks_have_coordinate_and_map_lineage": all(
            item["map_lineage_complete"] for item in source_reports
        ),
        "all_sources_have_map_matches": all(item["matched_tracks"] > 0 for item in source_reports),
    }
    report = {
        "schema_version": "uav.gcj02-demo-verification/v1",
        "verification_scope": "automated technical demo gate",
        "operator_lane_accuracy_review": "required_for_production_signoff",
        "selected_source_profiles": sorted(selected_profiles),
        "minimum_sample_count": minimum_samples,
        "source_count": len(source_reports),
        "track_count": sum(item["track_count"] for item in source_reports),
        "matched_track_count": sum(item["matched_tracks"] for item in source_reports),
        "sampled_track_count": total_sampled,
        "automated_spatial_consistency": round(consistency, 4),
        "max_gcj02_roundtrip_error_m": (
            round(max(all_coordinate_errors), 4) if all_coordinate_errors else None
        ),
        "checks": checks,
        "items": source_reports,
        "passed": all(checks.values()),
    }
    if not report["passed"]:
        failed = [name for name, passed in checks.items() if not passed]
        raise RuntimeError(json.dumps({"failed_checks": failed, "report": report}, ensure_ascii=False))
    return report


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "output/native-mps/gcj02-map-projection-v3-20260722",
    )
    parser.add_argument("--sample-per-source", type=int, default=25)
    parser.add_argument("--minimum-samples", type=int, default=100)
    parser.add_argument(
        "--source",
        action="append",
        dest="sources",
        help="Verify only this finalized SourceProfile; repeat for multiple sources.",
    )
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        report = await verify(
            args.output_dir.resolve(),
            max(1, args.sample_per_source),
            profile_ids=set(args.sources) if args.sources else None,
            minimum_samples=max(1, args.minimum_samples),
        )
        rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
