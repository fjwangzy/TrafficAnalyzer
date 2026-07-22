#!/usr/bin/env python3
"""Idempotently register the mp4new replay cameras in road9."""

from __future__ import annotations

import argparse
import asyncio
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
    TelemetrySourceRecord,
    VideoSourceRecord,
)
from app.models.survey import EvidenceItem, SurveyCaptureBatch  # noqa: E402
from app.services.mission_orchestrator import SourceValidator  # noqa: E402

MP4NEW_CATALOG = (
    {
        "inter_id": "011wwe28dm500001",
        "road_data_version": "20260501-IMAGERY-FIT-V1",
        "intersection_name": "解放东路-海右路",
        "drone_id": "UAV-MP4NEW-HY",
        "drone_name": "回放摄像头 · 解放东路-海右路",
        "test_coordinate": {
            "lat": 36.6628016,
            "lon": 117.0930902,
            "source": "SRC-MP4NEW-HY-0625-AM telemetry_median",
        },
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
            {
                "profile_id": "SRC-MP4NEW2-HY-0715-PM",
                "video": "test_videos/mp4new2/解放东路-海右路路口晚高峰.mp4",
                "telemetry": "test_videos/mp4new2/srt/解放东路-海右路  解放东路-礼士路srt.txt",
                "time_offset_sec": 169.004,
            },
        ),
    },
    {
        "inter_id": "011wwe28dr400003",
        "road_data_version": "20260501-IMAGERY-FIT-V1",
        "intersection_name": "解放东路-礼士路",
        "drone_id": "UAV-MP4NEW-LS",
        "drone_name": "回放摄像头 · 解放东路-礼士路",
        "test_coordinate": {
            "lat": 36.6627830,
            "lon": 117.0953953,
            "source": "SRC-MP4NEW-LS-0625-AM telemetry_median",
        },
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
            {
                "profile_id": "SRC-MP4NEW2-LS-0715-PM",
                "video": "test_videos/mp4new2/解放东路-礼士路路口晚高峰.mp4",
                "telemetry": "test_videos/mp4new2/srt/解放东路-海右路  解放东路-礼士路srt.txt",
                "time_offset_sec": 691.247,
            },
        ),
    },
    {
        "inter_id": "011wwe29k1q00001",
        "road_data_version": "20260501-IMAGERY-FIT-V1",
        "intersection_name": "新泺大街-崇华路",
        "drone_id": "UAV-MP4NEW-CH",
        "drone_name": "回放摄像头 · 新泺大街-崇华路",
        "test_coordinate": {
            "lat": 36.6729919,
            "lon": 117.1210255,
            "source": "SRC-MP4NEW-CH-0625-AM telemetry_median",
        },
        "sources": (
            {
                "profile_id": "SRC-MP4NEW-CH-0625-AM",
                "video": "test_videos/mp4new/6.25早高峰 崇华路.mp4",
                "telemetry": "test_videos/mp4new/srt/新泺大街崇华路路口0625早高峰srt文件.txt",
                "time_offset_sec": 247.096,
                "default": True,
            },
            {
                "profile_id": "SRC-MP4NEW2-CH-0715-PM",
                "video": "test_videos/mp4new2/解放东路-崇华路路口晚高峰.mp4",
                "telemetry": "test_videos/mp4new2/srt/新泺大街-崇华路路口srt数据.txt",
                "time_offset_sec": 334.868,
            },
        ),
    },
)

INTER_XQH_CATALOG = (
    {
        "inter_id": "011wwe0z19700001",
        "road_data_version": "20260501-IMAGERY-FIT-V1",
        "intersection_name": "小清河北路与水屯路路口",
        "drone_id": "UAV-INTER-XQH",
        "drone_name": "回放无人机 · 小清河北路与水屯路",
        "test_coordinate": {
            "lat": 36.7029090,
            "lon": 117.0223260,
            "source": "SRC-INTER-XQH-0403-PM telemetry_median",
        },
        "sources": (
            {
                "profile_id": "SRC-INTER-XQH-0403-PM",
                "video": "test_videos/inter_xqh/DJI_20260403142902_0001_V小清河北路与水屯路路口.mp4",
                "telemetry": "test_videos/inter_xqh/telemetry.srt",
                "telemetry_type": "srt",
                "time_offset_sec": 0.0,
                "sync_tolerance_sec": 0.033,
                "default": True,
            },
        ),
    },
)

LOCAL_REPLAY_CATALOG = INTER_XQH_CATALOG + MP4NEW_CATALOG


def _source_id(prefix: str, profile_id: str) -> str:
    return f"{prefix}-{profile_id.removeprefix('SRC-')}"



async def bootstrap(check_only: bool = False) -> dict:
    if not await init_db():
        raise RuntimeError("road9 initialization failed")
    validator = SourceValidator()
    changed = 0
    checked = 0
    async with async_session_maker() as session:
        for item in LOCAL_REPLAY_CATALOG:
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
                        drone_id=item["drone_id"], mode="local", source_type=source.get("telemetry_type", "file"),
                        location=source["telemetry"], enabled=True, config={},
                    )
                    session.add(telemetry)
                    changed += 1
                if not check_only:
                    video.drone_id = telemetry.drone_id = item["drone_id"]
                    video.mode = telemetry.mode = "local"
                    video.source_type = "mp4"
                    video.location = source["video"]
                    telemetry.source_type = source.get("telemetry_type", "file")
                    telemetry.location = source["telemetry"]
                    telemetry.config = {
                        "format": "dji_srt" if source.get("telemetry_type") == "srt" else "dji_cloud_json",
                        "time_offset_sec": source["time_offset_sec"],
                        "sync_tolerance_sec": source.get("sync_tolerance_sec", 2.5),
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
        if not check_only:
            formats = {
                source["profile_id"]: ("dji_srt" if source.get("telemetry_type") == "srt" else "dji_cloud_json")
                for item in LOCAL_REPLAY_CATALOG
                for source in item["sources"]
            }
            evidence_rows = (
                await session.execute(select(EvidenceItem).where(EvidenceItem.kind == "original_telemetry"))
            ).scalars().all()
            for evidence in evidence_rows:
                metadata = dict(evidence.item_metadata or {})
                profile_id = metadata.get("source_profile_id")
                if profile_id in formats and metadata.get("telemetry_type") != formats[profile_id]:
                    metadata["telemetry_type"] = formats[profile_id]
                    evidence.item_metadata = metadata
            batch_rows = (
                await session.execute(select(SurveyCaptureBatch).where(SurveyCaptureBatch.source_profile_id.in_(formats)))
            ).scalars().all()
            for batch in batch_rows:
                batch.source_type = f"mp4_{formats[batch.source_profile_id]}"
        if check_only:
            await session.rollback()
        else:
            await session.commit()
    await close_db()
    return {
        "schema_version": "uav.mp4new-bootstrap/v1",
        "mode": "check" if check_only else "upsert",
        "intersections": len(LOCAL_REPLAY_CATALOG),
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
