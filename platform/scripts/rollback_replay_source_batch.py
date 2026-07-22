#!/usr/bin/env python3
"""Rollback one failed local replay SourceProfile from road9.

The source is restricted to the registered replay catalog.  Dry-run is the
default.  Raw assets, source master data, maps, registrations, audit history,
and message inbox rows are deliberately preserved.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

from sqlalchemy import delete, select

PLATFORM_DIR = Path(__file__).resolve().parents[1]
ROOT = PLATFORM_DIR.parent
sys.path.insert(0, str(PLATFORM_DIR))
sys.path.insert(0, str(ROOT))

from app.core.database import async_session_maker, close_db  # noqa: E402
from app.models.metrics import (  # noqa: E402
    ConflictEvent, ConflictReview, TelemetryMetric, TrackEvent, TrackPoint, TrafficMetric,
)
from app.models.survey import (  # noqa: E402
    AiEvent, AuditLog, DeadLetter, EventDeliveryAttempt, EventOutbox,
    EvidenceItem, EvidencePackage,
)
from inventory_trajectory_replay import (  # noqa: E402
    KNOWN_SOURCE_PROFILES, collect_inventory,
)


CONFIRMATION = "ROLLBACK-ONE-FAILED-REPLAY-SOURCE"


async def rollback(source_profile_id: str, execute: bool, confirmation: str | None) -> dict:
    before = await collect_inventory((source_profile_id,))
    result = {
        "schema_version": "uav.replay-source-rollback/v1",
        "mode": "execute" if execute else "dry-run",
        "source_profile_id": source_profile_id,
        "before": before["totals"],
        "preserved": [
            "raw assets", "source master data", "channelized maps",
            "visual registrations", "uav_message_inbox", "uav_audit_logs",
        ],
    }
    if not execute:
        result["passed"] = True
        return result
    if os.environ.get("ALLOW_REPLAY_SOURCE_ROLLBACK") != "1":
        raise RuntimeError("set ALLOW_REPLAY_SOURCE_ROLLBACK=1 before execution")
    if confirmation != CONFIRMATION:
        raise RuntimeError(f"pass --confirm {CONFIRMATION}")
    if before["totals"]["active_missions"] or before["totals"]["active_pipelines"]:
        raise RuntimeError("active Mission/Pipeline blocks source rollback")

    async with async_session_maker() as session:
        metric_message_ids = select(TrafficMetric.source_message_id).where(
            TrafficMetric.source_profile_id == source_profile_id
        )
        conflict_ids = select(ConflictEvent.id).where(
            ConflictEvent.source_profile_id == source_profile_id
        )
        ai_event_ids = select(AiEvent.id).where(
            AiEvent.payload["source_profile_id"].as_string() == source_profile_id
        )
        outbox_ids = select(EventOutbox.id).where(EventOutbox.event_id.in_(ai_event_ids))
        package_ids = select(EvidencePackage.id).where(
            (
                (EvidencePackage.owner_type == "conflict_event")
                & EvidencePackage.owner_id.in_(conflict_ids)
            )
            | (
                (EvidencePackage.owner_type == "ai_event_candidate")
                & EvidencePackage.source_event_id.in_(metric_message_ids)
            )
        )
        await session.execute(delete(EventDeliveryAttempt).where(EventDeliveryAttempt.outbox_id.in_(outbox_ids)))
        await session.execute(delete(DeadLetter).where(DeadLetter.outbox_id.in_(outbox_ids)))
        await session.execute(delete(EventOutbox).where(EventOutbox.id.in_(outbox_ids)))
        await session.execute(delete(EvidenceItem).where(EvidenceItem.package_id.in_(package_ids)))
        await session.execute(delete(EvidencePackage).where(EvidencePackage.id.in_(package_ids)))
        await session.execute(delete(AiEvent).where(AiEvent.id.in_(ai_event_ids)))
        await session.execute(delete(ConflictReview).where(ConflictReview.event_id.in_(conflict_ids)))
        for model in (TrackPoint, ConflictEvent, TrackEvent, TrafficMetric, TelemetryMetric):
            await session.execute(delete(model).where(model.source_profile_id == source_profile_id))
        session.add(AuditLog(
            action="replay_source_batch_rolled_back",
            target_type="source_profile", target_id=source_profile_id,
            after_value={"deleted_counts": before["totals"], "inbox_preserved": True},
            reason="failed or detached replay batch rolled back before retry",
            request_id=f"rollback-{uuid.uuid4().hex}",
        ))
        await session.commit()
    after = await collect_inventory((source_profile_id,))
    result["after"] = after["totals"]
    result["passed"] = all(
        int(after["totals"].get(key) or 0) == 0
        for key in (
            "traffic_metrics", "track_events", "track_points", "conflict_events",
            "telemetry_metrics", "conflict_reviews", "derived_ai_events", "evidence_packages",
        )
    )
    return result


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm")
    args = parser.parse_args()
    if args.source not in KNOWN_SOURCE_PROFILES:
        raise SystemExit(f"unknown replay SourceProfile: {args.source}")
    try:
        result = await rollback(args.source, args.execute, args.confirm)
    finally:
        await close_db()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
