#!/usr/bin/env python3
"""Create a read-only inventory of the local legacy InfluxDB dataset.

This script never writes to InfluxDB or PostgreSQL.  It records candidate
ADR-019 mappings, but deliberately leaves them ``unverified`` until historical
time semantics, field transformations and reconciliation thresholds are
approved.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SAFE_INFLUX_CONTAINER = "traffic_influxdb"
SAFE_INFLUX_DATABASE = "influx"
SAFE_POSTGRES_CONTAINER = "traffic_timescaledb_local"
SAFE_POSTGRES_DATABASE = "road9"
SAFE_POSTGRES_USER = "traffic"

MAPPINGS = (
    ("intersection_stats", "uav_traffic_metrics"),
    ("track_events", "uav_track_events"),
    ("conflict_events", "uav_conflict_events"),
)


def _run(command: list[str]) -> str:
    return subprocess.run(command, check=True, capture_output=True, text=True).stdout.strip()


def _influx_query(container: str, database: str, statement: str) -> dict[str, Any]:
    output = _run(
        [
            "docker",
            "exec",
            container,
            "influx",
            "-database",
            database,
            "-format",
            "json",
            "-execute",
            statement,
        ]
    )
    return json.loads(output)


def _series(payload: dict[str, Any]) -> dict[str, Any] | None:
    for result in payload.get("results", []):
        series = result.get("series") or []
        if series:
            return series[0]
    return None


def _rows(payload: dict[str, Any]) -> tuple[list[str], list[list[Any]]]:
    series = _series(payload)
    if not series:
        return [], []
    return list(series.get("columns", [])), list(series.get("values", []))


def _boundary_time(payload: dict[str, Any]) -> str | None:
    columns, rows = _rows(payload)
    if not rows or "time" not in columns:
        return None
    raw = rows[0][columns.index("time")]
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(raw / 1_000_000_000, tz=UTC).isoformat().replace("+00:00", "Z")
    return str(raw)


def _point_count_estimate(payload: dict[str, Any]) -> int:
    columns, rows = _rows(payload)
    if not rows:
        return 0
    counts = [value for column, value in zip(columns, rows[0], strict=False) if column != "time" and isinstance(value, int)]
    return max(counts, default=0)


def _cardinality(payload: dict[str, Any]) -> int:
    columns, rows = _rows(payload)
    if not rows or "count" not in columns:
        return 0
    return int(rows[0][columns.index("count")])


def _key_rows(payload: dict[str, Any], key_column: str, type_column: str | None = None) -> list[Any]:
    columns, rows = _rows(payload)
    if key_column not in columns:
        return []
    key_index = columns.index(key_column)
    if type_column and type_column in columns:
        type_index = columns.index(type_column)
        return [{"name": str(row[key_index]), "type": str(row[type_index])} for row in rows]
    return [str(row[key_index]) for row in rows]


def _time_semantics(first_time: str | None, last_time: str | None) -> dict[str, str]:
    values = [value for value in (first_time, last_time) if value]
    if values and any(value < "2000-01-01" for value in values):
        return {
            "status": "blocked_external",
            "classification": "relative_or_invalid_epoch",
            "detail": "Source time is relative or invalid as UTC; an approved reconstruction rule is required before backfill.",
        }
    return {
        "status": "unverified",
        "classification": "absolute_utc_candidate",
        "detail": "The boundary resembles UTC, but source clock and timezone semantics still require approval.",
    }


def _target_snapshot(container: str, database: str, user: str) -> list[dict[str, Any]]:
    sql = (
        "SELECT 'uav_traffic_metrics', count(*), min(observed_at), max(observed_at) FROM uav_traffic_metrics "
        "UNION ALL SELECT 'uav_track_events', count(*), min(ended_at), max(ended_at) FROM uav_track_events "
        "UNION ALL SELECT 'uav_conflict_events', count(*), min(occurred_at), max(occurred_at) FROM uav_conflict_events "
        "ORDER BY 1"
    )
    output = _run(
        [
            "docker",
            "exec",
            container,
            "psql",
            "-U",
            user,
            "-d",
            database,
            "-At",
            "-F",
            "|",
            "-c",
            sql,
        ]
    )
    rows = []
    for line in output.splitlines():
        table, count, first_time, last_time = line.split("|", maxsplit=3)
        rows.append(
            {
                "table": table,
                "row_count": int(count),
                "first_time": first_time or None,
                "last_time": last_time or None,
            }
        )
    return rows


def inventory(
    influx_container: str = SAFE_INFLUX_CONTAINER,
    influx_database: str = SAFE_INFLUX_DATABASE,
    postgres_container: str = SAFE_POSTGRES_CONTAINER,
    postgres_database: str = SAFE_POSTGRES_DATABASE,
    postgres_user: str = SAFE_POSTGRES_USER,
) -> dict[str, Any]:
    supplied = (influx_container, influx_database, postgres_container, postgres_database, postgres_user)
    expected = (
        SAFE_INFLUX_CONTAINER,
        SAFE_INFLUX_DATABASE,
        SAFE_POSTGRES_CONTAINER,
        SAFE_POSTGRES_DATABASE,
        SAFE_POSTGRES_USER,
    )
    if supplied != expected:
        raise ValueError("inventory is restricted to the approved local legacy and road9 development containers")

    measurements = []
    for measurement, candidate_table in MAPPINGS:
        quoted = f'"{measurement}"'
        fields = _key_rows(
            _influx_query(influx_container, influx_database, f"SHOW FIELD KEYS FROM {quoted}"),
            "fieldKey",
            "fieldType",
        )
        tags = _key_rows(
            _influx_query(influx_container, influx_database, f"SHOW TAG KEYS FROM {quoted}"),
            "tagKey",
        )
        point_count = _point_count_estimate(
            _influx_query(influx_container, influx_database, f"SELECT COUNT(*) FROM {quoted}")
        )
        cardinality = _cardinality(
            _influx_query(influx_container, influx_database, f"SHOW SERIES CARDINALITY FROM {quoted}")
        )
        first_time = _boundary_time(
            _influx_query(influx_container, influx_database, f"SELECT * FROM {quoted} ORDER BY time ASC LIMIT 1")
        )
        last_time = _boundary_time(
            _influx_query(influx_container, influx_database, f"SELECT * FROM {quoted} ORDER BY time DESC LIMIT 1")
        )
        measurements.append(
            {
                "measurement": measurement,
                "candidate_target_table": candidate_table,
                "mapping_status": "unverified",
                "point_count_estimate": point_count,
                "count_basis": "maximum non-null field count returned by InfluxQL COUNT(*)",
                "series_cardinality": cardinality,
                "first_time": first_time,
                "last_time": last_time,
                "time_semantics": _time_semantics(first_time, last_time),
                "tag_keys": tags,
                "field_keys": fields,
            }
        )

    return {
        "schema_version": "uav.legacy-influx-inventory/v1",
        "generated_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "mode": "read_only",
        "inventory_complete": all(item["field_keys"] and item["point_count_estimate"] >= 0 for item in measurements),
        "source": {"container": influx_container, "database": influx_database},
        "measurements": measurements,
        "target_snapshot": {
            "container": postgres_container,
            "database": postgres_database,
            "tables": _target_snapshot(postgres_container, postgres_database, postgres_user),
        },
        "reconciliation": {
            "status": "blocked_external",
            "detail": "Inventory is not a backfill approval. Field mapping, source-time reconstruction, thresholds, observation window and rollback require written approval.",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = inventory()
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
