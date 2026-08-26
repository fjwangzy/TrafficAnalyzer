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

MP4728_CATALOG = (
    {
        "inter_id": "INT_MP4728_JINGSHI_CORRIDOR",
        "road_data_version": None,
        "intersection_name": "经十路巡航测试走廊",
        "drone_id": "UAV-MP4728-JS",
        "drone_name": "回放无人机 · 经十路巡航",
        "test_coordinate": {
            "lat": 36.6481757,
            "lon": 117.0340793,
            "source": "SRC-MP4728-JS-0728-7MS telemetry_median",
        },
        "sources": (
            {
                "profile_id": "SRC-MP4728-JS-0728-3MS",
                "video": "test_videos/mp4728/经十路交通状态拍摄3米每秒.mp4",
                "telemetry": "test_videos/mp4728/srt0728/经十路3米每秒.txt",
                "telemetry_enabled": True,
                "time_offset_sec": 72.778,
                "sync_tolerance_sec": 2.5,
                "expected_speed_mps": 3.0,
                "expected_capture_started_at": "2026-07-28T10:06:20+08:00",
                "acceptance_mode": "roadless_trajectory",
                "source_manifest": {
                    "video_sha256": "1d61ea4b594a82425df4db481a0d0fc07039e60b5abb74ebb7a702ccb1062409",
                    "video_size_bytes": 2784863729,
                    "video_duration_sec": 512.078233,
                    "video_frame_count": 15347,
                    "video_fps": 29.97003,
                    "video_codec": "hevc",
                    "video_resolution": [3840, 2160],
                    "telemetry_sha256": "9fbb083238d6488ca353ffe2bd1de432aa50c71ff6d487b86ed87d207f3bd1c7",
                    "telemetry_size_bytes": 1597351,
                    "telemetry_started_at": "2026-07-28T10:05:07.222+08:00",
                    "telemetry_ended_at": "2026-07-28T10:18:33.432+08:00",
                },
            },
            {
                "profile_id": "SRC-MP4728-JS-0728-5MS",
                "video": "test_videos/mp4728/经十路交通状态拍摄5米每秒.mp4",
                "telemetry": "test_videos/mp4728/srt0728/经十路5米每秒.txt",
                "telemetry_enabled": True,
                "time_offset_sec": 72.438,
                "sync_tolerance_sec": 2.5,
                "expected_speed_mps": 5.0,
                "expected_capture_started_at": "2026-07-28T09:50:19+08:00",
                "acceptance_mode": "roadless_trajectory",
                "source_manifest": {
                    "video_sha256": "87c6522d756517936f44e71004665a212288a632e9fcfcc7b14238db766411ec",
                    "video_size_bytes": 2022413670,
                    "video_duration_sec": 371.7714,
                    "video_frame_count": 11142,
                    "video_fps": 29.97003,
                    "video_codec": "hevc",
                    "video_resolution": [3840, 2160],
                    "telemetry_sha256": "ba81892e79e64eb8f697048df1e5792b34644fab43742a5492c33923087a3b00",
                    "telemetry_size_bytes": 1561049,
                    "telemetry_started_at": "2026-07-28T09:49:06.562+08:00",
                    "telemetry_ended_at": "2026-07-28T10:01:57.422+08:00",
                },
            },
            {
                "profile_id": "SRC-MP4728-JS-0728-7MS",
                "video": "test_videos/mp4728/经十路交通状态拍摄7米每秒.mp4",
                "telemetry": "test_videos/mp4728/srt0728/经十路7米每秒.txt",
                "telemetry_enabled": True,
                "time_offset_sec": 74.373,
                "sync_tolerance_sec": 2.5,
                "expected_speed_mps": 7.0,
                "expected_capture_started_at": "2026-07-28T09:37:09+08:00",
                "acceptance_mode": "roadless_trajectory",
                "source_manifest": {
                    "video_sha256": "ce0c3ec29a0109f26d01e3985fd223700650468d233dc4cfbd7f359778e678de",
                    "video_size_bytes": 1589755777,
                    "video_duration_sec": 292.225267,
                    "video_frame_count": 8758,
                    "video_fps": 29.97003,
                    "video_codec": "hevc",
                    "video_resolution": [3840, 2160],
                    "telemetry_sha256": "b440df508737954c4eaecb65ff54b82c60d2104fc69d187c060eb2f33ba6b1d2",
                    "telemetry_size_bytes": 1265494,
                    "telemetry_started_at": "2026-07-28T09:35:54.627+08:00",
                    "telemetry_ended_at": "2026-07-28T09:47:01.485+08:00",
                },
            },
            {
                "profile_id": "SRC-MP4729-JS-0729-3MS",
                "video": "test_videos/mp4729/729经十路交通状态拍摄3米每秒.mp4",
                "telemetry": "test_videos/mp4729/srt/经十路3米每秒.txt",
                "telemetry_enabled": True,
                "time_offset_sec": 73.779,
                "sync_tolerance_sec": 2.5,
                "expected_speed_mps": 3.0,
                "expected_capture_started_at": "2026-07-29T09:44:03+08:00",
                "acceptance_mode": "roadless_trajectory",
                "default": True,
                "source_manifest": {
                    "video_sha256": "19fda82a1804ef7e0d507b47741780f0e4212371173b1647207ef2f38e37ac32",
                    "video_size_bytes": 3148888137,
                    "video_duration_sec": 579.045133,
                    "video_frame_count": 17354,
                    "video_fps": 29.97003,
                    "video_codec": "hevc",
                    "video_resolution": [3840, 2160],
                    "telemetry_sha256": "d045717f5217fc59f93cfc05400b3d16958ebd1d60167e265b942105d52d257b",
                    "telemetry_size_bytes": 1716920,
                    "telemetry_started_at": "2026-07-29T09:42:49.221+08:00",
                    "telemetry_ended_at": "2026-07-29T09:57:32.037+08:00",
                },
            },
        ),
    },
)

