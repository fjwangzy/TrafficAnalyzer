#!/usr/bin/env python3
"""Persist one real-keyframe lane annotation for each local replay intersection."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json

import httpx


async def _json(client: httpx.AsyncClient, method: str, url: str, **kwargs):
    response = await client.request(method, url, **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {url}: HTTP {response.status_code}: {response.text[:1000]}")
    return response.json() if response.content else {}


async def main_async(args: argparse.Namespace) -> int:
    async with httpx.AsyncClient(base_url=args.base_url, timeout=120) as client:
        login = await _json(client, "POST", "/api/v1/auth/login", json={"username": args.username, "password": args.password})
        client.headers["Authorization"] = f"Bearer {login['access_token']}"
        sources = await _json(client, "GET", "/api/v1/sources")
        selected: dict[str, dict] = {}
        for source in sources:
            if source.get("mode") != "local":
                continue
            results = await _json(client, "GET", f"/api/v1/sources/{source['profile_id']}/results")
            if results.get("inter_id") and results.get("survey_tasks"):
                selected.setdefault(results["inter_id"], results)
        rows = []
        for inter_id, result in selected.items():
            survey_task = result["survey_tasks"][0]
            frames = await _json(
                client,
                "GET",
                f"/api/v1/survey-tasks/{survey_task['id']}/frames",
                params={"batch_id": survey_task["batch_id"]},
            )
            frame = frames[0]
            lane_task = await _json(
                client,
                "POST",
                "/api/v1/calibration/lane-tasks/from-survey-frame",
                json={"frame_id": frame["id"]},
            )
            width, height = lane_task["image_width"], lane_task["image_height"]
            polygon = [
                width * 0.35, height * 0.15,
                width * 0.52, height * 0.15,
                width * 0.58, height * 0.88,
                width * 0.30, height * 0.88,
            ]
            annotation = await _json(
                client,
                "POST",
                f"/api/v1/calibration/lane-tasks/{lane_task['task_id']}/annotation",
                json={"lanes": [{"lane_id": "L1", "name": "验收车道 1", "direction": "through", "polygon": polygon}]},
            )
            image = await client.get(lane_task["image_url"])
            image.raise_for_status()
            rows.append(
                {
                    "inter_id": inter_id,
                    "task_id": lane_task["task_id"],
                    "source_frame_id": frame["id"],
                    "image_width": width,
                    "image_height": height,
                    "image_bytes": len(image.content),
                    "lane_count": len(annotation["lanes"]),
                    "binding_count": annotation["binding_count"],
                    "road_data_version": annotation["road_data_version"],
                    "passed": bool(image.content and annotation["binding_count"] == 1),
                }
            )
        refreshed = await _json(client, "GET", "/api/v1/calibration/lane-annotations")
        report = {
            "schema_version": "uav.local-replay-lane-acceptance/v1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "results": rows,
            "persisted_annotations": len(refreshed),
            "passed": len(rows) == 4 and all(row["passed"] for row in rows),
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
