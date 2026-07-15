#!/usr/bin/env python3
"""Exercise local road9 outage and recovery in an isolated Docker project."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = ROOT / "docker-compose.road9.yaml"
PROJECT = "traffic_analyzer_i6_fault"
DB_PORT = "6545"
PLATFORM_PORT = 18006
BASE_URL = f"http://127.0.0.1:{PLATFORM_PORT}"


def _compose(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["ROAD9_PORT"] = DB_PORT
    return subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "-p", PROJECT, *arguments],
        cwd=ROOT,
        env=environment,
        check=check,
        capture_output=True,
        text=True,
    )


def _http_json(path: str, *, token: str | None = None, body: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    headers = {"Accept": "application/json"}
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        headers=headers,
        method="POST" if body is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"raw_body": raw[:500]}
        return exc.code, payload


def _wait_for(predicate, *, timeout_sec: float, interval_sec: float = 0.25):
    deadline = time.monotonic() + timeout_sec
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            value = predicate()
            if value:
                return value
        except Exception as exc:
            last_error = exc
        time.sleep(interval_sec)
    if last_error:
        raise TimeoutError(f"condition did not become ready: {last_error}") from last_error
    raise TimeoutError("condition did not become ready")


def _wait_database() -> None:
    _wait_for(
        lambda: _compose("exec", "-T", "road9", "pg_isready", "-U", "traffic", "-d", "road9", check=False).returncode == 0,
        timeout_sec=45,
        interval_sec=1,
    )


def run_drill() -> dict[str, Any]:
    if os.getenv("ALLOW_LOCAL_DB_OUTAGE_DRILL") != "1":
        raise RuntimeError("set ALLOW_LOCAL_DB_OUTAGE_DRILL=1 to run the isolated destructive drill")
    if _compose("ps", "-q", "road9", check=False).stdout.strip():
        raise RuntimeError(f"isolated Compose project {PROJECT} already exists; inspect it before retrying")

    platform_process: subprocess.Popen[bytes] | None = None
    log_file = tempfile.TemporaryFile()
    started_at = datetime.now(tz=UTC)
    try:
        _compose("up", "-d", "road9")
        _wait_database()

        environment = os.environ.copy()
        environment.update(
            {
                "DEBUG": "false",
                "SERVICE_PORT": str(PLATFORM_PORT),
                "DB_HOST": "127.0.0.1",
                "DB_PORT": DB_PORT,
                "DB_USER": "traffic",
                "DB_PASSWORD": "traffic123",
                "DB_NAME": "road9",
                "DB_BOOTSTRAP_DATABASE": "postgres",
                "DB_LEGACY_NAME": "road9",
                "KAFKA_BOOTSTRAP": "127.0.0.1:9092",
                "KAFKA_CONSUMER_GROUP": "uav-i6-fault-drill",
                "JWT_SECRET_KEY": "local-i6-fault-drill-only",
                "SURVEY_STORAGE_DIR": "/tmp/traffic-survey-i6-fault",
            }
        )
        platform_process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(PLATFORM_PORT)],
            cwd=ROOT / "platform",
            env=environment,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )

        _wait_for(lambda: _http_json("/health")[0] == 200, timeout_sec=60)
        login_status, login = _http_json(
            "/api/v1/auth/login",
            body={"username": "admin", "password": "admin123"},
        )
        if login_status != 200 or not login.get("access_token"):
            raise RuntimeError("isolated Platform did not create the local admin login")
        token = str(login["access_token"])

        baseline_status, _ = _http_json("/api/v1/dashboard/overview", token=token)
        if baseline_status != 200:
            raise RuntimeError(f"baseline dashboard status was {baseline_status}")

        outage_started = time.monotonic()
        _compose("stop", "road9")
        outage = _wait_for(
            lambda: (result if (result := _http_json("/api/v1/dashboard/overview", token=token))[0] != 200 else None),
            timeout_sec=20,
        )
        detected_after_sec = time.monotonic() - outage_started

        recovery_started = time.monotonic()
        _compose("start", "road9")
        _wait_database()
        recovery = _wait_for(
            lambda: (result if (result := _http_json("/api/v1/dashboard/overview", token=token))[0] == 200 else None),
            timeout_sec=45,
        )
        recovered_after_sec = time.monotonic() - recovery_started

        outage_detail = outage[1].get("detail", {})
        return {
            "schema_version": "uav.i6-local-database-outage/v1",
            "generated_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
            "environment": "isolated_local_non_contract",
            "compose_project": PROJECT,
            "database": "road9",
            "baseline_status": baseline_status,
            "outage": {
                "status": outage[0],
                "code": outage_detail.get("code"),
                "detected_after_sec": round(detected_after_sec, 3),
            },
            "recovery": {
                "status": recovery[0],
                "recovered_after_sec": round(recovered_after_sec, 3),
            },
            "execution_complete": baseline_status == 200 and outage[0] == 503 and recovery[0] == 200,
            "elapsed_sec": round((datetime.now(tz=UTC) - started_at).total_seconds(), 3),
            "acceptance": {
                "status": "blocked_external",
                "detail": "This isolated single-instance drill does not approve production RTO/RPO, HA, data-loss, sustained-load or rollback requirements.",
            },
        }
    finally:
        if platform_process and platform_process.poll() is None:
            platform_process.terminate()
            try:
                platform_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                platform_process.kill()
                platform_process.wait(timeout=5)
        log_file.close()
        _compose("down", "-v", "--remove-orphans", check=False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_drill()
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["execution_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
