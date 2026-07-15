#!/usr/bin/env python3
"""Persist an honest I4 contract fixture backed by real inter_xqh file hashes.

This does not claim that the detector found a violation. No approved S4 rule,
authoritative fence, radar measurement, or legal evidence contract exists.
"""

from __future__ import annotations

import asyncio
import hashlib
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PLATFORM = ROOT / "platform"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(PLATFORM))

from app.core.database import async_session_maker  # noqa: E402
from app.schemas.enforcement import ClueIngest, EvidenceReference, RuleCreate, ZoneCreate  # noqa: E402
from app.services.enforcement_service import EnforcementService  # noqa: E402
from services.SrtTelemetryParser import SrtTelemetryParser  # noqa: E402


VIDEO = ROOT / "test_videos/inter_xqh/DJI_20260403142902_0001_V小清河北路与水屯路路口.mp4"
SRT = ROOT / "test_videos/inter_xqh/telemetry.srt"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


async def main() -> None:
    service = EnforcementService(async_session_maker)
    zones = await service.list_zones()
    zone = next((item for item in zones if item["name"] == "inter_xqh 工程候选区域"), None)
    if zone is None:
        zone = await service.create_zone(ZoneCreate(
            name="inter_xqh 工程候选区域",
            zone_type="truck_restriction",
            geometry={"type": "Polygon", "coordinates": [[[-20, -20], [20, -20], [20, 20], [-20, -20]]]},
            coordinate_system="ENU",
            road_data_version="ROAD-LOCAL-INTER-XQH",
            schedule={"status": "candidate_only", "thresholds": "not_approved"},
        ), None)

    rules = await service.list_rules()
    rule = next((item for item in rules if item["name"] == "inter_xqh 工程事实规则"), None)
    if rule is None:
        rule = await service.create_rule(RuleCreate(
            name="inter_xqh 工程事实规则", zone_id=zone["id"], clue_type="truck_restriction",
            definition={"mode": "fact_only", "rule_execution_status": "blocked", "thresholds": "not_approved"},
        ), None)

    parser = SrtTelemetryParser(str(SRT))
    telemetry = parser.get_nearest(0.0) or {}
    recorded_at = telemetry.get("recorded_at")
    if not recorded_at:
        raise RuntimeError("inter_xqh SRT did not expose a recorded_at timestamp")
    recorded_at = datetime.fromisoformat(recorded_at) if isinstance(recorded_at, str) else recorded_at

    video_hash = sha256(VIDEO)
    srt_hash = sha256(SRT)
    clue = await service.ingest_clue(ClueIngest(
        source_event_id="i4-inter-xqh-contract-fixture-v1",
        idempotency_key="i4-inter-xqh-contract-fixture-v1",
        occurred_at=recorded_at,
        inter_id="INT_camera_1",
        road_data_version="ROAD-LOCAL-INTER-XQH",
        track_id="validation-fixture-no-detected-track",
        vehicle_class="unknown",
        clue_type="truck_restriction",
        zone_id=zone["id"], zone_version=f"candidate-r{zone['revision']}",
        rule_id=rule["id"], rule_version=f"candidate-r{rule['revision']}",
        matched_facts={
            "validation_fixture": True,
            "real_pipeline_baseline": "56 PASS / 0 FAIL / 0 WARN",
            "detected_enforcement_clue": False,
            "rule_execution_status": "blocked",
            "source_recorded_at": recorded_at.isoformat(),
        },
        exclusion_result={"reason": "authoritative fence and approved rule are unavailable"},
        quality_status="unverified",
        validation_fixture=True,
        evidence=[
            EvidenceReference(
                kind="original_video", storage_key=str(VIDEO.relative_to(ROOT)),
                sha256=video_hash, media_type="video/mp4", size_bytes=VIDEO.stat().st_size,
                metadata={"role": "real_source_material", "not_legal_evidence": True},
            ),
            EvidenceReference(
                kind="telemetry", storage_key=str(SRT.relative_to(ROOT)),
                sha256=srt_hash, media_type="application/x-subrip", size_bytes=SRT.stat().st_size,
                metadata={"records": parser.buffer_count, "source": "DJI SRT"},
            ),
        ],
    ), None)

    print(f"zone_id={zone['id']} status={zone['status']} authority={zone['authority_status']}")
    print(f"rule_id={rule['id']} approval={rule['approval_status']}")
    print(f"clue_id={clue['id']} review={clue['review_status']} delivery={clue['delivery_status']}")
    print(f"video_size={VIDEO.stat().st_size} video_sha256={video_hash}")
    print(f"srt_records={parser.buffer_count} srt_sha256={srt_hash}")
    print("quality_status=unverified validation_fixture=true detected_enforcement_clue=false")


if __name__ == "__main__":
    asyncio.run(main())
