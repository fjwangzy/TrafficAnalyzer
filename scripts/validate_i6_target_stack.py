#!/usr/bin/env python3
"""Validate the isolated full ADR-019 target Compose stack."""

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


PROJECT = "traffic_analyzer_i6_target_full"
PLATFORM_URL = "http://127.0.0.1:18007"
CONSOLE_URL = "http://127.0.0.1:4178"
CONTAINERS = {
    "road9": f"{PROJECT}-road9-1",
    "kafka": f"{PROJECT}-kafka-1",
    "platform": f"{PROJECT}-platform-1",
    "console2": f"{PROJECT}-console2-1",
}


def _run(command: list[str]) -> str:
    return subprocess.run(command, check=True, capture_output=True, text=True).stdout.strip()


def _http_json(url: str, *, token: str | None = None, body: dict[str, Any] | None = None) -> tuple[int, Any]:
    headers = {"Accept": "application/json"}
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, headers=headers, data=data, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return exc.code, json.loads(raw) if raw else None


def _container_state(name: str) -> dict[str, str]:
    output = _run(
        [
            "docker",
            "inspect",
            "--format",
            "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
            name,
        ]
    )
    status, health = output.split("|", maxsplit=1)
    return {"status": status, "health": health}


def validate() -> dict[str, Any]:
    if os.getenv("ALLOW_LOCAL_TARGET_STACK_CHECK") != "1":
        raise RuntimeError("set ALLOW_LOCAL_TARGET_STACK_CHECK=1 to inspect the fixed isolated target stack")

    containers = {service: _container_state(name) for service, name in CONTAINERS.items()}
    ready_status, ready = _http_json(f"{PLATFORM_URL}/ready")
    login_status, login = _http_json(
        f"{CONSOLE_URL}/api/v1/auth/login",
        body={"username": "admin", "password": "admin123"},
    )
    token = str(login.get("access_token", "")) if isinstance(login, dict) else ""
    dashboard_status, dashboard = _http_json(f"{CONSOLE_URL}/api/v1/dashboard/overview", token=token)
    system_status, system_health = _http_json(f"{CONSOLE_URL}/api/v1/system/health", token=token)
    openapi_status, openapi = _http_json(f"{PLATFORM_URL}/openapi.json")
    operation_methods = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}
    paths = openapi.get("paths", {}) if isinstance(openapi, dict) else {}
    operations = sum(
        method.lower() in operation_methods
        for path_item in paths.values()
        if isinstance(path_item, dict)
        for method in path_item
    )

    influx_spec = _run(
        [
            "docker",
            "exec",
            CONTAINERS["platform"],
            "python",
            "-c",
            "import importlib.util; print(importlib.util.find_spec('influxdb'))",
        ]
    )
    database_raw = _run(
        [
            "docker",
            "exec",
            CONTAINERS["road9"],
            "psql",
            "-U",
            "traffic",
            "-d",
            "road9",
            "-At",
            "-F",
            "|",
            "-c",
            "SELECT (SELECT version_num FROM uav_alembic_version LIMIT 1), extversion, (SELECT count(*) FROM timescaledb_information.hypertables), (SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name LIKE 'uav_%') FROM pg_extension WHERE extname='timescaledb'",
        ]
    )
    revision, timescaledb_version, hypertables, uav_tables = database_raw.split("|", maxsplit=3)
    topics = _run(
        [
            "docker",
            "exec",
            CONTAINERS["kafka"],
            "/opt/kafka/bin/kafka-topics.sh",
            "--bootstrap-server",
            "localhost:29092",
            "--list",
        ]
    ).splitlines()

    checks = {
        "containers_running": all(state["status"] == "running" for state in containers.values()),
        "dependency_health": all(containers[name]["health"] == "healthy" for name in ("road9", "kafka", "platform")),
        "platform_ready": ready_status == 200 and ready.get("status") == "ready",
        "console_proxy_login": login_status == 200 and bool(token),
        "dashboard_via_console": dashboard_status == 200 and dashboard.get("schema_version") == "uav.dashboard/v1",
        "system_health_via_console": system_status == 200 and isinstance(system_health, dict),
        "openapi_available": openapi_status == 200 and len(paths) > 0 and operations > 0,
        "target_image_without_influx_client": influx_spec == "None",
        "road9_at_head": revision == "20260715_0010",
        "timescaledb_hypertables": int(hypertables) == 5,
        "canonical_kafka_topic": "uav_statistics_i6_probe" in topics,
    }
    return {
        "schema_version": "uav.i6-target-stack/v1",
        "generated_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "environment": "isolated_local_non_contract",
        "project": PROJECT,
        "containers": containers,
        "database": {
            "name": "road9",
            "alembic_revision": revision,
            "timescaledb_version": timescaledb_version,
            "hypertables": int(hypertables),
            "uav_tables": int(uav_tables),
        },
        "api": {
            "ready": ready,
            "openapi_paths": len(paths),
            "openapi_operations": operations,
            "dashboard_quality_status": dashboard.get("quality_status") if isinstance(dashboard, dict) else None,
        },
        "kafka": {"image_mode": "apache_kraft", "canonical_probe_topic": "uav_statistics_i6_probe"},
        "target_image": {"influxdb_module": None if influx_spec == "None" else influx_spec},
        "checks": checks,
        "passed": all(checks.values()),
        "acceptance": {
            "status": "blocked_external",
            "detail": "Local full-stack startup does not approve production image pins, secrets, TLS/SASL, HA, capacity, RPO/RTO or retirement.",
        },
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
