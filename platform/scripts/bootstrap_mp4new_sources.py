#!/usr/bin/env python3
"""Idempotently register the mp4new replay cameras in road9."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select


PLATFORM_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = PLATFORM_DIR.parent
sys.path.insert(0, str(PLATFORM_DIR))

from app.core.database import async_session_maker, close_db, init_db  # noqa: E402
from app.models.mission import (  # noqa: E402
    DroneRecord,
    RoadContextSnapshot,
    TelemetrySourceRecord,
    VideoSourceRecord,
)
from app.services.mission_orchestrator import SourceValidator  # noqa: E402


MP4NEW_CATALOG = (
    {
        "inter_id": "INT_mp4new_haiyou",
        "road_data_version": "ROAD-MP4NEW-HY-UNVERIFIED-V1",
        "intersection_name": "解放东路-海右路",
        "drone_id": "UAV-MP4NEW-HY",
        "drone_name": "回放摄像头 · 解放东路-海右路",
        "sources": (
            {
                "profile_id": "SRC-MP4NEW-HY-0624-PM",
                "video": "test_videos/mp4new/6.24晚高峰 解放东路-海右路.mp4",
                "telemetry": "test_videos/mp4new/srt/解放东路-海右路0624晚高峰 srt文件.txt",
                "time_offset_sec": 233.463,
            },
            {
                "profile_id": "SRC-MP4NEW-HY-0625-AM",
                "video": "test_videos/mp4new/6.25早高峰 解放东路-海右路.mp4",
                "telemetry": "test_videos/mp4new/srt/解放东路-海右路0625早高峰 srt文件.txt",
                "time_offset_sec": 178.129,
                "default": True,
            },
        ),
    },
    {
        "inter_id": "INT_mp4new_lishi",
        "road_data_version": "ROAD-MP4NEW-LS-UNVERIFIED-V1",
        "intersection_name": "解放东路-礼士路",
        "drone_id": "UAV-MP4NEW-LS",
        "drone_name": "回放摄像头 · 解放东路-礼士路",
        "sources": (
            {
                "profile_id": "SRC-MP4NEW-LS-0624-PM",
                "video": "test_videos/mp4new/6.24晚高峰 解放东路-礼士路.mp4",
                "telemetry": "test_videos/mp4new/srt/解放东路-礼士路0624晚高峰srt文件.txt",
                "time_offset_sec": 179.115,
                "known_degradation": "telemetry_gap_34s",
            },
            {
                "profile_id": "SRC-MP4NEW-LS-0625-AM",
                "video": "test_videos/mp4new/6.25早高峰 解放东路-礼士路路口.mp4",
                "telemetry": "test_videos/mp4new/srt/解放东路礼士路路口0625早高峰srt文件.txt",
                "time_offset_sec": 132.032,
                "default": True,
            },
        ),
    },
    {
        "inter_id": "INT_mp4new_chonghua",
        "road_data_version": "ROAD-MP4NEW-CH-UNVERIFIED-V1",
        "intersection_name": "新泺大街-崇华路",
        "drone_id": "UAV-MP4NEW-CH",
        "drone_name": "回放摄像头 · 新泺大街-崇华路",
        "sources": (
            {
                "profile_id": "SRC-MP4NEW-CH-0625-AM",
                "video": "test_videos/mp4new/6.25早高峰 崇华路.mp4",
                "telemetry": "test_videos/mp4new/srt/新泺大街崇华路路口0625早高峰srt文件.txt",
                "time_offset_sec": 247.096,
                "default": True,
            },
        ),
    },
)


def _source_id(prefix: str, profile_id: str) -> str:
    return f"{prefix}-{profile_id.removeprefix('SRC-')}"


def _context_payload(item: dict) -> dict:
    return {
        "intersection": {
            "name": item["intersection_name"],
            "roads_json": "",
            "calibration_status": "not_started",
        },
        "links": [],
        "lanes": [],
        "acceptance_scope": "detection_tracking_telemetry_only",
    }


async def bootstrap(check_only: bool = False) -> dict:
    if not await init_db():
        raise RuntimeError("road9 initialization failed")
    validator = SourceValidator()
    changed = 0
    checked = 0
    async with async_session_maker() as session:
        for item in MP4NEW_CATALOG:
            payload = _context_payload(item)
            checksum = hashlib.sha256(
                json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()
            context = (
                await session.execute(
                    select(RoadContextSnapshot).where(
                        RoadContextSnapshot.inter_id == item["inter_id"],
                        RoadContextSnapshot.road_data_version == item["road_data_version"],
                    )
                )
            ).scalar_one_or_none()
            if context is None:
                if check_only:
                    raise RuntimeError(f"missing RoadContext {item['inter_id']}")
                context = RoadContextSnapshot(
                    id=f"CTX-{item['drone_id'].removeprefix('UAV-')}",
                    inter_id=item["inter_id"],
                    road_data_version=item["road_data_version"],
                    source="mp4new_local_fixture",
                    checksum=checksum,
                    coordinate_reference={"status": "unverified", "display": "unknown", "metric": "ENU"},
                    payload=payload,
                    quality_status="unverified",
                    effective_at=datetime.now(UTC),
                )
                session.add(context)
                changed += 1
            elif not check_only:
                context.source = "mp4new_local_fixture"
                context.checksum = checksum
                context.coordinate_reference = {"status": "unverified", "display": "unknown", "metric": "ENU"}
                context.payload = payload
                context.quality_status = "unverified"

            drone = await session.get(DroneRecord, item["drone_id"])
            if drone is None:
                if check_only:
                    raise RuntimeError(f"missing drone {item['drone_id']}")
                drone = DroneRecord(
                    id=item["drone_id"], name=item["drone_name"], model="MP4 replay fixture",
                    enabled=True, default_inter_id=item["inter_id"],
                )
                session.add(drone)
                changed += 1
            elif not check_only:
                drone.name = item["drone_name"]
                drone.model = "MP4 replay fixture"
                drone.enabled = True
                drone.default_inter_id = item["inter_id"]

            await session.flush()
            for source in item["sources"]:
                profile_id = source["profile_id"]
                video = (
                    await session.execute(
                        select(VideoSourceRecord).where(VideoSourceRecord.profile_id == profile_id)
                    )
                ).scalar_one_or_none()
                telemetry = (
                    await session.execute(
                        select(TelemetrySourceRecord).where(TelemetrySourceRecord.profile_id == profile_id)
                    )
                ).scalar_one_or_none()
                if check_only and (video is None or telemetry is None):
                    raise RuntimeError(f"missing source profile {profile_id}")
                if video is None:
                    video = VideoSourceRecord(
                        id=_source_id("VID", profile_id), profile_id=profile_id,
                        drone_id=item["drone_id"], mode="local", source_type="mp4",
                        location=source["video"], enabled=True,
                    )
                    session.add(video)
                    changed += 1
                if telemetry is None:
                    telemetry = TelemetrySourceRecord(
                        id=_source_id("TEL", profile_id), profile_id=profile_id,
                        drone_id=item["drone_id"], mode="local", source_type="file",
                        location=source["telemetry"], enabled=True, config={},
                    )
                    session.add(telemetry)
                    changed += 1
                if not check_only:
                    video.drone_id = telemetry.drone_id = item["drone_id"]
                    video.mode = telemetry.mode = "local"
                    video.source_type = "mp4"
                    video.location = source["video"]
                    telemetry.source_type = "file"
                    telemetry.location = source["telemetry"]
                    telemetry.config = {
                        "time_offset_sec": source["time_offset_sec"],
                        "sync_tolerance_sec": 2.5,
                        "known_degradation": source.get("known_degradation"),
                    }
                    video.enabled = telemetry.enabled = True
                    status, code = validator.validate(video, telemetry)
                    if status == "valid" and source.get("known_degradation"):
                        status = "degraded"
                        code = source["known_degradation"]
                    video.validation_status = telemetry.validation_status = status
                    video.validation_error_code = telemetry.validation_error_code = code
                    video.validated_at = telemetry.validated_at = datetime.now(UTC)
                    if source.get("default"):
                        drone.default_video_source_id = video.id
                        drone.default_telemetry_source_id = telemetry.id
                checked += 1
        if check_only:
            await session.rollback()
        else:
            await session.commit()
    await close_db()
    return {
        "schema_version": "uav.mp4new-bootstrap/v1",
        "mode": "check" if check_only else "upsert",
        "intersections": len(MP4NEW_CATALOG),
        "sources": checked,
        "changed": changed,
        "passed": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(bootstrap(args.check)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
