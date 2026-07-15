#!/usr/bin/env python3
"""Seed truthful I3 UI evidence from the inter_xqh engineering baseline.

The 100-frame real pipeline baseline produces no conflict events.  This script
therefore persists a clearly labelled, unverified contract fixture for the
review UI while retaining the real SRT source timestamp/anchor in the payload.
It must never be presented as a detected production conflict.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PLATFORM = ROOT / "platform"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(PLATFORM))

from app.core.database import async_session_maker  # noqa: E402
from app.services.metric_store import MessageEnvelope, PostgresMetricStoreAdapter  # noqa: E402
from services.SrtTelemetryParser import SrtTelemetryParser  # noqa: E402


OCCURRED_AT = datetime(2026, 7, 15, 4, 30, tzinfo=UTC).isoformat()
SOURCE_SYSTEM = "uav_traffic_analyzer_ai"
INTER_ID = "INT_camera_1"


def canonical(msg_type: str, message_id: str, data: dict) -> dict:
    return {
        "message_id": message_id,
        "trace_id": "trace-i3-inter-xqh-ui-evidence",
        "msg_type": msg_type,
        "schema_version": f"{msg_type}/v1",
        "source_system": SOURCE_SYSTEM,
        "occurred_at": OCCURRED_AT,
        "produced_at": OCCURRED_AT,
        "camera_id": "1",
        "drone_id": "drone_inter_xqh",
        "intersection_id": INTER_ID,
        "inter_id": INTER_ID,
        "road_data_version": "ROAD-LOCAL-INTER-XQH",
        "road_context_status": "fixture",
        "source_time_semantics": "replay_validation",
        "time_quality": "ingest_only",
        "quality_status": "unverified",
        "data": data,
    }


async def main() -> None:
    parser = SrtTelemetryParser(str(ROOT / "test_videos/inter_xqh/telemetry.srt"))
    telemetry = parser.get_nearest(0.0) or {}
    source_recorded_at = telemetry.get("recorded_at")
    anchor = [telemetry.get("latitude"), telemetry.get("longitude")]
    store = PostgresMetricStoreAdapter(async_session_maker)
    messages = [
        (
            "uav_statistics_1",
            canonical("uav_stats", "i3-inter-xqh-stats-v1", {
                "cars": 82,
                "total_vehicles": 82,
                "active_tracks": 86,
                "expected_samples": 100,
                "actual_samples": 100,
                "coverage_ratio": 1.0,
                "validation_baseline": "56 PASS / 0 FAIL / 0 WARN",
                "source_recorded_at": source_recorded_at,
            }),
        ),
        (
            "uav_track_complete_1",
            canonical("uav_track_complete", "i3-inter-xqh-track-fixture-v1", {
                "track_id": "I3-QA-TRACK-01",
                "vehicle_class": "motor",
                "turn_behavior": "straight",
                "trajectory_px": [[1810, 1120], [1870, 1080], [1940, 1020]],
                "trajectory_world_m": [[-4.0, -2.0], [0.0, 0.0], [5.0, 3.0]],
                "world_anchor_lat_lon": anchor,
                "map_match_quality": "unverified",
                "validation_fixture": True,
                "source_recorded_at": source_recorded_at,
            }),
        ),
        (
            "uav_conflicts_1",
            canonical("uav_conflict", "i3-inter-xqh-conflict-fixture-v1", {
                "motor_id": "I3-QA-MOTOR",
                "non_motor_id": "I3-QA-NONMOTOR",
                "severity": "warning",
                "ttc_sec": 2.6,
                "pet_sec": 0.8,
                "distance_m": 1.4,
                "risk_score": 42,
                "prediction_type": "path_intersection",
                "conflict_scene": "I3 工程复核样本（非真实冲突）",
                "evidence": ["engineering_contract_fixture", "inter_xqh_56_pass"],
                "motor_position_m": [-1.0, 0.0],
                "non_motor_position_m": [0.0, 1.0],
                "world_anchor_lat_lon": anchor,
                "validation_fixture": True,
                "source_recorded_at": source_recorded_at,
            }),
        ),
        (
            "uav_telemetry_1",
            canonical("uav_telemetry", "i3-inter-xqh-telemetry-v1", {
                "drone_id": "drone_inter_xqh",
                "latitude": telemetry.get("latitude"),
                "longitude": telemetry.get("longitude"),
                "altitude_m": telemetry.get("height"),
                "gimbal_pitch_deg": telemetry.get("gimbal_pitch"),
                "gimbal_yaw_deg": telemetry.get("gimbal_yaw"),
                "positioning_quality": "srt_replay",
                "source_recorded_at": source_recorded_at,
            }),
        ),
    ]

    results = []
    for offset, (topic, payload) in enumerate(messages, start=9000):
        results.append(await store.persist(MessageEnvelope(payload, topic, 0, offset)))
    conflict_ref = next(ref for ref in results[2].fact_references if ref.startswith("uav_conflict_events:"))
    print(f"telemetry_records={parser.buffer_count}")
    print(f"source_recorded_at={source_recorded_at}")
    print(f"anchor={anchor}")
    print(f"conflict_ref={conflict_ref}")
    print("quality_status=unverified validation_fixture=true")


if __name__ == "__main__":
    asyncio.run(main())
