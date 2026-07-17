#!/usr/bin/env python3
"""Exercise all registered local replay Missions, MJPEG and canonical WebSocket paths."""

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


def _source_catalog() -> dict[str, dict]:
    result: dict[str, dict] = {}
    for intersection in LOCAL_REPLAY_CATALOG:
        for source in intersection["sources"]:
            result[source["profile_id"]] = {**intersection, **source}
    return result


async def _wait_messages(
    base_url: str, token: str, inter_id: str, drone_id: str, timeout_sec: float
) -> dict:
    channels = [f"uav_intersection:{inter_id}", f"uav_telemetry:{drone_id}"]
    found = {"uav_stats": False, "uav_telemetry": False}
    url = f"{_ws_url(base_url)}?access_token={quote(token)}"
    async with websockets.connect(url, max_size=8 * 1024 * 1024) as websocket:
        await websocket.send(json.dumps({"action": "subscribe", "channels": channels}))
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline and not all(found.values()):
            try:
                raw = await asyncio.wait_for(websocket.recv(), timeout=min(5, deadline - time.monotonic()))
            except asyncio.TimeoutError:
                continue
            payload = json.loads(raw)
            message_type = payload.get("type")
            if message_type in found:
                found[message_type] = True
    return found


async def _wait_mjpeg(
    client: httpx.AsyncClient, camera_id: int, mission_id: str, timeout_sec: float
) -> dict:
    deadline = time.monotonic() + timeout_sec
    last_error = "camera_not_ready"
    while time.monotonic() < deadline:
        try:
            timeout = httpx.Timeout(connect=3, read=15, write=5, pool=5)
            async with client.stream("GET", f"/api/v1/video/camera/{camera_id}", timeout=timeout) as response:
                if response.status_code != 200:
                    last_error = f"HTTP {response.status_code}"
                    mission = await client.get(f"/api/v1/missions/{mission_id}")
                    if mission.status_code == 200 and mission.json().get("status") in {"failed", "completed"}:
                        payload = mission.json()
                        return {
                            "ok": False,
                            "error": payload.get("error_message") or payload.get("reason_code"),
                        }
                    await asyncio.sleep(2)
                    continue
                payload = bytearray()
                async for chunk in response.aiter_bytes():
                    payload.extend(chunk)
                    start = payload.find(b"\xff\xd8")
                    end = payload.find(b"\xff\xd9", start + 2) if start >= 0 else -1
                    if start >= 0 and end > start:
                        return {
                            "ok": True,
                            "jpeg_bytes": end + 2 - start,
                            "content_type": response.headers.get("content-type", ""),
                        }
                    if len(payload) > 12 * 1024 * 1024:
                        payload = payload[-6 * 1024 * 1024 :]
        except (httpx.HTTPError, asyncio.TimeoutError) as exc:
            last_error = type(exc).__name__
        await asyncio.sleep(2)
    return {"ok": False, "error": last_error}


async def _stop(client: httpx.AsyncClient, mission_id: str) -> dict:
    current = await client.get(f"/api/v1/missions/{mission_id}")
    current.raise_for_status()
    payload = current.json()
    if payload.get("status") not in {"pending", "starting", "running"}:
        return payload
    response = await client.post(f"/api/v1/missions/{mission_id}/stop", json={"reason": "manual_stop"})
    response.raise_for_status()
    return response.json()


