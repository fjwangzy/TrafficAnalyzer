#!/usr/bin/env python3
"""Audit ADR-019 retirement for local development or production scope."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCAL_REPORT = ROOT / "docs" / "test_report_adr019_local_retirement.json"
GCJ02_REBUILD_REPORT = ROOT / "docs" / "test_report_gcj02_rebuild_local.json"


def _text(relative: str) -> str:
    path = ROOT / relative
    return path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""


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


def _report_passed() -> bool:
    try:
        rebuild = json.loads(GCJ02_REBUILD_REPORT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        rebuild = {}
    if (
        rebuild.get("schema_version") == "uav.gcj02-local-rebuild/v1"
        and rebuild.get("passed") is True
        and rebuild.get("database", {}).get("alembic_revision") == _current_schema_head()
        and rebuild.get("database", {}).get("hypertables") == 5
        and rebuild.get("database", {}).get("business_tables_empty") is True
        and not rebuild.get("raw_materials", {}).get("missing_files")
        and not rebuild.get("kafka", {}).get("nonzero_end_offsets")
        and not rebuild.get("kafka", {}).get("managed_consumer_groups_remaining")
    ):
        return True
    try:
        report = json.loads(LOCAL_REPORT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        report.get("schema_version") == "uav.adr019-local-retirement/v1"
        and report.get("passed") is True
        and report.get("database", {}).get("alembic_revision") == _current_schema_head()
        and report.get("database", {}).get("hypertables") == 5
    )


def audit(scope: str = "production") -> dict:
    compose = _text("docker-compose.yaml")
    settings = _text("platform/app/core/config.py")
    database = _text("platform/app/core/database.py")
    metric_store = _text("platform/app/services/metric_store.py")
    consumer = _text("platform/app/kafka/consumer.py")
    ws_manager = _text("platform/app/kafka/ws_manager.py")
    platform_project = _text("platform/pyproject.toml")
    realtime = _text("console2/src/lib/realtime.js")
    nginx = _text("services/nginx/nginx.conf")
    purge = _text("scripts/purge_adr019_legacy_storage.py")
    mac_local_platform = _text("scripts/mac_local_platform.sh")

    checks = [
        {
            "code": "canonical_root_compose",
            "status": "pass" if (
                "apache/kafka:3.9.2" in compose
                and "timescale/timescaledb" in compose
                and "DB_NAME: road9" in compose
                and not any(f"\n  {name}:" in compose for name in (
                    "postgres", "influxdb", "telegraf", "grafana", "zookeeper", "timescaledb_local"
                ))
            ) else "blocker",
            "evidence": "docker-compose.yaml",
            "detail": "生产根 Compose 仅保留 road9/TimescaleDB、KRaft、Platform、Console2、Nginx 与可选服务。",
        },
        {
            "code": "stable_clean_road9_volume",
            "status": "pass" if (
                "${ROAD9_VOLUME_NAME:-traffic_road9_data}" in compose
                and not any(name in compose for name in (
                    "trafficanalyzer_postgres_data",
                    "trafficanalyzer_timescaledb_local_data",
                    "traffic_analyzer_mp4new_road9_target_data",
                    "services/influxdb_data",
                ))
            ) else "blocker",
            "evidence": "docker-compose.yaml",
            "detail": "正式 road9 使用稳定新卷且不挂载任何旧存储。",
        },
        {
            "code": "single_compose_topology",
            "status": "pass" if not (ROOT / "docker-compose.road9.yaml").exists() else "blocker",
            "evidence": "docker-compose.yaml",
            "detail": "不存在重复的完整 road9 Compose。",
        },
        {
            "code": "platform_no_legacy_database_or_influx",
            "status": "pass" if not any(token in (settings + database + platform_project).lower() for token in (
                "db_legacy_name", "migrate_legacy_core_data", "admin@traffic.local",
                "influx_host", "influxdb>=", "legacy-influx"
            )) and not (ROOT / "platform/app/utils/influx_query.py").exists() else "blocker",
            "evidence": "platform/app/core + platform/pyproject.toml",
            "detail": "Platform 不包含旧库自动迁移、Influx 配置、客户端或依赖。",
        },
        {
            "code": "canonical_runtime_contract_only",
            "status": "pass" if (
                "LEGACY_TYPES" not in metric_store
                and "unsupported canonical msg_type" in metric_store
                and "CANONICAL_TOPIC_PATTERNS" in metric_store
                and "unsupported canonical topic" in metric_store
                and '"statistics_"' not in consumer
                and 'if "intersection_" in topic' not in consumer
                and "_is_canonical_message_type" in ws_manager
                and 'msg.get("type", "stats")' not in ws_manager
                and "`intersection:${intersectionId}`" not in realtime
                and "`telemetry:${droneId}`" not in realtime
                and "`alerts:${intersectionId}`" not in realtime
            ) else "blocker",
            "evidence": "platform/app/kafka + platform/app/services/metric_store.py + console2/src/lib/realtime.js",
            "detail": "Kafka msg_type/Topic 与 WebSocket channel 仅接受 uav_ canonical 契约。",
        },
        {
            "code": "legacy_runtime_assets_removed",
            "status": "pass" if not any((ROOT / path).exists() for path in (
                "platform/gateway", "platform/services", "platform/shared", "platform/frontend", "platform/docker",
                "services/grafana", "services/telegraf", "export_dashboards.py", "fetch_dashboard.py",
                "update_dashboards.py", "test_grafana_provisioning.py",
            )) else "blocker",
            "evidence": "platform/ + services/ + root scripts",
            "detail": "旧微服务、旧 Platform Compose 与 Grafana/Telegraf 资产已删除。",
        },
        {
            "code": "nginx_uses_compose_dns",
            "status": "pass" if "http://platform:8000" in nginx and "traffic_platform" not in nginx else "blocker",
            "evidence": "services/nginx/nginx.conf",
            "detail": "Nginx 使用 Compose service DNS。",
        },
        {
            "code": "guarded_retention_cleanup",
            "status": "pass" if all(token in purge for token in (
                "ALLOW_ADR019_LEGACY_PURGE", "purge_after", "FIXED_VOLUME_ALLOWLIST", "FIXED_BIND_ALLOWLIST"
            )) else "blocker",
            "evidence": "scripts/purge_adr019_legacy_storage.py",
            "detail": "旧存储清理具有固定 allowlist、7 天到期校验和显式确认开关。",
        },
        {
            "code": "native_mac_development_contract",
            "status": "pass" if (
                'DEPLOYMENT_MODE: "production"' in compose
                and "PIPELINE_DEVICE=mps" in mac_local_platform
                and "scripts/mac_local_platform.sh" not in compose
                and "PIPELINE_REMOTE_" not in compose
                and "host.docker.internal" not in compose
            ) else "blocker",
            "evidence": "docker-compose.yaml + scripts/mac_local_platform.sh",
            "detail": "Mac 开发态原生运行 Platform/MPS，Docker Compose 只承担生产发布。",
        },
        {
            "code": "local_runtime_evidence",
            "status": "pass" if _report_passed() else "blocker",
            "evidence": f"{LOCAL_REPORT.relative_to(ROOT)} + {GCJ02_REBUILD_REPORT.relative_to(ROOT)}",
            "detail": "ADR-019 基线和 GCJ-02 清库重建、原始素材哈希、Kafka 空状态已有执行证据。",
        },
    ]
    if scope == "production":
        checks.append({
            "code": "production_retirement_approval",
            "status": "blocked_external",
            "evidence": "production change control",
            "detail": "本任务仅完成本机开发环境；生产安全、HA、RPO/RTO 与退役窗口仍需外部门禁。",
        })
    blockers = [item for item in checks if item["status"] != "pass"]
    return {
        "schema_version": "uav.adr019-retirement-audit/v2",
        "scope": scope,
        "ready": not blockers,
        "summary": {"passed": len(checks) - len(blockers), "blocked": len(blockers), "total": len(checks)},
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", choices=("local", "production"), default="production")
    parser.add_argument("--format", choices=("json", "text"), default="text")
    parser.add_argument("--strict", action="store_true", help="return non-zero while selected scope is blocked")
    args = parser.parse_args()
    result = audit(args.scope)
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"ADR-019 retirement scope={args.scope} ready: {result['ready']}")
        for item in result["checks"]:
            print(f"[{item['status']}] {item['code']}: {item['detail']}")
    return 1 if args.strict and not result["ready"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
