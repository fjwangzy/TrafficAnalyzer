"""Persistent accident-survey domain models (ADR-019 / S3)."""

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class SurveyTask(Base):
    __tablename__ = "uav_survey_tasks"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    external_task_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="local")
    scene_location: Mapped[str] = mapped_column(String(300), nullable=False)
    inter_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    road_data_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    assignee_user_id: Mapped[int | None] = mapped_column(ForeignKey("uav_users.id"), nullable=True, index=True)
    owner_name: Mapped[str] = mapped_column(String(120), nullable=False, default="未分配")
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="created", index=True)
    quality_status: Mapped[str] = mapped_column(String(24), nullable=False, default="unverified")
    delivery_status: Mapped[str] = mapped_column(String(24), nullable=False, default="not_generated")
    precheck: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    selected_batch_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("uav_users.id"), nullable=True)
    last_return_type: Mapped[str | None] = mapped_column(String(24), nullable=True)
    last_return_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=lambda: datetime.now(UTC), nullable=False
    )


class EvidencePackage(Base):
    __tablename__ = "uav_evidence_packages"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("uav_survey_tasks.id", ondelete="CASCADE"), nullable=True, index=True)
    owner_type: Mapped[str] = mapped_column(String(40), nullable=False, default="survey_task")
    owner_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    source_system: Mapped[str] = mapped_column(String(80), nullable=False, default="uav_traffic_analyzer_ai")
    source_event_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    integrity_status: Mapped[str] = mapped_column(String(24), nullable=False, default="unverified")
    manifest_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    items: Mapped[list["EvidenceItem"]] = relationship(
        back_populates="package",
        cascade="all, delete-orphan",
    )

    __table_args__ = (UniqueConstraint("task_id", "version", name="uq_uav_evidence_package_task_version"),)


class EvidenceItem(Base):
    __tablename__ = "uav_evidence_items"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    package_id: Mapped[str] = mapped_column(ForeignKey("uav_evidence_packages.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("uav_survey_tasks.id", ondelete="CASCADE"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    storage_backend: Mapped[str] = mapped_column(String(24), nullable=False, default="managed")
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    media_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    derived_from_id: Mapped[str | None] = mapped_column(ForeignKey("uav_evidence_items.id"), nullable=True)
    item_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    package: Mapped[EvidencePackage] = relationship(back_populates="items")


class SurveyCaptureBatch(Base):
    __tablename__ = "uav_capture_batches"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("uav_survey_tasks.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="processing", index=True)
    source_type: Mapped[str] = mapped_column(String(24), nullable=False, default="mp4_srt")
    source_profile_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    video_evidence_id: Mapped[str | None] = mapped_column(ForeignKey("uav_evidence_items.id"), nullable=True)
    telemetry_evidence_id: Mapped[str | None] = mapped_column(ForeignKey("uav_evidence_items.id"), nullable=True)
    duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    fps: Mapped[float | None] = mapped_column(Float, nullable=True)
    frame_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    telemetry_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_checks: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    calibration: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=lambda: datetime.now(UTC), nullable=False
    )


class CaptureIngestionJob(Base):
    __tablename__ = "uav_capture_ingestion_jobs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("uav_survey_tasks.id", ondelete="CASCADE"), index=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("uav_capture_batches.id", ondelete="CASCADE"), unique=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=lambda: datetime.now(UTC), nullable=False
    )


class SurveyFrame(Base):
    __tablename__ = "uav_capture_frames"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("uav_survey_tasks.id", ondelete="CASCADE"), index=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("uav_capture_batches.id", ondelete="CASCADE"), index=True)
    frame_number: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp_sec: Mapped[float] = mapped_column(Float, nullable=False)
    image_evidence_id: Mapped[str] = mapped_column(ForeignKey("uav_evidence_items.id"), nullable=False)
    bev_evidence_id: Mapped[str] = mapped_column(ForeignKey("uav_evidence_items.id"), nullable=False)
    image_width: Mapped[int] = mapped_column(Integer, nullable=False)
    image_height: Mapped[int] = mapped_column(Integer, nullable=False)
    homography: Mapped[list | None] = mapped_column(JSON, nullable=True)
    view_transform: Mapped[list] = mapped_column(JSON, nullable=False)
    telemetry: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    quality: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("batch_id", "frame_number", name="uq_uav_capture_frame_batch_number"),)


