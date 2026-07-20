#!/usr/bin/env python3
"""Prove local replay Pipelines start without lane annotation parameters.

The historical filename is retained so existing operator commands keep working.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from bootstrap_mp4new_sources import LOCAL_REPLAY_CATALOG  # noqa: E402


def _one_source_per_intersection() -> list[dict]:
    selected: list[dict] = []
    for intersection in LOCAL_REPLAY_CATALOG:
        source = next(
            (item for item in intersection["sources"] if item.get("known_degradation") is None),
            intersection["sources"][0],
        )
        selected.append({**intersection, **source})
    return selected


async def _json(client: httpx.AsyncClient, method: str, url: str, **kwargs):
    response = await client.request(method, url, **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {url}: HTTP {response.status_code}: {response.text[:1000]}")
    return response.json() if response.content else {}


async def _stop(client: httpx.AsyncClient, mission_id: str) -> dict:
    mission = await _json(client, "GET", f"/api/v1/missions/{mission_id}")
    if mission.get("status") not in {"pending", "starting", "running"}:
        return mission
    return await _json(
        client,
        "POST",
        f"/api/v1/missions/{mission_id}/stop",
        json={"reason": "no_lane_parameters_validation_complete"},
    )


async def _validate_one(
    client: httpx.AsyncClient,
    source: dict,
) -> dict:
    inter_id = source["inter_id"]
    mission = await _json(
        client,
        "POST",
        "/api/v1/missions",
        json={
            "name": f"lane reuse validation {inter_id}",
            "drone_id": source["drone_id"],
            "source_profile_id": source["profile_id"],
            "inter_id": inter_id,
            "road_data_version": source["road_data_version"],
            "scheduled_end_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        },
    )
    mission_id = mission["id"]
    result = {
        "inter_id": inter_id,
        "profile_id": source["profile_id"],
        "mission_id": mission_id,
        "pipeline_id": mission.get("pipeline_id"),
        "expected_roads_json": "",
    }
    try:
        if mission.get("status") != "running" or not mission.get("pipeline_id"):
            result.update({"passed": False, "error": mission.get("error_message") or "mission_not_running"})
            return result
        pipeline = await _json(client, "GET", f"/api/v1/pipelines/{mission['pipeline_id']}")
        result["actual_roads_json"] = pipeline.get("roads_json")
        result["lane_parameters_disabled"] = pipeline.get("roads_json") == ""
        result["camera_id"] = pipeline.get("camera_id")
        result["passed"] = bool(result["lane_parameters_disabled"] and result["camera_id"] is not None)
        if not result["passed"]:
            result["error"] = "pipeline_lane_parameters_not_empty"
        return result
    finally:
        result["final_mission"] = (await _stop(client, mission_id)).get("status")


async def main_async(args: argparse.Namespace) -> int:
    async with httpx.AsyncClient(base_url=args.base_url, timeout=60) as client:
        login = await _json(
            client,
            "POST",
            "/api/v1/auth/login",
            json={"username": args.username, "password": args.password},
        )
        client.headers["Authorization"] = f"Bearer {login['access_token']}"
        results = []
        for source in _one_source_per_intersection():
            results.append(await _validate_one(client, source))

        active = await _json(client, "GET", "/api/v1/missions", params={"status": "running"})
        report = {
            "schema_version": "uav.local-replay-no-lane-parameters-validation/v1",
            "generated_at": datetime.now(UTC).isoformat(),
            "results": results,
            "active_missions_after_validation": len(active),
            "passed": len(results) == 4 and all(row.get("passed") for row in results) and not active,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["passed"] else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="admin123")
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
