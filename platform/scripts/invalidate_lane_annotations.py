#!/usr/bin/env python3
"""Invalidate current lane annotations in road9 and the calibration volume."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select, update

PLATFORM_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_DIR))

from app.core.config import settings  # noqa: E402
from app.core.database import async_session_maker, close_db, init_db  # noqa: E402
from app.models.mission import LaneAnnotationTaskRecord, VisualLaneBinding  # noqa: E402
from app.services.lane_annotation_store import LaneAnnotationStore  # noqa: E402

REASON = "video_sources_without_lane_annotations"


async def invalidate(*, apply: bool) -> dict:
    if not await init_db():
        raise RuntimeError("road9 initialization failed")
    now = datetime.now(UTC)
    try:
        async with async_session_maker() as session:
            active_bindings = await session.scalar(
                select(func.count()).select_from(VisualLaneBinding).where(
                    VisualLaneBinding.retired_at.is_(None)
                )
            )
            active_tasks = await session.scalar(
                select(func.count()).select_from(LaneAnnotationTaskRecord).where(
                    LaneAnnotationTaskRecord.status != "invalidated"
                )
            )
            if apply:
                await session.execute(
                    update(VisualLaneBinding)
                    .where(VisualLaneBinding.retired_at.is_(None))
                    .values(status="retired", retired_at=now, roads_json=None)
                )
                await session.execute(
                    update(LaneAnnotationTaskRecord)
                    .where(LaneAnnotationTaskRecord.status != "invalidated")
                    .values(
                        status="invalidated",
                        revision=LaneAnnotationTaskRecord.revision + 1,
                        updated_at=now,
                    )
                )
                await session.commit()
            else:
                await session.rollback()

        store = LaneAnnotationStore(settings.lane_annotation_db_path)
        file_result = (
            store.invalidate_all(REASON)
            if apply
            else {
                "invalidated_annotations": len(store.list_annotations()),
                "invalidated_tasks": sum(
                    task.get("status") != "invalidated" for task in store.list_tasks()
                ),
                "archived_exports": [
                    str(path) for path in sorted(store.export_dir.glob("*.json"))
                ],
                "reason": REASON,
            }
        )
        return {
            "schema_version": "uav.lane-annotation-invalidation/v1",
            "mode": "apply" if apply else "check",
            "road9": {
                "bindings": int(active_bindings or 0),
                "tasks": int(active_tasks or 0),
            },
            "calibration_store": file_result,
            "passed": True,
        }
    finally:
        await close_db()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="perform invalidation; without this flag only report current active data",
    )
    args = parser.parse_args()
    print(json.dumps(asyncio.run(invalidate(apply=args.apply)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