class SurveyMeasurement(Base):
    __tablename__ = "uav_survey_measurements"

    row_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    measurement_id: Mapped[str] = mapped_column(String(40), nullable=False)
    task_id: Mapped[str] = mapped_column(ForeignKey("uav_survey_tasks.id", ondelete="CASCADE"), index=True)
    frame_id: Mapped[str] = mapped_column(ForeignKey("uav_capture_frames.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    geometry_type: Mapped[str] = mapped_column(String(24), nullable=False)
    category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    image_geometry: Mapped[list] = mapped_column(JSON, nullable=False)
    metric_geometry: Mapped[list | None] = mapped_column(JSON, nullable=True)
    computed_values: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error_estimate: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    quality_status: Mapped[str] = mapped_column(String(24), nullable=False, default="unverified")
    source: Mapped[str] = mapped_column(String(24), nullable=False, default="manual")
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("uav_users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("task_id", "measurement_id", "revision", name="uq_uav_measurement_revision"),
    )


class SceneAnnotation(Base):
    __tablename__ = "uav_scene_annotations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("uav_survey_tasks.id", ondelete="CASCADE"), index=True)
    frame_id: Mapped[str] = mapped_column(ForeignKey("uav_capture_frames.id"), index=True)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    image_geometry: Mapped[list] = mapped_column(JSON, nullable=False)
    source: Mapped[str] = mapped_column(String(24), nullable=False, default="manual")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_state: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SurveyReport(Base):
    __tablename__ = "uav_survey_reports"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("uav_survey_tasks.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="generated")
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False, default="uav.survey-result.v1")
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    pdf_evidence_id: Mapped[str | None] = mapped_column(ForeignKey("uav_evidence_items.id"), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("uav_users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("task_id", "version", name="uq_uav_survey_report_task_version"),)


class AuditLog(Base):
    __tablename__ = "uav_audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("uav_users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    before_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_value: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("action", "request_id", name="uq_uav_audit_action_request"),)


class AiEvent(Base):
    __tablename__ = "uav_ai_events"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    source_system: Mapped[str] = mapped_column(String(80), nullable=False, default="uav_traffic_analyzer_ai")
    source_event_id: Mapped[str] = mapped_column(String(80), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("uav_survey_tasks.id"), nullable=True)
    review_status: Mapped[str] = mapped_column(String(24), nullable=False, default="technical_reviewed")
    review_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("uav_users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    inter_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    road_data_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    quality_status: Mapped[str] = mapped_column(String(24), nullable=False, default="unverified")
    payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    delivery_status: Mapped[str] = mapped_column(String(24), nullable=False, default="not_queued")
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("source_system", "source_event_id", name="uq_uav_ai_event_source_id"),
        UniqueConstraint("source_system", "idempotency_key", name="uq_uav_ai_event_idempotency"),
    )


class EventOutbox(Base):
    __tablename__ = "uav_event_outbox"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("uav_ai_events.id"), index=True)
    destination: Mapped[str] = mapped_column(String(300), nullable=False)
    source_system: Mapped[str] = mapped_column(String(80), nullable=False, default="uav_traffic_analyzer_ai")
    message_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("idempotency_key", "destination", name="uq_uav_outbox_delivery"),)


class EventDeliveryAttempt(Base):
    __tablename__ = "uav_event_delivery_attempts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    outbox_id: Mapped[str] = mapped_column(ForeignKey("uav_event_outbox.id", ondelete="CASCADE"), index=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    platform_event_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    receipt_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class DeadLetter(Base):
    __tablename__ = "uav_dead_letters"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    outbox_id: Mapped[str] = mapped_column(ForeignKey("uav_event_outbox.id"), unique=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RuleVersion(Base):
    __tablename__ = "uav_rule_versions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    rule_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    rule_schema: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("uav_users.id"), nullable=True)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("rule_type", "version", name="uq_uav_rule_type_version"),)