async def _validate_source(
    client: httpx.AsyncClient,
    base_url: str,
    token: str,
    source: dict,
    timeout_sec: float,
    check_duplicate: bool,
    expect_eof: bool,
    hold_seconds: float,
) -> dict:
    body = {
        "name": f"local replay runtime validation {source['profile_id']}",
        "drone_id": source["drone_id"],
        "source_profile_id": source["profile_id"],
        "inter_id": source["inter_id"],
        "road_data_version": source["road_data_version"],
        "scheduled_end_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
    }
    started = time.monotonic()
    response = await client.post("/api/v1/missions", json=body)
    response.raise_for_status()
    mission = response.json()
    mission_id = mission["id"]
    result = {
        "profile_id": source["profile_id"],
        "drone_id": source["drone_id"],
        "inter_id": source["inter_id"],
        "offset_sec": source["time_offset_sec"],
        "expected_telemetry": source.get("known_degradation") is None,
        "mission_id": mission_id,
        "running": mission.get("status") == "running",
        "pipeline_id": mission.get("pipeline_id"),
        "camera_id": (mission.get("pipeline") or {}).get("camera_id"),
    }
    should_stop = True
    try:
        if check_duplicate:
            duplicate = await client.post("/api/v1/missions", json=body)
            duplicate_payload = duplicate.json()
            result["duplicate_guard"] = {
                "status_code": duplicate.status_code,
                "code": (duplicate_payload.get("detail") or {}).get("code"),
            }
            result["duplicate_guard"]["passed"] = bool(
                duplicate.status_code == 409
                and result["duplicate_guard"]["code"] == "drone_mission_active"
            )

        camera_id = result["camera_id"]
        if not result["running"] or camera_id is None:
            result["passed"] = False
            result["error"] = mission.get("error_message") or "mission_not_running"
            return result

        websocket_task = asyncio.create_task(
            _wait_messages(base_url, token, source["inter_id"], source["drone_id"], timeout_sec)
        )
        result["mjpeg"] = await _wait_mjpeg(client, camera_id, mission_id, timeout_sec)
        result["websocket"] = await websocket_task
        telemetry_ok = result["websocket"]["uav_telemetry"] or not result["expected_telemetry"]
        result["passed"] = bool(
            result["mjpeg"]["ok"] and result["websocket"]["uav_stats"] and telemetry_ok
            and (not check_duplicate or result["duplicate_guard"]["passed"])
        )
        if expect_eof and result["passed"]:
            deadline = time.monotonic() + timeout_sec
            while time.monotonic() < deadline:
                current = await client.get(f"/api/v1/missions/{mission_id}")
                current.raise_for_status()
                payload = current.json()
                if payload.get("status") in {"completed", "failed", "cancelled"}:
                    result["eof_status"] = payload.get("status")
                    result["eof_reason"] = payload.get("reason_code")
                    should_stop = payload.get("status") not in {"completed", "failed", "cancelled"}
                    result["passed"] = bool(
                        payload.get("status") == "completed" and payload.get("reason_code") == "source_eof"
                    )
                    break
                await asyncio.sleep(2)
            else:
                result["passed"] = False
                result["eof_reason"] = "timeout"
        elif result["passed"] and hold_seconds > 0:
            result["hold_seconds"] = hold_seconds
            await asyncio.sleep(hold_seconds)
        return result
    finally:
        stopped = await _stop(client, mission_id) if should_stop else (
            await client.get(f"/api/v1/missions/{mission_id}")
        ).json()
        result["stop_status"] = stopped.get("status")
        result["stop_reason"] = stopped.get("reason_code")
        result["elapsed_sec"] = round(time.monotonic() - started, 3)


async def main_async(args: argparse.Namespace) -> int:
    catalog = _source_catalog()
    selected = args.source or list(catalog)
    unknown = [profile_id for profile_id in selected if profile_id not in catalog]
    if unknown:
        raise SystemExit(f"unknown source profile(s): {', '.join(unknown)}")

    async with httpx.AsyncClient(base_url=args.base_url, timeout=30) as client:
        login = await client.post(
            "/api/v1/auth/login", json={"username": args.username, "password": args.password}
        )
        login.raise_for_status()
        token = login.json()["access_token"]
        client.headers["Authorization"] = f"Bearer {token}"

        if args.stop_active:
            missions = await client.get("/api/v1/missions")
            missions.raise_for_status()
            stopped = []
            for mission in missions.json():
                source_profile_id = mission.get("source_profile_id") or (
                    mission.get("context_snapshot") or {}
                ).get("source_profile_id")
                if source_profile_id in catalog and mission.get("status") in {
                    "pending", "starting", "running"
                }:
                    stopped.append(await _stop(client, mission["id"]))
            print(json.dumps({"stopped": len(stopped), "passed": True}, ensure_ascii=False, indent=2))
            return 0

        sources_response = await client.get("/api/v1/sources")
        sources_response.raise_for_status()
        persisted = {row["profile_id"]: row for row in sources_response.json()}

        for profile_id in selected:
            if profile_id not in persisted:
                raise RuntimeError(f"source is not persisted: {profile_id}")

        async def validate_selected(index: int, profile_id: str) -> dict:
            return await _validate_source(
                client,
                args.base_url,
                token,
                catalog[profile_id],
                args.timeout,
                check_duplicate=index == 0,
                expect_eof=args.expect_eof,
                hold_seconds=args.hold_seconds,
            )

        if args.parallel:
            results = list(await asyncio.gather(*(
                validate_selected(index, profile_id)
                for index, profile_id in enumerate(selected)
            )))
        else:
            results = [
                await validate_selected(index, profile_id)
                for index, profile_id in enumerate(selected)
            ]

        active = await client.get("/api/v1/missions", params={"status": "running"})
        active.raise_for_status()
        report = {
            "schema_version": "uav.local-replay-runtime-validation/v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "base_url": args.base_url,
            "results": results,
            "active_missions_after_validation": len(active.json()),
            "passed": all(row.get("passed") for row in results) and not active.json(),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["passed"] else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="admin123")
    parser.add_argument("--source", action="append", help="source profile ID; repeat to select several")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--expect-eof", action="store_true", help="wait for completed/source_eof")
    parser.add_argument(
        "--parallel",
        action="store_true",
        help="start selected sources concurrently; select at most one source per drone",
    )
    parser.add_argument("--hold-seconds", type=float, default=0, help="keep a validated Mission running")
    parser.add_argument("--stop-active", action="store_true", help="stop active mp4new Missions and exit")
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
