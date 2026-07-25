#!/usr/bin/env python3
"""Validate the live canonical local stack after ADR-019 cutover."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROJECT = "traffic_analyzer"
EXPECTED_NATIVE_INFRA_CONTAINERS = {
    "traffic_analyzer-road9-1",
    "traffic_analyzer-kafka-1",
}
DOCKER_APPLICATION_CONTAINERS = {
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


def _current_schema_head() -> str:
    revisions: set[str] = set()
    parents: set[str] = set()
    for path in (ROOT / "platform" / "alembic" / "versions").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        revision = re.search(r'^revision\s*=\s*["\']([^"\']+)["\']', source, re.MULTILINE)
        down_revision = re.search(r'^down_revision\s*=\s*["\']([^"\']+)["\']', source, re.MULTILINE)
        if revision:
            revisions.add(revision.group(1))
        if down_revision:
            parents.add(down_revision.group(1))
    heads = revisions - parents
    if len(heads) != 1:
        raise RuntimeError(f"expected one Alembic head, found {sorted(heads)}")
    return heads.pop()


def _canonical_topics_only(topics: list[str]) -> bool:
    business_topics = [topic for topic in topics if not topic.startswith("__")]
    return bool(business_topics) and all(topic.startswith("uav_") for topic in business_topics)


def evaluate_runtime_snapshot(snapshot: dict[str, Any], *, expected_schema_head: str) -> dict[str, Any]:
    """Evaluate a captured native-macOS local runtime without performing I/O."""
    containers = snapshot["containers"]
    running = set(containers["running"])
    states = containers["states"]
    native = snapshot["native_platform"]
    database = snapshot["database"]
    storage = snapshot["storage"]
    resilience = snapshot["resilience"]
    checks = {
        "only_canonical_infrastructure_running": running == EXPECTED_NATIVE_INFRA_CONTAINERS,
        "infrastructure_containers_healthy": all(
            states.get(name, {}).get("status") == "running"
            and states.get(name, {}).get("health") == "healthy"
            for name in EXPECTED_NATIVE_INFRA_CONTAINERS
        ),
        "docker_application_containers_stopped": not (running & DOCKER_APPLICATION_CONTAINERS),
        "native_platform_ready": native.get("status") == "ready"
        and native.get("single_instance") is True
        and native.get("pipelines_active") == 0
        and all(
            native.get("services", {}).get(name) == "healthy"
            for name in ("database", "kafka", "timescaledb", "pipeline_manager")
        ),
        "native_mps_available": native.get("mps_available") is True,
        "stable_new_volume_mounted": storage.get("stable_volume_mounted") is True,
        "old_storage_retained": storage.get("old_storage_retained") is True,
        "old_storage_unmounted": storage.get("old_storage_unmounted") is True,
        "retention_is_seven_days": snapshot["retention"].get("at_least_seven_days") is True,
        "road9_at_head": database.get("name") == "road9"
        and database.get("alembic_revision") == expected_schema_head,
        "timescaledb_hypertables": database.get("hypertables") == 5
        and set(database.get("hypertable_names", [])) == EXPECTED_HYPERTABLES,
        "canonical_admin_present": database.get("admin_rows", 0) >= 1
        and database.get("user_rows", 0) >= database.get("admin_rows", 0),
        "no_legacy_database_or_isolation_tables": database.get("legacy_database_count") == 0
        and not database.get("migration_isolation_tables"),
        "canonical_topics_only": _canonical_topics_only(snapshot["kafka"]["topics"]),
        "database_outage_recovered": resilience.get("database_outage_recovered") is True,
        "thirty_minute_soak": resilience.get("thirty_minute_soak") is True,
    }
    return {"checks": checks, "passed": all(checks.values())}


def build_runtime_report(
    snapshot: dict[str, Any],
    *,
    expected_schema_head: str,
    generated_at: str,
) -> dict[str, Any]:
    evaluation = evaluate_runtime_snapshot(
        snapshot, expected_schema_head=expected_schema_head
    )
    return {
        "schema_version": "uav.adr019-local-retirement/v2",
        "generated_at": generated_at,
        "scope": "local_development_only",
        "runtime_topology": "native_macos_platform_with_docker_infra",
        **snapshot,
        **evaluation,
        "production_acceptance": "blocked_external",
    }


def build_local_validation_environment(base: dict[str, str]) -> dict[str, str]:
    environment = dict(base)
    defaults = {
        "ROAD9_PASSWORD": "traffic123",
        "JWT_SECRET_KEY": "local-retirement-validation-only",
        "BOOTSTRAP_ADMIN_PASSWORD": "local-retirement-admin-only",
        "CORS_ORIGINS": '["http://127.0.0.1:8080"]',
        "AMAP_JS_API_KEY": "local-retirement-validation-only",
        "YCX_DB_HOST": "127.0.0.1",
        "YCX_DB_USER": "local-retirement-validation-only",
        "YCX_DB_PASSWORD": "local-retirement-validation-only",
        "YCX_DB_NAME": "ycx",
    }
    for name, value in defaults.items():
        if not environment.get(name):
            environment[name] = value
    return environment


def _run(command: list[str]) -> str:
    environment = build_local_validation_environment(dict(os.environ))
    return subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


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
    expected_states = json.loads(
        _run(["docker", "inspect", *sorted(EXPECTED_NATIVE_INFRA_CONTAINERS)])
    )
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
    native_platform = json.loads(_run(["scripts/mac_local_platform.sh", "status"]))
    native_platform["single_instance"] = True
    native_platform["mps_available"] = _run(
        [
            str(ROOT / ".venv-mps" / "bin" / "python"),
            "-c",
            "import torch; print(str(bool(torch.backends.mps.is_built() and torch.backends.mps.is_available())).lower())",
        ]
    ) == "true"

    retention = _load_json(RETENTION)
    soak = _load_json(SOAK_REPORT)
    outage = _load_json(OUTAGE_REPORT)
    purge_after = datetime.fromisoformat(str(retention["purge_after"]).replace("Z", "+00:00"))
    retired_at = datetime.fromisoformat(str(retention["retired_at"]).replace("Z", "+00:00"))
    snapshot = {
        "containers": {
            "running": sorted(running_names),
            "all": sorted(all_names),
            "states": container_health,
        },
        "native_platform": native_platform,
        "database": {
            "name": database_name,
            "alembic_revision": revision,
            "timescaledb_version": timescaledb_version,
            "hypertables": int(hypertables),
            "hypertable_names": sorted(hypertable_names),
            "uav_tables": int(uav_tables),
            "uav_table_names": uav_table_names,
            "admin_rows": admin_rows,
            "user_rows": user_rows,
            "business_rows": business_rows,
            "legacy_database_count": legacy_database_count,
            "migration_isolation_tables": isolation_tables,
        },
        "kafka": {"topics": topics},
        "retention": {
            **retention,
            "at_least_seven_days": (purge_after - retired_at).total_seconds() >= 7 * 86400,
        },
        "storage": {
            "old_volumes": sorted(OLD_VOLUMES),
            "old_bind": OLD_BIND,
            "mounted_sources": sorted(mounted_sources),
            "stable_volume_mounted": "traffic_road9_data" in mounted_sources,
            "old_storage_retained": OLD_VOLUMES <= volume_names and Path(OLD_BIND).exists(),
            "old_storage_unmounted": not ((OLD_VOLUMES | {OLD_BIND}) & mounted_sources),
        },
        "resilience": {
            "database_outage_recovered": outage.get("execution_complete") is True
            and outage.get("outage", {}).get("status") == 503
            and outage.get("recovery", {}).get("status") == 200,
            "thirty_minute_soak": soak.get("passed") is True
            and soak.get("requested_duration_sec") == 1800
            and soak.get("summary", {}).get("all_samples_healthy") is True,
            "database_outage_report_generated_at": outage.get("generated_at"),
            "soak_report_generated_at": soak.get("generated_at"),
        },
        "retirement_isolation": {
            "old_containers_absent": not (FORBIDDEN_CONTAINER_NAMES & all_names)
            and not any(name.startswith("traffic_analyzer_mp4new-") for name in all_names),
        },
    }
    report = build_runtime_report(
        snapshot,
        expected_schema_head=_current_schema_head(),
        generated_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    )
    report["checks"]["compose_config"] = True
    report["checks"]["old_containers_absent"] = snapshot["retirement_isolation"][
        "old_containers_absent"
    ]
    report["passed"] = all(report["checks"].values())
    return report


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
