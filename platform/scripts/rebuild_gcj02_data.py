#!/usr/bin/env python3
"""Inventory or execute the one-time GCJ-02 business-data rebuild.

The default is a read-only dry run.  Execution requires both an environment
gate and an exact confirmation phrase.  External YCX tables and retained
master data are never targets.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg

from app.core.config import settings


CONFIRMATION = "REBUILD_GCJ02_BUSINESS_DATA"
KAFKA_TOPIC_ALLOWLIST = (
    re.compile(r"uav_statistics_.+"),
    re.compile(r"uav_track_complete_.+"),
    re.compile(r"uav_conflicts_.+"),
    re.compile(r"uav_telemetry_.+"),
    re.compile(r"uav_system_metrics"),
    re.compile(r"uav_ai_events"),
    re.compile(r"uav_ai_event_feedback"),
)
KAFKA_CONSUMER_GROUP_ALLOWLIST = frozenset({"vision-service", settings.kafka_consumer_group})
RETAINED_TABLES = (
    "uav_users",
    "uav_drones",
    "uav_video_sources",
    "uav_telemetry_sources",
    "uav_flight_plans",
    "uav_alembic_version",
)
# FK-safe child-to-parent order.  Keep this explicit: wildcard discovery must
# never silently expand the destructive scope.
CLEAR_TABLES = (
    "uav_event_delivery_attempts",
    "uav_event_outbox",
    "uav_enforcement_review_audits",
    "uav_enforcement_clues",
    "uav_conflict_reviews",
    "uav_track_points",
    "uav_capture_ingestion_jobs",
    "uav_survey_measurements",
    "uav_scene_annotations",
    "uav_survey_reports",
    "uav_capture_frames",
    "uav_capture_batches",
    "uav_evidence_items",
    "uav_evidence_packages",
    "uav_ai_events",
    "uav_survey_tasks",
    "uav_lane_annotation_tasks",
    "uav_visual_lane_bindings",
    "uav_visual_registrations",
    "uav_channelized_map_versions",
    "uav_road_context_snapshots",
    "uav_device_intersection_bindings",
    "uav_pipelines",
    "uav_missions",
    "uav_event_feedback",
    "uav_alerts",
    "uav_enforcement_rules",
    "uav_enforcement_zones",
    "uav_dead_letters",
    "uav_message_dead_letters",
    "uav_message_inbox",
    "uav_conflict_events",
    "uav_track_events",
    "uav_traffic_metrics",
    "uav_telemetry_metrics",
    "uav_system_metrics",
    "uav_rule_versions",
    "uav_audit_logs",
)
RAW_EVIDENCE_KINDS = frozenset({
    "source_video", "source_telemetry", "raw_video", "raw_telemetry",
    "source_image", "original_image", "keyframe_image",
})


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def _existing_tables(connection: asyncpg.Connection) -> set[str]:
    rows = await connection.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename LIKE 'uav_%'"
    )
    return {row["tablename"] for row in rows}


async def _raw_manifest(connection: asyncpg.Connection, existing: set[str]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if "uav_video_sources" in existing:
        for row in await connection.fetch("SELECT id, profile_id, location FROM uav_video_sources ORDER BY id"):
            candidates.append({"kind": "source_video", "id": row["id"], "profile_id": row["profile_id"], "path": row["location"]})
    if "uav_telemetry_sources" in existing:
        for row in await connection.fetch("SELECT id, profile_id, location FROM uav_telemetry_sources ORDER BY id"):
            candidates.append({"kind": "source_telemetry", "id": row["id"], "profile_id": row["profile_id"], "path": row["location"]})
    if "uav_evidence_items" in existing:
        rows = await connection.fetch(
            "SELECT id, kind, storage_key, sha256, size_bytes FROM uav_evidence_items WHERE kind=ANY($1::text[]) ORDER BY id",
            sorted(RAW_EVIDENCE_KINDS),
        )
        for row in rows:
            candidates.append({
                "kind": row["kind"], "id": row["id"], "path": row["storage_key"],
                "registered_sha256": row["sha256"], "registered_size_bytes": row["size_bytes"],
            })
    for item in candidates:
        path = Path(str(item["path"]))
        item["exists"] = path.is_file()
        item["size_bytes"] = path.stat().st_size if path.is_file() else None
        item["sha256"] = _sha256(path)
    return candidates


def _managed_topic(name: str) -> bool:
    return any(pattern.fullmatch(name) for pattern in KAFKA_TOPIC_ALLOWLIST)


async def _kafka_inventory() -> list[str]:
    return await asyncio.to_thread(_kafka_inventory_sync)


def _kafka_inventory_sync() -> list[str]:
    from kafka.admin import KafkaAdminClient

    admin = KafkaAdminClient(bootstrap_servers=settings.kafka_bootstrap, client_id="uav-gcj02-rebuild-inventory")
    try:
        return sorted(name for name in admin.list_topics() if _managed_topic(name))
    finally:
        admin.close()


async def _rebuild_kafka(topics: list[str]) -> dict[str, Any]:
    return await asyncio.to_thread(_rebuild_kafka_sync, topics)


def _kafka_empty_state_sync(topics: list[str]) -> dict[str, Any]:
    from kafka import KafkaConsumer, TopicPartition
    from kafka.admin import KafkaAdminClient

    consumer = KafkaConsumer(
        bootstrap_servers=settings.kafka_bootstrap,
        enable_auto_commit=False,
        group_id=None,
        client_id="uav-gcj02-rebuild-verifier",
    )
    admin = KafkaAdminClient(
        bootstrap_servers=settings.kafka_bootstrap,
        client_id="uav-gcj02-rebuild-group-verifier",
    )
    try:
        partitions = []
        for topic in topics:
            partitions.extend(
                TopicPartition(topic, partition)
                for partition in sorted(consumer.partitions_for_topic(topic) or ())
            )
        end_offsets = consumer.end_offsets(partitions) if partitions else {}
        offsets = {
            f"{item.topic}:{item.partition}": int(offset)
            for item, offset in end_offsets.items()
        }
        managed_groups = sorted(
            group_id
            for group_id, _ in admin.list_consumer_groups()
            if group_id in KAFKA_CONSUMER_GROUP_ALLOWLIST
        )
        return {
            "end_offsets": offsets,
            "nonzero_end_offsets": {
                key: value for key, value in offsets.items() if value != 0
            },
            "managed_consumer_groups_remaining": managed_groups,
        }
    finally:
        consumer.close()
        admin.close()


def _rebuild_kafka_sync(topics: list[str]) -> dict[str, Any]:
    from kafka.admin import KafkaAdminClient, NewTopic

    admin = KafkaAdminClient(bootstrap_servers=settings.kafka_bootstrap, client_id="uav-gcj02-rebuild")
    try:
        if topics:
            admin.delete_topics(topics)
            deadline = time.monotonic() + 30
            while set(topics).intersection(admin.list_topics()):
                if time.monotonic() >= deadline:
                    raise RuntimeError("Kafka topic deletion did not complete within 30 seconds")
                time.sleep(0.5)
            admin.create_topics([
                NewTopic(name=name, num_partitions=1, replication_factor=1) for name in topics
            ])
        groups = sorted(KAFKA_CONSUMER_GROUP_ALLOWLIST)
        existing_groups = {group_id for group_id, _ in admin.list_consumer_groups()}
        targets = [group_id for group_id in groups if group_id in existing_groups]
        if targets:
            admin.delete_consumer_groups(targets)
    finally:
        admin.close()
    deadline = time.monotonic() + 30
    while True:
        state = _kafka_empty_state_sync(topics)
        if not state["nonzero_end_offsets"] and not state["managed_consumer_groups_remaining"]:
            return state
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Kafka rebuild verification failed: {state}")
        time.sleep(0.5)


async def rebuild(execute: bool, confirmation: str, output: Path, include_kafka: bool = False) -> dict[str, Any]:
    connection = await asyncpg.connect(
        host=settings.db_host, port=settings.db_port, user=settings.db_user,
        password=settings.db_password, database=settings.db_name, timeout=10,
    )
    try:
        existing = await _existing_tables(connection)
        unknown = sorted(existing - set(RETAINED_TABLES) - set(CLEAR_TABLES))
        if unknown:
            raise RuntimeError(f"unclassified uav tables block rebuild: {unknown}")
        counts = {
            table: int(await connection.fetchval(f'SELECT count(*) FROM "{table}"'))
            for table in (*RETAINED_TABLES, *CLEAR_TABLES)
            if table in existing
        }
        active_missions = counts.get("uav_missions", 0) and int(await connection.fetchval(
            "SELECT count(*) FROM uav_missions WHERE status IN ('pending','starting','running')"
        ))
        active_pipelines = counts.get("uav_pipelines", 0) and int(await connection.fetchval(
            "SELECT count(*) FROM uav_pipelines WHERE observed_status IN ('pending','starting','running')"
        ))
        raw_files = await _raw_manifest(connection, existing)
        kafka_topics = await _kafka_inventory() if include_kafka else []
        result: dict[str, Any] = {
            "schema_version": "uav.gcj02-rebuild-manifest/v1",
            "generated_at": datetime.now(UTC).isoformat(),
            "mode": "execute" if execute else "dry-run",
            "database": settings.db_name,
            "retained_tables": list(RETAINED_TABLES),
            "clear_tables": [table for table in CLEAR_TABLES if table in existing],
            "counts_before": counts,
            "active_missions": active_missions,
            "active_pipelines": active_pipelines,
            "raw_files": raw_files,
            "missing_raw_files": [item["path"] for item in raw_files if not item["exists"]],
            "kafka": {
                "included": include_kafka,
                "managed_topics": kafka_topics,
                "consumer_groups": sorted(KAFKA_CONSUMER_GROUP_ALLOWLIST) if include_kafka else [],
            },
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if not execute:
            return result
        if os.getenv("ALLOW_GCJ02_REBUILD") != "1":
            raise RuntimeError("set ALLOW_GCJ02_REBUILD=1 before execution")
        if confirmation != CONFIRMATION:
            raise RuntimeError(f"pass --confirm {CONFIRMATION}")
        if active_missions or active_pipelines:
            raise RuntimeError("active Mission/Pipeline blocks rebuild")
        if result["missing_raw_files"]:
            raise RuntimeError("missing retained raw files block rebuild")

        kafka_after = await _rebuild_kafka(kafka_topics) if include_kafka else None

        async with connection.transaction():
            await connection.execute("SELECT pg_advisory_xact_lock(2026072102)")
            for table in CLEAR_TABLES:
                if table in existing:
                    await connection.execute(f'DELETE FROM "{table}"')
            if "uav_flight_plans" in existing:
                await connection.execute(
                    "UPDATE uav_flight_plans SET state='draft', road_data_version='UNBOUND-GCJ02', revision=revision+1"
                )
            if "uav_audit_logs" in existing:
                await connection.execute(
                    "INSERT INTO uav_audit_logs(action,target_type,target_id,after_value,reason) "
                    "VALUES('gcj02_rebuild_started','system','road9',$1::jsonb,'historical business data cleared for GCJ-02 rebuild')",
                    json.dumps({"coordinate_system": "GCJ02", "manifest": str(output)}),
                )
        result["completed_at"] = datetime.now(UTC).isoformat()
        if kafka_after is not None:
            result["kafka"]["after"] = kafka_after
        result["counts_after"] = {
            table: int(await connection.fetchval(f'SELECT count(*) FROM "{table}"'))
            for table in CLEAR_TABLES if table in existing
        }
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result
    finally:
        await connection.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--include-kafka", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("/private/tmp/TrafficAnalyzer-gcj02-rebuild-manifest.json"))
    args = parser.parse_args()
    result = asyncio.run(rebuild(args.execute, args.confirm, args.output, args.include_kafka))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
