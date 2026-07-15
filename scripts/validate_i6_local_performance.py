#!/usr/bin/env python3
"""Run a guarded, read-only Platform performance smoke on localhost.

The result is an engineering baseline, not a contract acceptance result.  No
latency threshold is embedded because the production hardware, traffic model
and SLO remain external approval inputs.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any


DEFAULT_BASE_URL = "http://127.0.0.1:18004"
ENDPOINTS = (
    "/api/v1/dashboard/overview",
    "/api/v1/dashboard/intersections",
    "/api/v1/dashboard/drones",
    "/api/v1/system/health",
)


def _validate_local_url(base_url: str) -> str:
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("performance smoke is restricted to an explicit local HTTP endpoint")
    return base_url.rstrip("/")


def _request_json(url: str, *, body: dict[str, Any] | None = None, token: str | None = None) -> tuple[int, dict[str, Any]]:
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if body is not None else "GET")
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
        return response.status, payload


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) * percentile + 0.999999)) - 1))
    return ordered[index]


def _sample(base_url: str, endpoint: str, token: str) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        status, _ = _request_json(f"{base_url}{endpoint}", token=token)
        error = None
    except urllib.error.HTTPError as exc:
        status = exc.code
        error = f"http_{exc.code}"
    except Exception as exc:  # network failure is part of the smoke evidence
        status = 0
        error = type(exc).__name__
    return {
        "endpoint": endpoint,
        "status": status,
        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        "error": error,
    }


def run_smoke(base_url: str, requests: int, concurrency: int) -> dict[str, Any]:
    if os.getenv("ALLOW_LOCAL_PERF_SMOKE") != "1":
        raise RuntimeError("set ALLOW_LOCAL_PERF_SMOKE=1 to run the guarded localhost smoke")
    if requests < len(ENDPOINTS) or requests > 10_000:
        raise ValueError("requests must be between 4 and 10000")
    if concurrency < 1 or concurrency > 64:
        raise ValueError("concurrency must be between 1 and 64")
    base_url = _validate_local_url(base_url)
    username = os.getenv("I6_USERNAME")
    password = os.getenv("I6_PASSWORD")
    if not username or not password:
        raise RuntimeError("I6_USERNAME and I6_PASSWORD are required; credentials are never written to evidence")

    status, login = _request_json(
        f"{base_url}/api/v1/auth/login",
        body={"username": username, "password": password},
    )
    if status != 200 or not login.get("access_token"):
        raise RuntimeError("local authentication did not return an access token")
    token = str(login["access_token"])

    started = time.perf_counter()
    samples = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(_sample, base_url, ENDPOINTS[index % len(ENDPOINTS)], token) for index in range(requests)]
        for future in as_completed(futures):
            samples.append(future.result())
    elapsed = time.perf_counter() - started

    endpoints = []
    for endpoint in ENDPOINTS:
        subset = [sample for sample in samples if sample["endpoint"] == endpoint]
        latencies = [float(sample["latency_ms"]) for sample in subset]
        successes = sum(sample["status"] == 200 for sample in subset)
        endpoints.append(
            {
                "endpoint": endpoint,
                "requests": len(subset),
                "successes": successes,
                "errors": len(subset) - successes,
                "p50_ms": round(median(latencies), 3) if latencies else 0.0,
                "p95_ms": round(_percentile(latencies, 0.95), 3),
                "max_ms": round(max(latencies), 3) if latencies else 0.0,
                "statuses": {str(code): sum(sample["status"] == code for sample in subset) for code in sorted({sample["status"] for sample in subset})},
            }
        )

    total_successes = sum(sample["status"] == 200 for sample in samples)
    return {
        "schema_version": "uav.i6-local-performance-smoke/v1",
        "generated_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "environment": "local_non_contract",
        "base_url": base_url,
        "method": "authenticated_read_only_get",
        "threshold_status": "unverified",
        "execution_complete": len(samples) == requests,
        "all_requests_http_200": total_successes == requests,
        "summary": {
            "requests": requests,
            "concurrency": concurrency,
            "successes": total_successes,
            "errors": requests - total_successes,
            "elapsed_sec": round(elapsed, 3),
            "throughput_requests_per_sec": round(requests / elapsed, 3) if elapsed else 0.0,
        },
        "endpoints": endpoints,
        "acceptance": {
            "status": "blocked_external",
            "detail": "Production hardware, workload, duration, latency/error thresholds and sign-off are not approved; this local smoke is diagnostic evidence only.",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--requests", type=int, default=80)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_smoke(args.base_url, args.requests, args.concurrency)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["all_requests_http_200"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
