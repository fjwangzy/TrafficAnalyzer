#!/usr/bin/env python3
"""Read-only audit for duplicate or reasonless completed trajectories in road9."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Iterable, Mapping


AUDIT_SQL = """
SELECT
    pipeline_id,
    track_id,
    COUNT(*)::int AS completion_count,
    COUNT(*) FILTER (
        WHERE COALESCE(payload -> 'data' ->> 'termination_reason', '') = ''
    )::int AS missing_reason_count,
    ARRAY_AGG(source_message_id ORDER BY ended_at, source_message_id)
        AS source_message_ids
FROM uav_track_events
GROUP BY pipeline_id, track_id
HAVING COUNT(*) > 1
    OR COUNT(*) FILTER (
        WHERE COALESCE(payload -> 'data' ->> 'termination_reason', '') = ''
    ) > 0
ORDER BY pipeline_id NULLS FIRST, track_id
"""


def build_report(rows: Iterable[Mapping]) -> dict:
    """Build an immutable audit result; callers decide how to quarantine runs."""
    issues = []
    affected_pipelines = set()
    duplicate_pairs = 0
    reasonless_pairs = 0
    for raw in rows:
        row = dict(raw)
        completion_count = int(row.get("completion_count") or 0)
        missing_reason_count = int(row.get("missing_reason_count") or 0)
        pipeline_id = row.get("pipeline_id")
        if completion_count > 1:
            duplicate_pairs += 1
        if missing_reason_count > 0:
            reasonless_pairs += 1
        if pipeline_id:
            affected_pipelines.add(str(pipeline_id))
        issues.append(
            {
                "pipeline_id": pipeline_id,
                "track_id": str(row.get("track_id")),
                "completion_count": completion_count,
                "missing_termination_reason_count": missing_reason_count,
                "source_message_ids": list(row.get("source_message_ids") or []),
                "formal_statistics_status": "invalid",
                "action": "exclude_history_no_mutation",
            }
        )
    return {
        "schema_version": "uav.track-lifecycle-audit/v1",
        "read_only": True,
        "history_mutated": False,
        "ready_for_formal_statistics": not issues,
        "summary": {
            "issue_pairs": len(issues),
            "duplicate_completion_pairs": duplicate_pairs,
            "missing_termination_reason_pairs": reasonless_pairs,
            "affected_pipelines": len(affected_pipelines),
        },
        "affected_pipeline_ids": sorted(affected_pipelines),
        "issues": issues,
    }


async def audit_road9() -> dict:
    """Execute only a SELECT inside a PostgreSQL read-only transaction."""
    import asyncpg

    connection = await asyncpg.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", "5432")),
        user=os.getenv("DB_USER", "traffic"),
        password=os.getenv("DB_PASSWORD", "traffic123"),
        database=os.getenv("DB_NAME", "road9"),
    )
    try:
        async with connection.transaction(readonly=True):
            rows = await connection.fetch(AUDIT_SQL)
        return build_report(rows)
    finally:
        await connection.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--format", choices=("json", "text"), default="text")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    report = asyncio.run(audit_road9())
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        summary = report["summary"]
        print(
            "road9 lifecycle audit "
            f"ready={report['ready_for_formal_statistics']} "
            f"issues={summary['issue_pairs']} "
            f"affected_pipelines={summary['affected_pipelines']}"
        )
        for issue in report["issues"]:
            print(
                "[invalid] "
                f"pipeline={issue['pipeline_id']} track={issue['track_id']} "
                f"completions={issue['completion_count']} "
                f"missing_reason={issue['missing_termination_reason_count']}"
            )
    return 1 if args.strict and not report["ready_for_formal_statistics"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
