#!/usr/bin/env python3
"""Prove persisted lane annotations are loaded by later local replay Pipelines."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import time
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
import websockets


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from bootstrap_mp4new_sources import LOCAL_REPLAY_CATALOG  # noqa: E402


def _ws_url(base_url: str) -> str:
    parsed = urlsplit(base_url)
    return urlunsplit(("wss" if parsed.scheme == "https" else "ws", parsed.netloc, "/ws/realtime", "", ""))


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
        json={"reason": "lane_reuse_validation_complete"},
    )


async def _wait_manual_stats(
    base_url: str,
    token: str,
    inter_id: str,
    camera_id: int,
    timeout_sec: float,
) -> dict:
    url = f"{_ws_url(base_url)}?access_token={quote(token)}"
    channel = f"uav_intersection:{inter_id}"
    deadline = time.monotonic() + timeout_sec
    observed_stats = 0
    last_lane_source = None
    last_lane_count = 0
    async with websockets.connect(url, max_size=8 * 1024 * 1024) as websocket:
        await websocket.send(json.dumps({"action": "subscribe", "channels": [channel]}))
        while time.monotonic() < deadline:
            try:
                raw = await asyncio.wait_for(websocket.recv(), timeout=min(5, deadline - time.monotonic()))
            except asyncio.TimeoutError:
                continue
            envelope = json.loads(raw)
            if envelope.get("type") != "uav_stats":
                continue
            payload = envelope.get("data") or {}
            nested = payload.get("data") if isinstance(payload.get("data"), dict) else payload
            event_camera = payload.get("camera_id", nested.get("camera_id"))
            accepted_camera_ids = {str(camera_id), f"id_{camera_id}"}
            if event_camera is not None and str(event_camera) not in accepted_camera_ids:
                continue
            observed_stats += 1
            last_lane_source = nested.get("lane_source")
            lanes = nested.get("lanes") or nested.get("lane_stats") or []
            last_lane_count = len(lanes)
            if last_lane_source == "manual":
                return {
                    "passed": True,
                    "observed_stats": observed_stats,
                    "lane_source": last_lane_source,
                    "lane_count": last_lane_count,
                }
    return {
        "passed": False,
        "observed_stats": observed_stats,
        "lane_source": last_lane_source,
        "lane_count": last_lane_count,
        "error": "manual_lane_stats_timeout",
    }


async def _validate_one(
    client: httpx.AsyncClient,
    base_url: str,
    token: str,
    source: dict,
    timeout_sec: float,
) -> dict:
    inter_id = source["inter_id"]
    annotation = await _json(client, "GET", f"/api/v1/calibration/lane-annotations/{inter_id}")
    expected_path = annotation.get("export_path")
    if not expected_path:
        raise RuntimeError(f"lane annotation export path is missing for {inter_id}")
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
            "scheduled_end_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        },
    )
    mission_id = mission["id"]
    result = {
        "inter_id": inter_id,
        "profile_id": source["profile_id"],
        "mission_id": mission_id,
        "pipeline_id": mission.get("pipeline_id"),
        "expected_roads_json": expected_path,
    }
    try:
        if mission.get("status") != "running" or not mission.get("pipeline_id"):
            result.update({"passed": False, "error": mission.get("error_message") or "mission_not_running"})
            return result
        pipeline = await _json(client, "GET", f"/api/v1/pipelines/{mission['pipeline_id']}")
        result["actual_roads_json"] = pipeline.get("roads_json")
        result["binding_reused"] = pipeline.get("roads_json") == expected_path
        result["camera_id"] = pipeline.get("camera_id")
        if not result["binding_reused"] or result["camera_id"] is None:
            result.update({"passed": False, "error": "pipeline_binding_mismatch"})
            return result
        result["stats"] = await _wait_manual_stats(
            base_url,
            token,
            inter_id,
            int(result["camera_id"]),
            timeout_sec,
        )
        result["passed"] = bool(result["binding_reused"] and result["stats"]["passed"])
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
        token = login["access_token"]
        client.headers["Authorization"] = f"Bearer {token}"
        results = []
        for source in _one_source_per_intersection():
            results.append(await _validate_one(client, args.base_url, token, source, args.timeout))

        active = await _json(client, "GET", "/api/v1/missions", params={"status": "running"})
        report = {
            "schema_version": "uav.local-replay-lane-reuse-validation/v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
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
    parser.add_argument("--timeout", type=float, default=120)
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
