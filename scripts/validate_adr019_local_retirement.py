#!/usr/bin/env python3
"""Validate the live canonical local stack after ADR-019 cutover."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROJECT = "traffic_analyzer"
EXPECTED_CONTAINERS = {
    "traffic_analyzer-road9-1",
    "traffic_analyzer-kafka-1",
    "traffic_analyzer-platform-1",
    "traffic_analyzer-console2-1",
    "traffic_analyzer-nginx-1",
}
EXPECTED_HYPERTABLES = {
    "uav_conflict_events",
    "uav_system_metrics",
    "uav_telemetry_metrics",
    "uav_track_points",
    "uav_traffic_metrics",
}
FORBIDDEN_CONTAINER_NAMES = {
    "traffic_postgres",
    "traffic_influxdb",
    "traffic_platform",
    "traffic_kafka",
    "traffic_zookeeper",
    "traffic_timescaledb_local",
}
OLD_VOLUMES = {
    "trafficanalyzer_postgres_data",
    "trafficanalyzer_timescaledb_local_data",
    "traffic_analyzer_mp4new_road9_target_data",
}
OLD_BIND = str((ROOT / "services" / "influxdb_data").resolve())
RETENTION = ROOT / "output" / "adr019-retirement" / "retention.json"
SOAK_REPORT = ROOT / "docs" / "test_report_i6_local_readiness_soak.json"
OUTAGE_REPORT = ROOT / "docs" / "test_report_i6_database_outage.json"


def _canonical_topics_only(topics: list[str]) -> bool:
    business_topics = [topic for topic in topics if not topic.startswith("__")]
    return bool(business_topics) and all(topic.startswith("uav_") for topic in business_topics)


def _run(command: list[str]) -> str:
    return subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def _http_json(url: str, *, body: dict[str, Any] | None = None) -> tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read().decode()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        return exc.code, json.loads(raw) if raw else None


def _psql(database: str, sql: str) -> str:
    return _run([
        "docker", "exec", "traffic_analyzer-road9-1", "psql", "-U", "traffic", "-d", database,
        "-At", "-F", "|", "-c", sql,
    ])


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate() -> dict[str, Any]:
    if os.getenv("ALLOW_ADR019_LOCAL_RETIREMENT_CHECK") != "1":
        raise RuntimeError("set ALLOW_ADR019_LOCAL_RETIREMENT_CHECK=1 to inspect the live local stack")
    _run(["docker", "compose", "-f", "docker-compose.yaml", "-p", PROJECT, "config", "--quiet"])
    running_names = set(_run(["docker", "ps", "--format", "{{.Names}}"]).splitlines())
    all_names = set(_run(["docker", "ps", "-a", "--format", "{{.Names}}"]).splitlines())
    expected_states = json.loads(_run(["docker", "inspect", *sorted(EXPECTED_CONTAINERS)]))
    container_health = {
        item["Name"].lstrip("/"): {
            "status": item["State"]["Status"],
            "health": item["State"].get("Health", {}).get("Status", "none"),
        }
        for item in expected_states
    }

    container_ids = _run(["docker", "ps", "-aq"]).split()
    mounted_sources: set[str] = set()
    if container_ids:
        for item in json.loads(_run(["docker", "inspect", *container_ids])):
            for mount in item.get("Mounts", []):
                source = mount.get("Name") or mount.get("Source")
                if source:
                    mounted_sources.add(str(source))
    volume_names = set(_run(["docker", "volume", "ls", "--format", "{{.Name}}"]).splitlines())

    db_raw = _psql(
        "road9",
        "SELECT current_database(),(SELECT version_num FROM uav_alembic_version LIMIT 1),extversion,"
        "(SELECT count(*) FROM timescaledb_information.hypertables),"
        "(SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name LIKE 'uav_%') "
        "FROM pg_extension WHERE extname='timescaledb'",
    )
    database_name, revision, timescaledb_version, hypertables, uav_tables = db_raw.split("|")
    hypertable_names = set(_psql(
        "road9",
        "SELECT hypertable_name FROM timescaledb_information.hypertables "
        "WHERE hypertable_schema='public' ORDER BY hypertable_name",
    ).splitlines())
    uav_table_names = _psql(
        "road9",
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public' "
        "AND table_name LIKE 'uav_%' ORDER BY table_name",
    ).splitlines()
    admin_rows = int(_psql("road9", "SELECT count(*) FROM uav_users WHERE username='admin'"))
    user_rows = int(_psql("road9", "SELECT count(*) FROM uav_users"))
    business_tables = _psql(
        "road9",
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public' "
        "AND table_name LIKE 'uav_%' AND table_name NOT IN ('uav_users','uav_alembic_version') ORDER BY 1",
    ).splitlines()
    business_rows = sum(int(_psql("road9", f'SELECT count(*) FROM "{table}"')) for table in business_tables)
    legacy_database_count = int(_psql("postgres", "SELECT count(*) FROM pg_database WHERE datname='traffic_platform'"))
    isolation_tables = _psql(
        "road9",
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public' "
        "AND table_name IN ('uav_migration_audit','uav_migration_quarantine','uav_isolation_audit')",
    ).splitlines()

    topics = _run([
        "docker", "exec", "traffic_analyzer-kafka-1", "/opt/kafka/bin/kafka-topics.sh",
        "--bootstrap-server", "localhost:29092", "--list",
    ]).splitlines()
    ready_status, ready = _http_json("http://127.0.0.1:8000/ready")
    nginx_status, nginx_ready = _http_json("http://127.0.0.1:8009/ready")
    login_status, login = _http_json(
        "http://127.0.0.1:8080/api/v1/auth/login", body={"username": "admin", "password": "admin123"}
    )

    retention = _load_json(RETENTION)
    soak = _load_json(SOAK_REPORT)
    outage = _load_json(OUTAGE_REPORT)
    purge_after = datetime.fromisoformat(str(retention["purge_after"]).replace("Z", "+00:00"))
    retired_at = datetime.fromisoformat(str(retention["retired_at"]).replace("Z", "+00:00"))
    checks = {
        "compose_config": True,
        "only_canonical_containers_running": running_names == EXPECTED_CONTAINERS,
        "expected_containers_healthy": all(
            value["status"] == "running"
            and (name.endswith(("road9-1", "kafka-1", "platform-1")) is False or value["health"] == "healthy")
            for name, value in container_health.items()
        ),
        "old_containers_absent": not (FORBIDDEN_CONTAINER_NAMES & all_names)
        and not any(name.startswith("traffic_analyzer_mp4new-") for name in all_names),
        "stable_new_volume_mounted": "traffic_road9_data" in mounted_sources,
        "old_storage_retained": OLD_VOLUMES <= volume_names and Path(OLD_BIND).exists(),
        "old_storage_unmounted": not ((OLD_VOLUMES | {OLD_BIND}) & mounted_sources),
        "retention_is_seven_days": (purge_after - retired_at).total_seconds() >= 7 * 86400,
        "road9_at_head": database_name == "road9" and revision == "20260716_0011",
        "timescaledb_hypertables": int(hypertables) == 5 and hypertable_names == EXPECTED_HYPERTABLES,
        # The clean cutover baseline had zero business rows. Subsequent canonical
        # local-replay acceptance legitimately populates uav_* business tables,
        # so the live retirement gate must preserve the seed-user invariant
        # without treating current canonical data as legacy contamination.
        "only_seed_admin": admin_rows == 1 and user_rows == 1,
        "no_legacy_database_or_isolation_tables": legacy_database_count == 0 and not isolation_tables,
        "canonical_topics_only": _canonical_topics_only(topics),
        "platform_ready": ready_status == 200 and ready.get("status") == "ready",
        "nginx_ready": nginx_status == 200 and nginx_ready.get("status") == "ready",
        "console_auth": login_status == 200 and bool(login.get("access_token")),
        "database_outage_recovered": outage.get("execution_complete") is True
        and outage.get("outage", {}).get("status") == 503
        and outage.get("recovery", {}).get("status") == 200,
        "thirty_minute_soak": soak.get("passed") is True
        and soak.get("requested_duration_sec") == 1800
        and soak.get("summary", {}).get("all_samples_healthy") is True,
    }
    return {
        "schema_version": "uav.adr019-local-retirement/v1",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "scope": "local_development_only",
        "containers": {"running": sorted(running_names), "states": container_health},
        "database": {
            "name": database_name,
            "alembic_revision": revision,
            "timescaledb_version": timescaledb_version,
            "hypertables": int(hypertables),
            "hypertable_names": sorted(hypertable_names),
            "uav_tables": int(uav_tables),
            "uav_table_names": uav_table_names,
            "admin_rows": admin_rows,
            "business_rows": business_rows,
            "legacy_database_count": legacy_database_count,
            "migration_isolation_tables": isolation_tables,
        },
        "kafka": {"topics": topics},
        "retention": retention,
        "storage": {"old_volumes": sorted(OLD_VOLUMES), "old_bind": OLD_BIND, "mounted_sources": sorted(mounted_sources)},
        "checks": checks,
        "passed": all(checks.values()),
        "production_acceptance": "blocked_external",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate()
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
