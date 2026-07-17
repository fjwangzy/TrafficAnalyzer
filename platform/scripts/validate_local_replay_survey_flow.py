#!/usr/bin/env python3
"""Create or resume the six persistent local-replay survey acceptance flows."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

import httpx


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from bootstrap_mp4new_sources import LOCAL_REPLAY_CATALOG  # noqa: E402


PRECHECK = {
    "task_context": True,
    "operator_authorized": True,
    "site_command_confirmed": True,
    "device_ready": True,
    "storage_ready": True,
}
GEOMETRIES = (
    ("point", "车辆", [[140, 120]]),
    ("line", "痕迹", [[120, 120], [240, 180]]),
    ("area", "散落物", [[120, 120], [220, 120], [210, 210], [130, 205]]),
    ("object", "其他对象", [[260, 140], [350, 150], [340, 245], [255, 235]]),
)


def _catalog() -> list[dict]:
    return [{**intersection, **source} for intersection in LOCAL_REPLAY_CATALOG for source in intersection["sources"]]


async def _request(client: httpx.AsyncClient, method: str, url: str, **kwargs) -> dict | list:
    response = await client.request(method, url, **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {url}: HTTP {response.status_code}: {response.text[:1000]}")
    if response.status_code == 204:
        return {}
    return response.json()


async def _task(client: httpx.AsyncClient, task_id: str) -> dict:
    return await _request(client, "GET", f"/api/v1/survey-tasks/{task_id}")


async def _action(client: httpx.AsyncClient, task: dict, action: str, **values) -> dict:
    return await _request(
        client,
        "POST",
        f"/api/v1/survey-tasks/{task['id']}/actions",
        json={"action": action, "expected_revision": task["revision"], **values},
        headers={"Idempotency-Key": f"local-replay-{task['id']}-{action}-{task['revision']}"},
    )


async def _wait_batch(client: httpx.AsyncClient, task_id: str, profile_id: str, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    latest: dict = {}
    while time.monotonic() < deadline:
        rows = await _request(client, "GET", f"/api/v1/survey-tasks/{task_id}/capture-batches")
        matches = [row for row in rows if row.get("source_profile_id") == profile_id]
        if matches:
            latest = matches[0]
            if latest["status"] in {"ready", "degraded", "selected"}:
                return latest
            if latest["status"] == "error":
                raise RuntimeError(f"capture batch failed: {latest.get('error_message')}")
        await asyncio.sleep(2)
    raise RuntimeError(f"capture batch timeout for {profile_id}: {latest}")


async def _verify_content(client: httpx.AsyncClient, url: str) -> dict:
    response = await client.get(url)
    response.raise_for_status()
    digest = hashlib.sha256(response.content).hexdigest()
    expected_digest = response.headers.get("x-content-sha256")
    return {
        "url": url,
        "bytes": len(response.content),
        "content_type": response.headers.get("content-type", ""),
        "storage_backend": response.headers.get("x-storage-backend"),
        "sha256": digest,
        "expected_sha256": expected_digest,
        "ok": len(response.content) > 0 and bool(expected_digest) and digest == expected_digest,
    }


async def _probe_server_asset(
    client: httpx.AsyncClient,
    evidence_id: str,
    expected_sha256: str,
) -> dict:
    """Resolve a large server asset without transferring the complete video."""
    url = f"/api/v1/survey-evidence/{evidence_id}/content"
    first_chunk = b""
    async with client.stream("GET", url, headers={"Range": "bytes=0-1023"}) as response:
        response.raise_for_status()
        async for chunk in response.aiter_bytes():
            first_chunk = chunk
            break
        return {
            "url": url,
            "status_code": response.status_code,
            "bytes_read": len(first_chunk),
            "storage_backend": response.headers.get("x-storage-backend"),
            "expected_sha256": expected_sha256,
            "header_sha256": response.headers.get("x-content-sha256"),
            "ok": bool(first_chunk)
            and response.status_code in {200, 206}
            and response.headers.get("x-storage-backend") == "server_asset"
            and response.headers.get("x-content-sha256") == expected_sha256,
        }


async def _run_source(client: httpx.AsyncClient, source: dict, timeout: float) -> dict:
    profile_id = source["profile_id"]
    idempotency = f"local-replay-survey-create-{profile_id}"
    created = await _request(
        client,
        "POST",
        "/api/v1/survey-tasks",
        json={
            "title": f"本地无人机测绘验收 · {profile_id}",
            "scene_location": source["intersection_name"],
            "source": "local_replay",
            "external_task_id": f"ACCEPT-{profile_id}",
            "inter_id": source["inter_id"],
            "road_data_version": source["road_data_version"],
            "owner_name": "本机全流程验收",
        },
        headers={"Idempotency-Key": idempotency},
    )
    task = await _task(client, created["id"])
    if task["status"] == "created":
        task = await _action(client, task, "start_precheck")
    if task["status"] == "prechecking":
        task = await _action(client, task, "complete_precheck", checklist=PRECHECK)

    batches = await _request(client, "GET", f"/api/v1/survey-tasks/{task['id']}/capture-batches")
    matching = [row for row in batches if row.get("source_profile_id") == profile_id]
    if task["status"] == "ready" and not matching:
        await _request(
            client,
            "POST",
            f"/api/v1/survey-tasks/{task['id']}/capture-batches/import",
            json={"source_profile_id": profile_id},
            headers={"Idempotency-Key": f"local-replay-survey-import-{profile_id}"},
        )
    batch = await _wait_batch(client, task["id"], profile_id, timeout)
    task = await _task(client, task["id"])
    if task["status"] in {"ready", "collecting", "returned"}:
        task = await _action(client, task, "select_batch", batch_id=batch["id"])

    frames = await _request(
        client, "GET", f"/api/v1/survey-tasks/{task['id']}/frames", params={"batch_id": batch["id"]}
    )
    metric_frames = [frame for frame in frames if frame.get("has_metric_transform")]
    if len(frames) != 6 or not metric_frames:
        raise RuntimeError(f"{profile_id} expected 6 frames with a metric transform, got {len(frames)}/{len(metric_frames)}")
    frame = metric_frames[0]

    measurements = await _request(client, "GET", f"/api/v1/survey-tasks/{task['id']}/measurements")
    existing_types = {item["geometry_type"] for item in measurements}
    if task["status"] in {"measuring", "returned"}:
        for geometry_type, category, coordinates in GEOMETRIES:
            if geometry_type in existing_types:
                continue
            await _request(
                client,
                "POST",
                f"/api/v1/survey-tasks/{task['id']}/measurements",
                json={
                    "frame_id": frame["id"],
                    "geometry_type": geometry_type,
                    "category": category,
                    "image_geometry": coordinates,
                },
                headers={"Idempotency-Key": f"local-replay-measure-{profile_id}-{geometry_type}"},
            )
        annotations = await _request(client, "GET", f"/api/v1/survey-tasks/{task['id']}/annotations")
        if not annotations:
            annotation = await _request(
                client,
                "POST",
                f"/api/v1/survey-tasks/{task['id']}/annotations",
                json={
                    "frame_id": frame["id"],
                    "category": "车辆",
                    "image_geometry": [[300, 200], [380, 200], [380, 280], [300, 280]],
                    "source": "manual",
                },
                headers={"Idempotency-Key": f"local-replay-annotation-{profile_id}"},
            )
            await _request(
                client,
                "PATCH",
                f"/api/v1/survey-tasks/{task['id']}/annotations/{annotation['id']}",
                json={
                    "expected_revision": annotation["revision"],
                    "category": annotation["category"],
                    "image_geometry": annotation["image_geometry"],
                    "review_state": "confirmed",
                },
            )
        task = await _task(client, task["id"])
        task = await _action(client, task, "submit_review")
    if task["status"] == "pending_review":
        task = await _action(client, task, "approve_review")

    reports = await _request(client, "GET", f"/api/v1/survey-tasks/{task['id']}/reports")
    if not reports:
        report = await _request(
            client,
            "POST",
            f"/api/v1/survey-tasks/{task['id']}/reports",
            headers={"Idempotency-Key": f"local-replay-report-{profile_id}"},
        )
    else:
        report = reports[-1]
    measurements = await _request(client, "GET", f"/api/v1/survey-tasks/{task['id']}/measurements")
    annotations = await _request(client, "GET", f"/api/v1/survey-tasks/{task['id']}/annotations")
    content = []
    for persisted_frame in frames:
        content.append(await _verify_content(client, persisted_frame["image_url"]))
        content.append(await _verify_content(client, persisted_frame["bev_url"]))
    for report_url in (report["pdf_url"], report["json_url"], report["geojson_url"]):
        content.append(await _verify_content(client, report_url))
    raw = batch["original_materials"]
    telemetry_content = await _verify_content(
        client,
        f"/api/v1/survey-evidence/{raw['telemetry']['evidence_id']}/content",
    )
    video_probe = await _probe_server_asset(
        client,
        raw["video"]["evidence_id"],
        raw["video"]["sha256"],
    )
    content.append(telemetry_content)
    passed = bool(
        len(frames) == 6
        and {item["geometry_type"] for item in measurements} >= {item[0] for item in GEOMETRIES}
        and annotations
        and all(item["reference_status"] == "verified" and item["storage_backend"] == "server_asset" for item in raw.values())
        and all(item["ok"] for item in content)
        and video_probe["ok"]
    )
    return {
        "profile_id": profile_id,
        "task_id": task["id"],
        "task_status": (await _task(client, task["id"]))["status"],
        "batch_id": batch["id"],
        "batch_status": batch["status"],
        "telemetry_type": batch["telemetry_type"],
        "sync_config": batch["sync_config"],
        "telemetry_coverage": batch["telemetry_coverage"],
        "frames": len(frames),
        "bev_frames": len([item for item in frames if item.get("bev_url")]),
        "measurements": len(measurements),
        "annotations": len(annotations),
        "report_id": report["id"],
        "content_checks": {
            "checked": len(content),
            "hash_verified": sum(item["ok"] for item in content),
            "bytes": sum(item["bytes"] for item in content),
            "sample": content[:3],
        },
        "original_materials": raw,
        "raw_content_checks": {
            "telemetry": telemetry_content,
            "video_range_probe": video_probe,
        },
        "passed": passed,
    }


async def main_async(args: argparse.Namespace) -> int:
    async with httpx.AsyncClient(base_url=args.base_url, timeout=httpx.Timeout(args.timeout)) as client:
        login = await _request(
            client,
            "POST",
            "/api/v1/auth/login",
            json={"username": args.username, "password": args.password},
        )
        client.headers["Authorization"] = f"Bearer {login['access_token']}"
        results = []
        for source in _catalog():
            if args.source and source["profile_id"] not in args.source:
                continue
            results.append(await _run_source(client, source, args.timeout))
        report = {
            "schema_version": "uav.local-replay-survey-acceptance/v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "results": results,
            "totals": {
                "sources": len(results),
                "frames": sum(item["frames"] for item in results),
                "bev_frames": sum(item["bev_frames"] for item in results),
                "measurements": sum(item["measurements"] for item in results),
                "annotations": sum(item["annotations"] for item in results),
            },
            "passed": len(results) == (len(args.source) if args.source else 6) and all(item["passed"] for item in results),
        }
        rendered = json.dumps(report, ensure_ascii=False, indent=2)
        print(rendered)
        if args.output:
            Path(args.output).write_text(rendered + "\n", encoding="utf-8")
        return 0 if report["passed"] else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="admin123")
    parser.add_argument("--source", action="append")
    parser.add_argument("--timeout", type=float, default=1200)
    parser.add_argument("--output")
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
