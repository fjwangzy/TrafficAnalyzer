#!/usr/bin/env python3
"""Read-only ADR-019 retirement readiness audit.

The audit deliberately reports blockers instead of modifying Compose or deleting
legacy assets. Use ``--strict`` in a release gate once every blocker has an
approved migration/retirement disposition.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _text(relative: str) -> str:
    path = ROOT / relative
    return path.read_text(encoding="utf-8") if path.exists() else ""


def audit() -> dict:
    compose = _text("docker-compose.yaml")
    target_compose = _text("docker-compose.road9.yaml")
    target_compose_evidence = _text("docs/test_report_i6_target_compose.json")
    settings = _text("platform/app/core/config.py")
    platform_project = _text("platform/pyproject.toml")
    platform_dockerfile = _text("platform/Dockerfile")
    main = _text("platform/app/main.py")
    restore_evidence = _text("docs/test_report_i6_road9_restore.json")
    migration_evidence = _text("docs/test_report_i6_migration_drill.json")
    legacy_inventory_evidence = _text("docs/test_report_i6_legacy_influx_inventory.json")
    performance_evidence = _text("docs/test_report_i6_local_performance.json")
    outage_evidence = _text("docs/test_report_i6_database_outage.json")
    target_stack_evidence = _text("docs/test_report_i6_target_stack.json")
    readiness_soak_evidence = _text("docs/test_report_i6_local_readiness_soak.json")
    console_sources = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in (ROOT / "console2/src").rglob("*")
        if path.is_file() and path.suffix in {".js", ".jsx", ".ts", ".tsx"}
    )

    checks = [
        {
            "code": "platform_runtime_no_influx_import",
            "status": "pass" if "InfluxQuery" not in main and "influx_query" not in main else "blocker",
            "evidence": "platform/app/main.py",
            "detail": "Platform runtime composition uses PostgresMetricStoreAdapter.",
        },
        {
            "code": "target_platform_no_influx_dependency",
            "status": "pass" if (
                "legacy-influx = [" in platform_project
                and platform_project.count('"influxdb>=5.3.2"') == 2
                and platform_project.index('"influxdb>=5.3.2"') > platform_project.index("[project.optional-dependencies]")
            ) else "blocker",
            "evidence": "platform/pyproject.toml",
            "detail": "InfluxDB client is excluded from target runtime dependencies and retained only in explicit legacy/dev extras.",
        },
        {
            "code": "target_platform_migration_and_readiness_assets",
            "status": "pass" if (
                "COPY alembic.ini ./" in platform_dockerfile
                and "COPY alembic/ ./alembic/" in platform_dockerfile
                and "http://127.0.0.1:8000/ready" in target_compose
                and "condition: service_healthy" in target_compose
            ) else "blocker",
            "evidence": "platform/Dockerfile + docker-compose.road9.yaml",
            "detail": "Target Platform image carries forward migrations and Console waits for dependency-aware readiness.",
        },
        {
            "code": "console_no_legacy_datasource",
            "status": "pass" if not any(value in console_sources.lower() for value in ("influxdb", "grafana", "telegraf")) else "blocker",
            "evidence": "console2/src",
            "detail": "Console2 formal routes must not query legacy observability services.",
        },
        {
            "code": "local_target_compose_road9_only",
            "status": "pass" if (
                "DB_NAME: road9" in target_compose
                and "timescale/timescaledb" in target_compose
                and not any(f"\n  {name}:" in target_compose for name in ("influxdb", "telegraf", "grafana"))
                and '"schema_version": "uav.road9-target-compose/v1"' in target_compose_evidence
                and '"passed": true' in target_compose_evidence
            ) else "blocker",
            "evidence": "docker-compose.road9.yaml + docs/test_report_i6_target_compose.json",
            "detail": "Independent local target stack must use road9/TimescaleDB without legacy services.",
        },
        {
            "code": "local_road9_restore_drill",
            "status": "pass" if (
                '"schema_version": "uav.road9-restore-drill/v1"' in restore_evidence
                and '"alembic_revision": "20260715_0009"' in restore_evidence
                and '"passed": true' in restore_evidence
            ) else "blocker",
            "evidence": "docs/test_report_i6_road9_restore.json",
            "detail": "Local pg_dump/pg_restore evidence must prove table counts, revision, Timescale version and hypertable count.",
        },
        {
            "code": "local_empty_migration_rollback_drill",
            "status": "pass" if (
                '"schema_version": "uav.road9-migration-drill/v1"' in migration_evidence
                and '"empty_to_head": "20260715_0009"' in migration_evidence
                and '"upgrade_after_downgrade": "20260715_0009"' in migration_evidence
                and '"passed": true' in migration_evidence
            ) else "blocker",
            "evidence": "docs/test_report_i6_migration_drill.json",
            "detail": "Empty database and 0009 downgrade/re-upgrade drill must be reproducible and cleaned up.",
        },
        {
            "code": "legacy_influx_read_only_inventory",
            "status": "pass" if (
                '"schema_version": "uav.legacy-influx-inventory/v1"' in legacy_inventory_evidence
                and '"mode": "read_only"' in legacy_inventory_evidence
                and '"inventory_complete": true' in legacy_inventory_evidence
                and legacy_inventory_evidence.count('"mapping_status": "unverified"') == 3
                and '"classification": "relative_or_invalid_epoch"' in legacy_inventory_evidence
            ) else "blocker",
            "evidence": "scripts/inventory_legacy_influx.py + docs/test_report_i6_legacy_influx_inventory.json",
            "detail": "Legacy measurement fields, tags, counts and time boundaries are inventoried read-only without approving a backfill.",
        },
        {
            "code": "local_non_contract_performance_smoke",
            "status": "pass" if (
                '"schema_version": "uav.i6-local-performance-smoke/v1"' in performance_evidence
                and '"environment": "local_non_contract"' in performance_evidence
                and '"threshold_status": "unverified"' in performance_evidence
                and '"execution_complete": true' in performance_evidence
                and '"all_requests_http_200": true' in performance_evidence
                and '"status": "blocked_external"' in performance_evidence
            ) else "blocker",
            "evidence": "scripts/validate_i6_local_performance.py + docs/test_report_i6_local_performance.json",
            "detail": "Guarded localhost read-only smoke is reproducible while production thresholds remain unverified.",
        },
        {
            "code": "local_isolated_database_outage_recovery",
            "status": "pass" if (
                '"schema_version": "uav.i6-local-database-outage/v1"' in outage_evidence
                and '"environment": "isolated_local_non_contract"' in outage_evidence
                and '"baseline_status": 200' in outage_evidence
                and '"status": 503' in outage_evidence
                and '"code": "dashboard_dependency_unavailable"' in outage_evidence
                and '"execution_complete": true' in outage_evidence
            ) else "blocker",
            "evidence": "scripts/validate_i6_database_outage.py + docs/test_report_i6_database_outage.json",
            "detail": "Isolated road9 outage produces structured 503 and recovers to HTTP 200 without touching the development database.",
        },
        {
            "code": "local_full_target_stack",
            "status": "pass" if (
                '"schema_version": "uav.i6-target-stack/v1"' in target_stack_evidence
                and '"alembic_revision": "20260715_0009"' in target_stack_evidence
                and '"image_mode": "apache_kraft"' in target_stack_evidence
                and '"influxdb_module": null' in target_stack_evidence
                and '"openapi_paths": 94' in target_stack_evidence
                and '"openapi_operations": 110' in target_stack_evidence
                and '"passed": true' in target_stack_evidence
            ) else "blocker",
            "evidence": "docker-compose.road9.yaml + scripts/validate_i6_target_stack.py + docs/test_report_i6_target_stack.json",
            "detail": "Full local road9/KRaft/Platform/Console2 target stack builds, migrates, becomes ready and serves authenticated APIs.",
        },
        {
            "code": "local_non_contract_readiness_soak",
            "status": "pass" if (
                '"schema_version": "uav.i6-local-readiness-soak/v1"' in readiness_soak_evidence
                and '"environment": "isolated_local_non_contract"' in readiness_soak_evidence
                and '"threshold_status": "unverified"' in readiness_soak_evidence
                and '"execution_complete": true' in readiness_soak_evidence
                and '"all_samples_healthy": true' in readiness_soak_evidence
                and '"passed": true' in readiness_soak_evidence
                and '"status": "blocked_external"' in readiness_soak_evidence
            ) else "blocker",
            "evidence": "scripts/validate_i6_local_readiness_soak.py + docs/test_report_i6_local_readiness_soak.json",
            "detail": "Guarded short local soak checks Platform readiness and authenticated Console APIs without approving sustained-run thresholds.",
        },
        {
            "code": "compose_database_road9",
            "status": "pass" if "DB_NAME: road9" in compose else "blocker",
            "evidence": "docker-compose.yaml",
            "detail": "Platform Compose still needs database=road9 before target deployment.",
        },
        {
            "code": "compose_no_legacy_services",
            "status": "pass" if not any(f"\n  {name}:" in compose for name in ("influxdb", "telegraf", "grafana")) else "blocker",
            "evidence": "docker-compose.yaml",
            "detail": "Legacy services remain in the current regression Compose and cannot be removed before migration reconciliation and rollback approval.",
        },
        {
            "code": "compose_platform_no_influx_dependency",
            "status": "pass" if "INFLUX_HOST:" not in compose and "condition: service_started" not in compose else "blocker",
            "evidence": "docker-compose.yaml",
            "detail": "Platform container still declares Influx settings/dependency in Compose.",
        },
        {
            "code": "settings_no_influx_contract",
            "status": "pass" if "influx_host:" not in settings else "blocker",
            "evidence": "platform/app/core/config.py",
            "detail": "Legacy Influx settings remain as migration inventory.",
        },
        {
            "code": "legacy_query_archived_or_removed",
            "status": "pass" if not (ROOT / "platform/app/utils/influx_query.py").exists() else "blocker",
            "evidence": "platform/app/utils/influx_query.py",
            "detail": "Legacy query helper remains for regression/migration comparison.",
        },
        {
            "code": "retirement_approval_inputs",
            "status": "blocked_external",
            "evidence": "S7-TBD-003/004/009/012/013",
            "detail": "Pilot scope, performance environment, RPO/RTO, historical mapping, reconciliation thresholds, observation window and retirement date require written approval.",
        },
    ]
    blockers = [item for item in checks if item["status"] != "pass"]
    return {
        "schema_version": "uav.adr019-retirement-audit/v1",
        "ready": not blockers,
        "summary": {"passed": len(checks) - len(blockers), "blocked": len(blockers), "total": len(checks)},
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--format", choices=("json", "text"), default="text")
    parser.add_argument("--strict", action="store_true", help="return non-zero while retirement is blocked")
    args = parser.parse_args()
    result = audit()
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"ADR-019 retirement ready: {result['ready']}")
        for item in result["checks"]:
            print(f"[{item['status']}] {item['code']}: {item['detail']}")
    return 1 if args.strict and not result["ready"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
