#!/usr/bin/env python3
"""Attach registration-time GCJ-02 motion references to verified demo maps.

The operation is restricted to the registered local replay catalog and updates
only ``uav_visual_registrations.residuals``.  Raw assets, map geometry, YCX,
tracks and source master data are never modified.  Dry-run is the default.
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
sys.path.insert(0, str(ROOT))

from app.core.database import async_session_maker, close_db  # noqa: E402
from app.models.mission import VisualRegistration  # noqa: E402
from app.models.survey import AuditLog  # noqa: E402
from bootstrap_mp4new_sources import LOCAL_REPLAY_CATALOG  # noqa: E402
from render_ycx_video_overlays import _telemetry  # noqa: E402


CONFIRMATION = "BACKFILL-VERIFIED-REGISTRATION-MOTION-REFERENCES"


def _catalog() -> dict[str, dict]:
    return {
        source["profile_id"]: source
        for intersection in LOCAL_REPLAY_CATALOG
        for source in intersection["sources"]
    }


async def backfill(execute: bool, confirmation: str | None) -> dict:
    catalog = _catalog()
    async with async_session_maker() as session:
        rows = (
            await session.execute(
                select(VisualRegistration).where(
                    VisualRegistration.source_profile_id.in_(tuple(catalog)),
                    VisualRegistration.status == "verified",
                )
            )
        ).scalars().all()
        by_source = {row.source_profile_id: row for row in rows}
        missing = sorted(set(catalog) - set(by_source))
        extra_duplicates = len(rows) != len(by_source)
        if missing or extra_duplicates:
            raise RuntimeError(
                f"expected one verified registration per source; missing={missing}, "
                f"duplicates={extra_duplicates}"
            )

        changes = []
        prepared: dict[str, dict] = {}
        for profile_id, source in sorted(catalog.items()):
            row = by_source[profile_id]
            residuals = dict(row.residuals or {})
            timestamp = float(residuals.get("video_timestamp_sec", 0.0))
            telemetry = _telemetry(source, timestamp)
            position = telemetry.get("position_gcj02") or {}
            reference = [position.get("longitude"), position.get("latitude")]
            if any(value is None for value in reference):
                raise RuntimeError(f"GCJ-02 telemetry unavailable for {profile_id}")
            next_residuals = {
                **residuals,
                "registration_position_gcj02": reference,
                "registration_gimbal_yaw_deg": telemetry.get("gimbal_yaw", 0) or 0,
                "coordinate_system": "GCJ02",
            }
            prepared[profile_id] = next_residuals
            changes.append(
                {
                    "source_profile_id": profile_id,
                    "registration_id": row.id,
                    "video_timestamp_sec": timestamp,
                    "registration_position_gcj02": reference,
                    "changed": next_residuals != residuals,
                }
            )

        result = {
            "schema_version": "uav.registration-motion-reference/v1",
            "mode": "execute" if execute else "dry-run",
            "registrations": changes,
            "count": len(changes),
            "preserved": [
                "YCX read-only database",
                "channelized map geometry",
                "raw assets",
                "source master data",
                "trajectory business facts",
            ],
        }
        if not execute:
            result["passed"] = len(changes) == len(catalog)
            return result
        if os.environ.get("ALLOW_REGISTRATION_REFERENCE_BACKFILL") != "1":
            raise RuntimeError("set ALLOW_REGISTRATION_REFERENCE_BACKFILL=1 before execution")
        if confirmation != CONFIRMATION:
            raise RuntimeError(f"pass --confirm {CONFIRMATION}")
        for profile_id, residuals in prepared.items():
            by_source[profile_id].residuals = residuals
        session.add(
            AuditLog(
                action="visual_registration_motion_reference_backfilled",
                target_type="visual_registration_batch",
                target_id="local-replay-catalog",
                after_value={"source_profile_ids": sorted(catalog), "count": len(catalog)},
                reason="lock runtime trajectory projection to exact source imagery registration",
                request_id=f"registration-reference-{uuid.uuid4().hex}",
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

