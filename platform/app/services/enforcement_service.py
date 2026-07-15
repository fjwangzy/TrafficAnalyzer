"""Deep S4 application module for candidate configuration and AI clue review."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select

from app.models.enforcement import EnforcementClue, EnforcementReviewAudit, EnforcementRule, EnforcementZone
from app.models.survey import AiEvent, AuditLog, EvidenceItem, EvidencePackage, RuleVersion
from app.schemas.enforcement import ClueIngest, ClueReview, RuleCreate, RuleUpdate, ZoneCreate, ZoneUpdate


SOURCE_SYSTEM = "uav_traffic_analyzer_ai"


class EnforcementError(RuntimeError):
    def __init__(self, status_code: int, code: str, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12].upper()}"


def _canonical(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: dict) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _time(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value else None


class EnforcementService:
    """Own S4 invariants while adapters and REST stay deliberately thin."""

    def __init__(self, session_factory):
        self._session_factory = session_factory

    @staticmethod
    def _zone(row: EnforcementZone, rule_count: int = 0) -> dict:
        return {
            "id": row.id, "name": row.name, "zone_type": row.zone_type,
            "geometry": row.geometry, "coordinate_system": row.coordinate_system,
            "road_data_version": row.road_data_version, "source": row.source,
            "status": row.status, "schedule": row.schedule, "checksum": row.checksum,
            "revision": row.revision, "rule_count": rule_count,
            "created_at": _time(row.created_at), "updated_at": _time(row.updated_at),
            "authority_status": "unavailable",
        }

    @staticmethod
    def _rule(row: EnforcementRule) -> dict:
        return {
            "id": row.id, "rule_version_id": row.rule_version_id, "zone_id": row.zone_id,
            "name": row.name, "clue_type": row.clue_type, "definition": row.definition,
            "source": row.source, "status": row.status, "quality_status": row.quality_status,
            "revision": row.revision, "created_at": _time(row.created_at), "updated_at": _time(row.updated_at),
            "approval_status": "blocked",
        }

    @staticmethod
    def _clue(event: AiEvent, clue: EnforcementClue, evidence_count: int = 0) -> dict:
        return {
            "id": event.id, "source_event_id": event.source_event_id,
            "idempotency_key": event.idempotency_key, "event_type": event.event_type,
            "event_revision": clue.event_revision, "occurred_at": _time(event.occurred_at),
            "inter_id": event.inter_id, "road_data_version": event.road_data_version,
            "quality_status": event.quality_status, "delivery_status": event.delivery_status,
            "review_status": event.review_status, "review_revision": event.review_revision,
            "review_reason": event.review_reason, "reviewed_at": _time(event.reviewed_at),
            "track_id": clue.track_id, "vehicle_class": clue.vehicle_class,
            "class_confidence": clue.class_confidence,
            "classification_model_version": clue.classification_model_version,
            "clue_type": clue.clue_type, "zone_id": clue.zone_id, "zone_version": clue.zone_version,
            "rule_id": clue.rule_id, "rule_version": clue.rule_version,
            "matched_facts": clue.matched_facts, "exclusion_result": clue.exclusion_result,
            "video_speed_kmh": clue.video_speed_kmh, "video_speed_method": clue.video_speed_method,
            "video_speed_quality": clue.video_speed_quality,
            "video_speed_uncertainty": clue.video_speed_uncertainty,
            "radar_speed_kmh": clue.radar_speed_kmh, "radar_device_id": clue.radar_device_id,
            "radar_metadata": clue.radar_metadata, "fused_speed_kmh": clue.fused_speed_kmh,
            "fusion_method": clue.fusion_method, "evidence_package_id": clue.evidence_package_id,
            "evidence_integrity_status": clue.evidence_integrity_status,
            "evidence_count": evidence_count,
            "validation_fixture": bool(event.payload.get("validation_fixture")),
            "legal_status": "not_a_violation_determination",
        }

    async def list_zones(self) -> list[dict]:
        async with self._session_factory() as session:
            rows = (await session.execute(
                select(EnforcementZone, func.count(EnforcementRule.id))
                .outerjoin(EnforcementRule, EnforcementRule.zone_id == EnforcementZone.id)
                .group_by(EnforcementZone.id).order_by(EnforcementZone.created_at.desc())
            )).all()
            return [self._zone(zone, count) for zone, count in rows]

    async def create_zone(self, body: ZoneCreate, actor_id: int | None) -> dict:
        values = body.model_dump(mode="json")
        now = datetime.now(UTC)
        row = EnforcementZone(
            id=_id("ZONE"), **values, source="local_candidate", status="candidate",
            checksum=_hash(values), revision=1, created_by=actor_id, updated_at=now,
        )
        async with self._session_factory() as session:
            session.add(row)
            session.add(AuditLog(actor_id=actor_id, action="enforcement.zone.create", target_type="enforcement_zone", target_id=row.id, after_value=values))
            await session.commit()
            await session.refresh(row)
        return self._zone(row)

    async def update_zone(self, zone_id: str, body: ZoneUpdate, actor_id: int | None) -> dict:
        async with self._session_factory() as session:
            row = (await session.execute(select(EnforcementZone).where(EnforcementZone.id == zone_id).with_for_update())).scalar_one_or_none()
            if row is None:
                raise EnforcementError(404, "zone_not_found", "执法候选区域不存在")
            if row.revision != body.revision:
                raise EnforcementError(409, "revision_conflict", f"区域已更新，当前 revision={row.revision}")
            before = self._zone(row)
            changes = body.model_dump(exclude={"revision"}, exclude_none=True, mode="json")
            for key, value in changes.items():
                setattr(row, key, value)
            row.revision += 1
            row.updated_at = datetime.now(UTC)
            row.checksum = _hash({
                "name": row.name, "zone_type": row.zone_type, "geometry": row.geometry,
                "coordinate_system": row.coordinate_system, "road_data_version": row.road_data_version,
                "schedule": row.schedule,
            })
            session.add(AuditLog(actor_id=actor_id, action="enforcement.zone.update", target_type="enforcement_zone", target_id=row.id, before_value=before, after_value=changes))
            await session.commit()
            await session.refresh(row)
            return self._zone(row)

    async def list_rules(self) -> list[dict]:
        async with self._session_factory() as session:
            rows = (await session.execute(select(EnforcementRule).order_by(EnforcementRule.created_at.desc()))).scalars().all()
            return [self._rule(row) for row in rows]

    async def create_rule(self, body: RuleCreate, actor_id: int | None) -> dict:
        async with self._session_factory() as session:
            if body.zone_id and await session.get(EnforcementZone, body.zone_id) is None:
                raise EnforcementError(422, "zone_not_found", "规则引用的候选区域不存在")
            rule_id = _id("RULE")
            version_id = _id("RULEV")
            definition = body.definition
            session.add(RuleVersion(
                id=version_id, rule_type=f"enforcement.{body.clue_type}", version=f"{rule_id}-r1",
                status="draft", rule_schema=definition,
            ))
            await session.flush()
            row = EnforcementRule(
                id=rule_id, rule_version_id=version_id, zone_id=body.zone_id, name=body.name,
                clue_type=body.clue_type, definition=definition, source="local_candidate",
                status="candidate", quality_status="unverified", revision=1, created_by=actor_id,
                updated_at=datetime.now(UTC),
            )
            session.add(row)
            session.add(AuditLog(actor_id=actor_id, action="enforcement.rule.create", target_type="enforcement_rule", target_id=rule_id, after_value=body.model_dump(mode="json")))
            await session.commit()
            await session.refresh(row)
            return self._rule(row)

    async def update_rule(self, rule_id: str, body: RuleUpdate, actor_id: int | None) -> dict:
        async with self._session_factory() as session:
            row = (await session.execute(select(EnforcementRule).where(EnforcementRule.id == rule_id).with_for_update())).scalar_one_or_none()
            if row is None:
                raise EnforcementError(404, "rule_not_found", "执法候选规则不存在")
            if row.revision != body.revision:
                raise EnforcementError(409, "revision_conflict", f"规则已更新，当前 revision={row.revision}")
            if body.zone_id and await session.get(EnforcementZone, body.zone_id) is None:
                raise EnforcementError(422, "zone_not_found", "规则引用的候选区域不存在")
            changes = body.model_dump(exclude={"revision"}, exclude_none=True, mode="json")
            before = self._rule(row)
            for key, value in changes.items():
                setattr(row, key, value)
            row.revision += 1
            row.updated_at = datetime.now(UTC)
            version = await session.get(RuleVersion, row.rule_version_id)
            if version and body.definition is not None:
                version.rule_schema = body.definition
                version.version = f"{row.id}-r{row.revision}"
            session.add(AuditLog(actor_id=actor_id, action="enforcement.rule.update", target_type="enforcement_rule", target_id=row.id, before_value=before, after_value=changes))
            await session.commit()
            await session.refresh(row)
            return self._rule(row)

    async def publish_candidate(self, target: str, target_id: str) -> None:
        raise EnforcementError(
            503, "authority_adapter_unavailable",
            f"{target} {target_id} 仅为本地候选；权威发布 Adapter 和审批合同尚未冻结",
        )

    async def ingest_clue(self, body: ClueIngest, actor_id: int | None) -> dict:
        payload = body.model_dump(mode="json")
        payload_hash = _hash(payload)
        async with self._session_factory() as session:
            existing = (await session.execute(select(AiEvent).where(
                AiEvent.source_system == SOURCE_SYSTEM,
                AiEvent.source_event_id == body.source_event_id,
            ))).scalar_one_or_none()
            if existing:
                if existing.payload_hash != payload_hash:
                    raise EnforcementError(409, "event_identity_conflict", "同一 source_event_id 的事实哈希不同")
                clue = await session.get(EnforcementClue, existing.id)
                return self._clue(existing, clue, len(body.evidence))

            event_id = _id("CLUE")
            package = None
            evidence_status = "missing"
            if body.evidence:
                package = EvidencePackage(
                    id=_id("EVP"), task_id=None, owner_type="ai_event", owner_id=event_id,
                    source_system=SOURCE_SYSTEM, source_event_id=body.source_event_id,
                    version=1, integrity_status="hash_verified",
                    manifest_hash=_hash({"items": [item.model_dump(mode="json") for item in body.evidence]}),
                )
                session.add(package)
                await session.flush()
                for reference in body.evidence:
                    session.add(EvidenceItem(
                        id=_id("EVI"), package_id=package.id, task_id=None, kind=reference.kind,
                        storage_key=reference.storage_key, sha256=reference.sha256,
                        media_type=reference.media_type, size_bytes=reference.size_bytes,
                        item_metadata=reference.metadata,
                    ))
                evidence_status = "hash_verified"

            event = AiEvent(
                id=event_id, source_system=SOURCE_SYSTEM, source_event_id=body.source_event_id,
                idempotency_key=body.idempotency_key, event_type="enforcement_clue",
                review_status="pending", review_revision=1, occurred_at=body.occurred_at.astimezone(UTC),
                inter_id=body.inter_id, road_data_version=body.road_data_version,
                quality_status=body.quality_status, payload_hash=payload_hash,
                delivery_status="blocked", payload=payload,
            )
            clue = EnforcementClue(
                event_id=event_id, event_revision=1, track_id=body.track_id,
                vehicle_class=body.vehicle_class, class_confidence=body.class_confidence,
                classification_model_version=body.classification_model_version,
                clue_type=body.clue_type, zone_id=body.zone_id, zone_version=body.zone_version,
                rule_id=body.rule_id, rule_version=body.rule_version,
                matched_facts=body.matched_facts, exclusion_result=body.exclusion_result,
                video_speed_kmh=body.video_speed_kmh, video_speed_method=body.video_speed_method,
                video_speed_quality=body.video_speed_quality,
                video_speed_uncertainty=body.video_speed_uncertainty,
                radar_speed_kmh=body.radar_speed_kmh, radar_device_id=body.radar_device_id,
                radar_metadata=body.radar_metadata, fused_speed_kmh=body.fused_speed_kmh,
                fusion_method=body.fusion_method,
                evidence_package_id=package.id if package else None,
                evidence_integrity_status=evidence_status,
            )
            session.add(event)
            await session.flush()
            session.add(clue)
            session.add(AuditLog(actor_id=actor_id, action="enforcement.clue.ingest", target_type="ai_event", target_id=event_id, after_value={"source_event_id": body.source_event_id, "quality_status": body.quality_status, "validation_fixture": body.validation_fixture}))
            await session.commit()
            return self._clue(event, clue, len(body.evidence))

    async def list_clues(self, review_status: str | None = None, clue_type: str | None = None) -> list[dict]:
        async with self._session_factory() as session:
            statement = select(AiEvent, EnforcementClue).join(EnforcementClue, EnforcementClue.event_id == AiEvent.id).where(AiEvent.event_type == "enforcement_clue")
            if review_status:
                statement = statement.where(AiEvent.review_status == review_status)
            if clue_type:
                statement = statement.where(EnforcementClue.clue_type == clue_type)
            rows = (await session.execute(statement.order_by(AiEvent.occurred_at.desc()))).all()
            results = []
            for event, clue in rows:
                count = 0
                if clue.evidence_package_id:
                    count = int(await session.scalar(select(func.count()).select_from(EvidenceItem).where(EvidenceItem.package_id == clue.evidence_package_id)) or 0)
                results.append(self._clue(event, clue, count))
            return results

    async def get_clue(self, event_id: str) -> dict:
        async with self._session_factory() as session:
            row = (await session.execute(select(AiEvent, EnforcementClue).join(EnforcementClue).where(AiEvent.id == event_id))).one_or_none()
            if row is None:
                raise EnforcementError(404, "clue_not_found", "AI 执法线索不存在")
            event, clue = row
            items = []
            if clue.evidence_package_id:
                evidence = (await session.execute(select(EvidenceItem).where(EvidenceItem.package_id == clue.evidence_package_id).order_by(EvidenceItem.created_at))).scalars().all()
                items = [{
                    "id": item.id, "kind": item.kind, "storage_key": item.storage_key,
                    "sha256": item.sha256, "media_type": item.media_type,
                    "size_bytes": item.size_bytes, "metadata": item.item_metadata,
                } for item in evidence]
            return {**self._clue(event, clue, len(items)), "evidence": items}

    async def review_clue(self, event_id: str, body: ClueReview, actor_id: int | None) -> dict:
        async with self._session_factory() as session:
            event = (await session.execute(select(AiEvent).where(AiEvent.id == event_id, AiEvent.event_type == "enforcement_clue").with_for_update())).scalar_one_or_none()
            clue = await session.get(EnforcementClue, event_id) if event else None
            if event is None or clue is None:
                raise EnforcementError(404, "clue_not_found", "AI 执法线索不存在")
            if event.review_revision != body.expected_revision:
                raise EnforcementError(409, "revision_conflict", f"线索已复核更新，当前 revision={event.review_revision}")
            previous_status = event.review_status
            event.review_status = body.review_status
            event.review_revision += 1
            event.review_reason = body.reason
            event.reviewed_by = actor_id
            event.reviewed_at = datetime.now(UTC)
            session.add(EnforcementReviewAudit(
                event_id=event.id, revision=event.review_revision, review_status=body.review_status,
                reason=body.reason, reviewed_by=actor_id,
            ))
            session.add(AuditLog(actor_id=actor_id, action="enforcement.clue.review", target_type="ai_event", target_id=event.id, before_value={"review_status": previous_status, "revision": body.expected_revision}, after_value={"review_status": body.review_status, "revision": event.review_revision}, reason=body.reason))
            await session.commit()
            await session.refresh(event)
            return self._clue(event, clue)

    async def truck_summary(self) -> dict:
        clues = [item for item in await self.list_clues() if item["vehicle_class"] == "truck"]
        as_of = max((item["occurred_at"] for item in clues if item["occurred_at"]), default=None)
        stale = True
        if as_of:
            stale = (datetime.now(UTC) - datetime.fromisoformat(as_of)).total_seconds() > 300
        return {
            "as_of": as_of, "status": "stale" if stale else "fresh",
            "active_count": 0, "clue_count": len(clues),
            "pending_review_count": sum(item["review_status"] == "pending" for item in clues),
            "vehicles": [],
            "reason": "当前只持久化已完成 AI 线索，不以历史事实伪造实时车辆位置",
        }
