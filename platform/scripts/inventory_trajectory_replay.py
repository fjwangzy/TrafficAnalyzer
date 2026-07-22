#!/usr/bin/env python3
"""Inventory canonical replay data before an explicitly approved cleanup.

This command is intentionally read-only.  It reports the database rows that
belong to the selected local replay SourceProfiles so an operator can review
the cleanup boundary before running a destructive reset in a later session.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from sqlalchemy import distinct, func, select, union

PLATFORM_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = PLATFORM_DIR.parent
sys.path.insert(0, str(PLATFORM_DIR))
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import async_session_maker, close_db  # noqa: E402
from app.models.metrics import (  # noqa: E402
    ConflictEvent,
    ConflictReview,
    TelemetryMetric,
    TrackEvent,
    TrackPoint,
    TrafficMetric,
)
from app.models.mission import (  # noqa: E402
    MessageInbox,
    MissionRecord,
    PipelineRecord,
    VideoSourceRecord,
)
from app.models.survey import AiEvent, EvidencePackage  # noqa: E402
from scripts.bootstrap_mp4new_sources import (  # noqa: E402
    INTER_XQH_CATALOG,
    MP4NEW_CATALOG,
)


def catalog_source_profiles(catalog: Iterable[dict]) -> tuple[str, ...]:
    return tuple(
        source["profile_id"]
        for intersection in catalog
        for source in intersection["sources"]
    )


MP4NEW_SOURCE_PROFILES = catalog_source_profiles(MP4NEW_CATALOG)
INTER_XQH_SOURCE_PROFILES = catalog_source_profiles(INTER_XQH_CATALOG)
KNOWN_SOURCE_PROFILES = frozenset((*MP4NEW_SOURCE_PROFILES, *INTER_XQH_SOURCE_PROFILES))


def resolve_source_profiles(
    requested: Iterable[str] | None,
    *,
    include_inter_xqh: bool = False,
) -> tuple[str, ...]:
    """Resolve a deterministic, allowlisted read-only inventory scope."""
    selected = tuple(dict.fromkeys(requested or MP4NEW_SOURCE_PROFILES))
    if include_inter_xqh:
        selected = tuple(dict.fromkeys((*selected, *INTER_XQH_SOURCE_PROFILES)))
    unknown = sorted(set(selected) - KNOWN_SOURCE_PROFILES)
    if unknown:
        raise ValueError(f"unknown replay SourceProfile(s): {', '.join(unknown)}")
    if not selected:
        raise ValueError("at least one replay SourceProfile is required")
    return selected


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


async def _group_counts(session, model, source_profiles: tuple[str, ...]) -> dict[str, int]:
    rows = (
        await session.execute(
            select(model.source_profile_id, func.count())
            .where(model.source_profile_id.in_(source_profiles))
            .group_by(model.source_profile_id)
        )
    ).all()
    return {str(source_profile_id): int(count) for source_profile_id, count in rows}


async def collect_inventory(source_profiles: tuple[str, ...]) -> dict:
    """Collect the current reset blast radius without mutating road9."""
    async with async_session_maker() as session:
        grouped = {
            "traffic_metrics": await _group_counts(session, TrafficMetric, source_profiles),
            "track_events": await _group_counts(session, TrackEvent, source_profiles),
            "track_points": await _group_counts(session, TrackPoint, source_profiles),
            "conflict_events": await _group_counts(session, ConflictEvent, source_profiles),
            "telemetry_metrics": await _group_counts(session, TelemetryMetric, source_profiles),
        }

        track_ranges = (
            await session.execute(
                select(
                    TrackEvent.source_profile_id,
                    func.min(TrackEvent.ended_at),
                    func.max(TrackEvent.ended_at),
                )
                .where(TrackEvent.source_profile_id.in_(source_profiles))
                .group_by(TrackEvent.source_profile_id)
            )
        ).all()
        ranges = {
            str(source_profile_id): {"first_track_at": _iso(first), "last_track_at": _iso(last)}
            for source_profile_id, first, last in track_ranges
        }

        conflict_ids = select(ConflictEvent.id).where(
            ConflictEvent.source_profile_id.in_(source_profiles)
        )
        conflict_reviews = int(
            (
                await session.execute(
                    select(func.count()).select_from(ConflictReview).where(
                        ConflictReview.event_id.in_(conflict_ids)
                    )
                )
            ).scalar_one()
        )

        metric_message_ids = select(distinct(TrafficMetric.source_message_id)).where(
            TrafficMetric.source_profile_id.in_(source_profiles)
        )
        conflict_message_ids = select(distinct(ConflictEvent.source_message_id)).where(
            ConflictEvent.source_profile_id.in_(source_profiles)
        )
        track_message_ids = select(distinct(TrackEvent.source_message_id)).where(
            TrackEvent.source_profile_id.in_(source_profiles)
        )
        telemetry_message_ids = select(distinct(TelemetryMetric.source_message_id)).where(
            TelemetryMetric.source_profile_id.in_(source_profiles)
        )
        selected_message_ids = union(
            metric_message_ids,
            conflict_message_ids,
            track_message_ids,
            telemetry_message_ids,
        )
        inbox_rows = int(
            (
                await session.execute(
                    select(func.count()).select_from(MessageInbox).where(
                        MessageInbox.message_id.in_(selected_message_ids)
                    )
                )
            ).scalar_one()
        )

        evidence_packages = int(
            (
                await session.execute(
                    select(func.count()).select_from(EvidencePackage).where(
                        (
                            (EvidencePackage.owner_type == "conflict_event")
                            & EvidencePackage.owner_id.in_(conflict_ids)
                        )
                        | (
                            (EvidencePackage.owner_type == "ai_event_candidate")
                            & EvidencePackage.source_event_id.in_(metric_message_ids)
                        )
                    )
                )
            ).scalar_one()
        )

        derived_events = int(
            (
                await session.execute(
                    select(func.count()).select_from(AiEvent).where(
                        AiEvent.payload["source_profile_id"].as_string().in_(source_profiles)
                    )
                )
            ).scalar_one()
        )

        active_missions = int(
            (
                await session.execute(
                    select(func.count(distinct(MissionRecord.id)))
                    .select_from(MissionRecord)
                    .join(VideoSourceRecord, MissionRecord.video_source_id == VideoSourceRecord.id)
                    .where(
                        VideoSourceRecord.profile_id.in_(source_profiles),
                        MissionRecord.status.in_(("pending", "running", "stopping")),
                    )
                )
            ).scalar_one()
        )
        active_pipelines = int(
            (
                await session.execute(
                    select(func.count(distinct(PipelineRecord.id)))
                    .select_from(PipelineRecord)
                    .join(MissionRecord, PipelineRecord.mission_id == MissionRecord.id)
                    .join(VideoSourceRecord, MissionRecord.video_source_id == VideoSourceRecord.id)
                    .where(
                        VideoSourceRecord.profile_id.in_(source_profiles),
                        PipelineRecord.observed_status.in_(("starting", "running", "stopping")),
                    )
                )
            ).scalar_one()
        )

    per_source = {}
    for source_profile_id in source_profiles:
        per_source[source_profile_id] = {
            table: counts.get(source_profile_id, 0)
            for table, counts in grouped.items()
        }
        per_source[source_profile_id].update(ranges.get(source_profile_id, {}))

    totals = {
        table: sum(counts.values())
        for table, counts in grouped.items()
    }
    totals.update(
        {
            "conflict_reviews": conflict_reviews,
            "derived_ai_events": derived_events,
            "evidence_packages": evidence_packages,
            "message_inbox_rows_preserved": inbox_rows,
            "active_missions": active_missions,
            "active_pipelines": active_pipelines,
        }
    )
    return {
        "schema_version": "uav.trajectory-replay-inventory/v1",
        "database": "road9",
        "read_only": True,
        "source_profiles": list(source_profiles),
        "totals": totals,
        "per_source": per_source,
        "preserve": [
            "uav_message_inbox",
            "uav_users",
            "uav_drones",
            "uav_video_sources",
            "uav_telemetry_sources",
            "uav_road_context_snapshots",
            "uav_lane_annotation_tasks",
            "uav_visual_lane_bindings",
            "uav_survey_tasks and survey-domain data",
            "uav_audit_logs",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        action="append",
        help="allowlisted SourceProfile; repeat to narrow scope (default: all mp4new/mp4new2)",
    )
    parser.add_argument(
        "--include-inter-xqh",
        action="store_true",
        help="also inventory the small-Qinghe inter_xqh replay source",
    )
    parser.add_argument("--output", type=Path, help="optional JSON manifest path")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    try:
        source_profiles = resolve_source_profiles(
            args.source,
            include_inter_xqh=args.include_inter_xqh,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    try:
        inventory = await collect_inventory(source_profiles)
    finally:
        await close_db()
    rendered = json.dumps(inventory, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