# mp4820 is a separate east-Jingshi cruise lineage.  It deliberately has no
# lane map: world trajectories and TCC may be assessed, while Lane/Link facts
# remain unavailable.
MP4820_CATALOG = (
    {
        "inter_id": "INT_MP4820_JINGSHI_EAST_CORRIDOR",
        "road_data_version": None,
        "intersection_name": "经十路东段巡航走廊",
        "drone_id": "UAV-MP4820-JS",
        "drone_name": "回放无人机 · 经十路东段巡航",
        "test_coordinate": {
            "lat": 36.6589100,
            "lon": 117.1052664,
            "source": "SRC-MP4820-JS-0813-EW telemetry_median",
        },
        "sources": (
            {
                "profile_id": "SRC-MP4820-JS-0813-EW",
                "video": "test_videos/mp4820/8.13晚高峰东向西.mp4",
                "telemetry": "test_videos/mp4820/8.13晚高峰东向西.txt",
                "telemetry_enabled": True,
                "telemetry_agl_policy": "laser_target",
                "allow_roll_with_visual_validation": True,
                "max_roll_visual_validation_deg": 15.0,
                "time_offset_sec": 58.451,
                "sync_tolerance_sec": 2.5,
                "expected_speed_mps": 5.0,
                "expected_capture_started_at": "2026-08-13T16:51:38.326+08:00",
                "acceptance_mode": "geo_tcc_validation",
                "min_tcc_eligible_coverage": 0.90,
                "default": True,
                "source_manifest": {
                    "video_sha256": "f3fd1e970aedce0d0527c5c85afad74ced23e28b99451c383cb08ba679294ccc",
                    "video_size_bytes": 2390960806,
                    "video_duration_sec": 440.873767,
                    "video_frame_count": 13213,
                    "video_fps": 29.97003,
                    "video_codec": "hevc",
                    "video_resolution": [3840, 2160],
                    "telemetry_sha256": "db895b67b9d2c27ba31b932a07cc6c64038ffb7fa747f106077e6356df737a68",
                    "telemetry_size_bytes": 1544450,
                    "telemetry_started_at": "2026-08-13T16:50:39.875+08:00",
                    "telemetry_ended_at": "2026-08-13T17:03:16.311+08:00",
                },
            },
            {
                "profile_id": "SRC-MP4820-JS-0813-WE",
                "video": "test_videos/mp4820/8.13晚高峰西向东.mp4",
                "telemetry": "test_videos/mp4820/8.13晚高峰西向东.txt",
                "telemetry_enabled": True,
                "telemetry_agl_policy": "laser_target",
                "allow_roll_with_visual_validation": True,
                "max_roll_visual_validation_deg": 15.0,
                "time_offset_sec": 216.149,
                "sync_tolerance_sec": 2.5,
                "expected_speed_mps": 5.0,
                "expected_capture_started_at": "2026-08-13T17:14:34.326+08:00",
                "acceptance_mode": "geo_tcc_validation",
                "min_tcc_eligible_coverage": 0.90,
                "source_manifest": {
                    "video_sha256": "03a85933c5ef8494463b0faaf54088898652e2b46c0860b2d7d3dba40d993474",
                    "video_size_bytes": 2225960569,
                    "video_duration_sec": 409.3089,
                    "video_frame_count": 12267,
                    "video_fps": 29.97003,
                    "video_codec": "hevc",
                    "video_resolution": [3840, 2160],
                    "telemetry_sha256": "028ea072c82e7e8c85ff4bbfcce1e53b77913a8191ead7ffb4a2c7ef03aa5877",
                    "telemetry_size_bytes": 1453284,
                    "telemetry_started_at": "2026-08-13T17:10:57.177+08:00",
                    "telemetry_ended_at": "2026-08-13T17:22:54.306+08:00",
                },
            },
        ),
    },
)

# Keep the established map-dependent catalog stable for survey/map scripts.
LOCAL_REPLAY_CATALOG = INTER_XQH_CATALOG + MP4NEW_CATALOG
ALL_LOCAL_REPLAY_CATALOG = LOCAL_REPLAY_CATALOG + MP4728_CATALOG + MP4820_CATALOG


def _source_id(prefix: str, profile_id: str) -> str:
    return f"{prefix}-{profile_id.removeprefix('SRC-')}"



async def bootstrap(check_only: bool = False) -> dict:
    if not await init_db():
        raise RuntimeError("road9 initialization failed")
    validator = SourceValidator()
    changed = 0
    checked = 0
    async with async_session_maker() as session:
        for item in ALL_LOCAL_REPLAY_CATALOG:
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
                        "camera_lens_policy": source.get(
                            "camera_lens_policy", "standard_wide_1x"
                        ),
                        "telemetry_enabled": source.get("telemetry_enabled", True),
                        "known_degradation": source.get("known_degradation"),
                        "acceptance_mode": source.get("acceptance_mode", "formal_world_trajectory"),
                        "expected_speed_mps": source.get("expected_speed_mps"),
                        "expected_capture_started_at": source.get("expected_capture_started_at"),
                        "source_manifest": source.get("source_manifest"),
                    }
                    video.enabled = True
                    telemetry.enabled = source.get("telemetry_enabled", True)
                    status, code = validator.validate(video, telemetry)
                    if source.get("known_degradation"):
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
                for item in ALL_LOCAL_REPLAY_CATALOG
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
        "intersections": len(ALL_LOCAL_REPLAY_CATALOG),
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
