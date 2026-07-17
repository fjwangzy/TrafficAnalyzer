#!/usr/bin/env python3
"""Run a guarded readiness soak against a local ADR-019 stack.

This is deliberately a local, non-contract check. It cannot approve production
availability, performance thresholds, high availability, RPO/RTO, or the
retirement of the legacy observability stack.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable


PLATFORM_URL = os.getenv("PLATFORM_URL", "http://127.0.0.1:18007")
CONSOLE_URL = os.getenv("CONSOLE_URL", "http://127.0.0.1:4178")
MIN_DURATION_SEC = 10
MAX_DURATION_SEC = 1800
MIN_INTERVAL_SEC = 1
MAX_INTERVAL_SEC = 30


def _http_json(
    url: str,
    *,
    token: str | None = None,
    body: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    headers = {"Accept": "application/json"}
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url,
        headers=headers,
        data=data,
        method="POST" if body is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            payload = {"raw": raw}
        return exc.code, payload
    except urllib.error.URLError as exc:
        return 0, {"error": str(exc.reason)}


def _probe_sample() -> dict[str, Any]:
    started = time.perf_counter()
    ready_status, ready = _http_json(f"{PLATFORM_URL}/ready")
    login_status, login = _http_json(
        f"{CONSOLE_URL}/api/v1/auth/login",
        body={"username": "admin", "password": "admin123"},
    )
    token = str(login.get("access_token", "")) if isinstance(login, dict) else ""
    dashboard_status, dashboard = _http_json(
        f"{CONSOLE_URL}/api/v1/dashboard/overview",
        token=token,
    )
    system_status, system_health = _http_json(
        f"{CONSOLE_URL}/api/v1/system/health",
        token=token,
    )
    checks = {
        "platform_ready": ready_status == 200 and isinstance(ready, dict) and ready.get("status") == "ready",
        "console_login": login_status == 200 and bool(token),
        "dashboard": (
            dashboard_status == 200
            and isinstance(dashboard, dict)
            and dashboard.get("schema_version") == "uav.dashboard/v1"
        ),
        "system_health": system_status == 200 and isinstance(system_health, dict),
    }
    payloads = {
        "ready": ready,
        "login": login,
        "dashboard": dashboard,
        "system_health": system_health,
    }
    return {
        "observed_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "statuses": {
            "ready": ready_status,
            "login": login_status,
            "dashboard": dashboard_status,
            "system_health": system_status,
        },
        "services": ready.get("services", {}) if isinstance(ready, dict) else {},
        "dashboard_quality_status": dashboard.get("quality_status") if isinstance(dashboard, dict) else None,
        "probe_errors": {
            name: payload
            for name, payload in payloads.items()
            if not checks[
                {
                    "ready": "platform_ready",
                    "login": "console_login",
                    "dashboard": "dashboard",
                    "system_health": "system_health",
                }[name]
            ]
        },
        "checks": checks,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
    }


def _summarize(samples: list[dict[str, Any]]) -> dict[str, Any]:
    if not samples:
        return {
            "sample_count": 0,
            "all_samples_healthy": False,
            "ready_ratio": 0.0,
            "max_latency_ms": None,
            "p95_latency_ms": None,
        }
    healthy_samples = [sample for sample in samples if all(sample["checks"].values())]
    ready_samples = [sample for sample in samples if sample["checks"].get("platform_ready")]
    latencies = sorted(float(sample["latency_ms"]) for sample in samples)
    p95_index = max(0, math.ceil(len(latencies) * 0.95) - 1)
    return {
        "sample_count": len(samples),
        "all_samples_healthy": len(healthy_samples) == len(samples),
        "ready_ratio": len(ready_samples) / len(samples),
        "max_latency_ms": max(latencies),
        "p95_latency_ms": latencies[p95_index],
    }


def validate(
    *,
    duration_sec: int = 60,
    interval_sec: int = 5,
    probe: Callable[[], dict[str, Any]] | None = None,
    clock: Callable[[], float] | None = None,
    sleeper: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    if os.getenv("ALLOW_LOCAL_READINESS_SOAK") != "1":
        raise RuntimeError("set ALLOW_LOCAL_READINESS_SOAK=1 to run the localhost soak")
    if not MIN_DURATION_SEC <= duration_sec <= MAX_DURATION_SEC:
        raise ValueError(f"duration must be between {MIN_DURATION_SEC} and {MAX_DURATION_SEC} seconds")
    if not MIN_INTERVAL_SEC <= interval_sec <= MAX_INTERVAL_SEC:
        raise ValueError(f"interval must be between {MIN_INTERVAL_SEC} and {MAX_INTERVAL_SEC} seconds")

    probe = probe or _probe_sample
    clock = clock or time.monotonic
    sleeper = sleeper or time.sleep
    started = clock()
    samples: list[dict[str, Any]] = []
    elapsed = 0.0
    stopped_early = False
    while True:
        sample = probe()
        samples.append(sample)
        elapsed = clock() - started
        if not all(sample["checks"].values()):
            stopped_early = True
            break
        if elapsed >= duration_sec:
            break
        sleeper(min(float(interval_sec), duration_sec - elapsed))

    summary = _summarize(samples)
    execution_complete = not stopped_early and elapsed >= duration_sec and summary["sample_count"] >= 3
    passed = execution_complete and summary["all_samples_healthy"]
    return {
        "schema_version": "uav.i6-local-readiness-soak/v1",
        "generated_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "environment": "local_development_only",
        "targets": {"platform": PLATFORM_URL, "console": CONSOLE_URL},
        "threshold_status": "unverified",
        "requested_duration_sec": duration_sec,
        "interval_sec": interval_sec,
        "execution_complete": execution_complete,
        "stopped_early": stopped_early,
        "observed_duration_sec": round(elapsed, 3),
        "summary": summary,
        "samples": samples,
        "passed": passed,
        "acceptance": {
            "status": "blocked_external",
            "detail": (
                "A local soak does not approve production thresholds, HA, capacity, "
                "RPO/RTO, sustained observation duration, or legacy retirement."
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration-sec", type=int, default=60)
    parser.add_argument("--interval-sec", type=int, default=5)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate(duration_sec=args.duration_sec, interval_sec=args.interval_sec)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
