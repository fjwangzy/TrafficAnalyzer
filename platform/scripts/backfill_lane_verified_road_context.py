#!/usr/bin/env python3
"""Expose published demo maps as verified GCJ-02 RoadContext snapshots.

The stage-one builder created immutable ``lane_verified`` maps from YCX
snapshots, but older builder runs left those source snapshots marked as
``candidate_only``.  Dashboard map eligibility is snapshot-backed, so this
bounded repair joins maps to snapshots by immutable source checksum and updates
only the snapshot quality/coordinate reference.  Dry-run is the default.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

from sqlalchemy import select

PLATFORM_DIR = Path(__file__).resolve().parents[1]
ROOT = PLATFORM_DIR.parent
sys.path.insert(0, str(PLATFORM_DIR))

from app.core.database import async_session_maker, close_db  # noqa: E402
from app.models.mission import ChannelizedMapVersion, RoadContextSnapshot  # noqa: E402
from app.models.survey import AuditLog  # noqa: E402
from scripts.bootstrap_mp4new_sources import LOCAL_REPLAY_CATALOG  # noqa: E402


CONFIRMATION = "BACKFILL-LANE-VERIFIED-ROAD-CONTEXT"


def _intersection_ids() -> set[str]:
    return {item["inter_id"] for item in LOCAL_REPLAY_CATALOG}


def _coordinate_reference(row: ChannelizedMapVersion) -> dict:
    return {
        "coordinate_system": "GCJ02",
        "display": "GCJ02",
        "metric": "local_ENU",
        "status": "verified",
        "usage": "lane_verified_runtime",
        "transform_version": row.coordinate_transform_version,
        "coordinate_transform_version": row.coordinate_transform_version,
        "anchor_gcj02": row.anchor_gcj02,
        "map_version_id": row.id,
    }


async def backfill(execute: bool, confirmation: str | None) -> dict:
    expected = _intersection_ids()
    async with async_session_maker() as session:
        maps = (
            await session.execute(
                select(ChannelizedMapVersion).where(
                    ChannelizedMapVersion.inter_id.in_(tuple(expected)),
                    ChannelizedMapVersion.status == "lane_verified",
                    ChannelizedMapVersion.coordinate_system == "GCJ02",
                )
            )
        ).scalars().all()
        by_intersection = {row.inter_id: row for row in maps}
        if set(by_intersection) != expected or len(maps) != len(by_intersection):
            raise RuntimeError(
                "expected one lane_verified GCJ02 map per registered intersection; "
                f"found={sorted(by_intersection)} expected={sorted(expected)}"
            )

        prepared: list[tuple[RoadContextSnapshot, dict]] = []
        items = []
        for inter_id, map_row in sorted(by_intersection.items()):
            predicates = [RoadContextSnapshot.inter_id == inter_id]
            if map_row.source_checksum:
                predicates.append(RoadContextSnapshot.checksum == map_row.source_checksum)
            else:
                predicates.append(
                    RoadContextSnapshot.road_data_version == map_row.road_data_version
                )
            snapshot = (
                await session.execute(
                    select(RoadContextSnapshot)
                    .where(*predicates)
                    .order_by(RoadContextSnapshot.created_at.desc())
                )
            ).scalars().first()
            if snapshot is None:
                raise RuntimeError(f"source RoadContext snapshot unavailable for {inter_id}")
            reference = _coordinate_reference(map_row)
            prepared.append((snapshot, reference))
            items.append(
                {
                    "inter_id": inter_id,
                    "map_version_id": map_row.id,
                    "snapshot_id": snapshot.id,
                    "before_quality_status": snapshot.quality_status,
                    "after_quality_status": "verified",
                    "anchor_gcj02": map_row.anchor_gcj02,
                    "changed": (
                        snapshot.quality_status != "verified"
                        or snapshot.coordinate_reference != reference
                    ),
                }
            )

        result = {
            "schema_version": "uav.lane-verified-road-context-backfill/v1",
            "mode": "execute" if execute else "dry-run",
            "count": len(items),
            "items": items,
            "preserved": [
                "YCX read-only database",
                "channelized map geometry",
                "visual registrations",
                "trajectory business facts",
                "raw assets",
            ],
        }
        if not execute:
            result["passed"] = len(items) == len(expected)
            return result
        if os.environ.get("ALLOW_ROAD_CONTEXT_BACKFILL") != "1":
            raise RuntimeError("set ALLOW_ROAD_CONTEXT_BACKFILL=1 before execution")
        if confirmation != CONFIRMATION:
            raise RuntimeError(f"pass --confirm {CONFIRMATION}")

        for snapshot, reference in prepared:
            snapshot.quality_status = "verified"
            snapshot.coordinate_reference = reference
        session.add(
            AuditLog(
                action="lane_verified_road_context_backfilled",
                target_type="road_context_snapshot_batch",
                target_id="registered-demo-intersections",
                after_value={
                    "intersection_ids": sorted(expected),
                    "map_version_ids": sorted(row.id for row in maps),
                },
                reason="publish lane_verified GCJ-02 map eligibility to Dashboard",
                request_id=f"road-context-backfill-{uuid.uuid4().hex}",
            )
        )
        await session.commit()
        result["passed"] = True
        return result


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm")
    args = parser.parse_args()
    try:
        result = await backfill(args.execute, args.confirm)
    finally:
        await close_db()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
