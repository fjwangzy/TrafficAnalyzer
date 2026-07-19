"""Run with RUN_PG_INTEGRATION=1 against a disposable/local road9 database."""

import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete

from app.core.database import async_session_maker
from app.models.enforcement import (
    EnforcementClue,
    EnforcementReviewAudit,
    EnforcementRule,
    EnforcementZone,
)
from app.models.survey import AiEvent, AuditLog, EvidenceItem, EvidencePackage, RuleVersion
from app.schemas.enforcement import (
    ClueIngest,
    ClueReview,
    EvidenceReference,
    RuleCreate,
    ZoneCreate,
    ZoneUpdate,
)
from app.services.enforcement_service import EnforcementError, EnforcementService

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_PG_INTEGRATION") != "1",
    reason="requires an explicitly selected local PostgreSQL/TimescaleDB database",
)


@pytest.mark.asyncio
async def test_candidate_config_clue_evidence_review_and_idempotency():
    marker = uuid.uuid4().hex[:10]
    service = EnforcementService(async_session_maker)
    source_event_id = f"s4-pg-{marker}"
    zone = rule = second_rule = clue = None
    try:
        zone = await service.create_zone(ZoneCreate(
            name=f"候选区域 {marker}", zone_type="truck_restriction",
            geometry={"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 0]]]},
            coordinate_system="ENU", road_data_version="ROAD-I4",
        ), None)
        assert zone["status"] == "candidate"
        with pytest.raises(EnforcementError) as revision:
            await service.update_zone(zone["id"], ZoneUpdate(revision=99, name="stale"), None)
        assert revision.value.status_code == 409

        rule = await service.create_rule(RuleCreate(
            name=f"候选货车事实规则 {marker}", zone_id=zone["id"],
            clue_type="truck_restriction", definition={"vehicle_class": "truck", "mode": "fact_only"},
        ), None)
        assert rule["approval_status"] == "blocked"
        second_rule = await service.create_rule(RuleCreate(
            name=f"第二条候选货车事实规则 {marker}", zone_id=zone["id"],
            clue_type="truck_restriction", definition={"vehicle_class": "truck", "mode": "fact_only"},
        ), None)
        assert second_rule["rule_version_id"] != rule["rule_version_id"]

        body = ClueIngest(
            source_event_id=source_event_id, idempotency_key=source_event_id,
            occurred_at=datetime.now(UTC), inter_id="INT-I4", road_data_version="ROAD-I4",
            track_id="track-7", vehicle_class="truck", class_confidence=0.91,
            classification_model_version="uav_best.pt", clue_type="truck_restriction",
            zone_id=zone["id"], zone_version="candidate-r1", rule_id=rule["id"],
            rule_version="candidate-r1", matched_facts={"entered_zone": True},
            video_speed_kmh=21.4, video_speed_method="homography_motion_compensated",
            video_speed_quality="unverified", quality_status="unverified", validation_fixture=True,
            evidence=[EvidenceReference(
                kind="original_video", storage_key=f"test/{marker}.mp4", sha256="a" * 64,
                media_type="video/mp4", size_bytes=128,
            )],
        )
        clue = await service.ingest_clue(body, None)
        duplicate = await service.ingest_clue(body, None)
        assert duplicate["id"] == clue["id"]
        assert clue["delivery_status"] == "blocked"
        assert clue["evidence_integrity_status"] == "hash_verified"

        changed = body.model_copy(update={"matched_facts": {"entered_zone": False}})
        with pytest.raises(EnforcementError) as identity:
            await service.ingest_clue(changed, None)
        assert identity.value.status_code == 409

        reviewed = await service.review_clue(clue["id"], ClueReview(
            review_status="reviewed_confirmed", expected_revision=1, reason="工程契约复核",
        ), None)
        assert reviewed["review_status"] == "reviewed_confirmed"
        assert reviewed["review_revision"] == 2
        with pytest.raises(EnforcementError) as stale:
            await service.review_clue(clue["id"], ClueReview(
                review_status="reviewed_rejected", expected_revision=1, reason="stale",
            ), None)
        assert stale.value.status_code == 409

        with pytest.raises(EnforcementError) as publish:
            await service.publish_candidate("zone", zone["id"])
        assert publish.value.status_code == 503
    finally:
        async with async_session_maker() as session:
            if clue:
                await session.execute(delete(EnforcementReviewAudit).where(EnforcementReviewAudit.event_id == clue["id"]))
                await session.execute(delete(EnforcementClue).where(EnforcementClue.event_id == clue["id"]))
                package_ids = [row[0] for row in (await session.execute(EvidencePackage.__table__.select().with_only_columns(EvidencePackage.id).where(EvidencePackage.source_event_id == source_event_id))).all()]
                if package_ids:
                    await session.execute(delete(EvidenceItem).where(EvidenceItem.package_id.in_(package_ids)))
                    await session.execute(delete(EvidencePackage).where(EvidencePackage.id.in_(package_ids)))
                await session.execute(delete(AiEvent).where(AiEvent.id == clue["id"]))
            for candidate_rule in (rule, second_rule):
                if candidate_rule:
                    await session.execute(delete(EnforcementRule).where(EnforcementRule.id == candidate_rule["id"]))
                    await session.execute(delete(RuleVersion).where(RuleVersion.id == candidate_rule["rule_version_id"]))
            if zone:
                await session.execute(delete(EnforcementZone).where(EnforcementZone.id == zone["id"]))
            await session.execute(delete(AuditLog).where(AuditLog.target_id.in_([value for value in [zone and zone["id"], rule and rule["id"], second_rule and second_rule["id"], clue and clue["id"]] if value])))
            await session.commit()
