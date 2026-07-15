"""S4 enforcement candidate configuration and event-specific facts."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class EnforcementZone(Base):
    __tablename__ = "uav_enforcement_zones"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    zone_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    geometry: Mapped[dict] = mapped_column(JSON, nullable=False)
    coordinate_system: Mapped[str] = mapped_column(String(32), nullable=False)
    road_data_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="local_candidate")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="candidate", index=True)
    schedule: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("uav_users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class EnforcementRule(Base):
    __tablename__ = "uav_enforcement_rules"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    rule_version_id: Mapped[str] = mapped_column(ForeignKey("uav_rule_versions.id"), unique=True)
    zone_id: Mapped[str | None] = mapped_column(ForeignKey("uav_enforcement_zones.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    clue_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    definition: Mapped[dict] = mapped_column(JSON, nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="local_candidate")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="candidate", index=True)
    quality_status: Mapped[str] = mapped_column(String(24), nullable=False, default="unverified")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("uav_users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class EnforcementClue(Base):
    __tablename__ = "uav_enforcement_clues"

    event_id: Mapped[str] = mapped_column(ForeignKey("uav_ai_events.id", ondelete="CASCADE"), primary_key=True)
    event_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    track_id: Mapped[str] = mapped_column(String(80), nullable=False)
    vehicle_class: Mapped[str] = mapped_column(String(24), nullable=False)
    class_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    classification_model_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    clue_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    zone_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    zone_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    rule_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    rule_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    matched_facts: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    exclusion_result: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    video_speed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    video_speed_method: Mapped[str | None] = mapped_column(String(80), nullable=True)
    video_speed_quality: Mapped[str | None] = mapped_column(String(24), nullable=True)
    video_speed_uncertainty: Mapped[float | None] = mapped_column(Float, nullable=True)
    radar_speed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    radar_device_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    radar_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    fused_speed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    fusion_method: Mapped[str | None] = mapped_column(String(80), nullable=True)
    evidence_package_id: Mapped[str | None] = mapped_column(ForeignKey("uav_evidence_packages.id"), nullable=True)
    evidence_integrity_status: Mapped[str] = mapped_column(String(24), nullable=False, default="unverified")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class EnforcementReviewAudit(Base):
    """Append-only S4 review ledger; current review summary remains on AiEvent."""

    __tablename__ = "uav_enforcement_review_audits"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("uav_ai_events.id", ondelete="CASCADE"), index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("uav_users.id"), nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("event_id", "revision", name="uq_uav_enforcement_review_revision"),)
