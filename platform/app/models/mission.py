"""Persistent S5/S9 road-context and mission-planning models."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    Float,
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class RoadContextSnapshot(Base):
    __tablename__ = "uav_road_context_snapshots"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    inter_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    road_data_version: Mapped[str] = mapped_column(String(100), nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    coordinate_reference: Mapped[dict] = mapped_column(JSON, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    quality_status: Mapped[str] = mapped_column(String(24), nullable=False, default="unverified")
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("inter_id", "road_data_version", name="uq_uav_road_context_inter_version"),
    )


class VisualLaneBinding(Base):
    __tablename__ = "uav_visual_lane_bindings"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    inter_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    road_data_version: Mapped[str] = mapped_column(String(100), nullable=False)
    map_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("uav_channelized_map_versions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    local_lane_id: Mapped[str] = mapped_column(String(100), nullable=False)
    canonical_link_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    canonical_lane_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    geometry_source: Mapped[str] = mapped_column(String(32), nullable=False, default="link_offset_derived")
    geometry_gcj02: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    geometry_enu_m: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    match_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="candidate")
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("uav_users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("map_version_id", "local_lane_id", name="uq_uav_visual_binding_map_lane"),
        CheckConstraint(
            "geometry_source IN ('link_offset_derived','imagery_fitted','manual_override')",
            name="ck_uav_visual_binding_geometry_source",
        ),
    )


class ChannelizedMapVersion(Base):
    __tablename__ = "uav_channelized_map_versions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    inter_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    road_data_version: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft", index=True)
    coordinate_system: Mapped[str] = mapped_column(String(16), nullable=False, default="GCJ02")
    coordinate_transform_version: Mapped[str] = mapped_column(String(80), nullable=False)
    anchor_gcj02: Mapped[list] = mapped_column(JSON, nullable=False)
    geometry_gcj02: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    geometry_enu_m: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    topology: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    quality: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("uav_users.id"), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("inter_id", "version_no", name="uq_uav_channelized_map_inter_version"),
        CheckConstraint(
            "status IN ('draft','candidate','link_verified','lane_verified','retired')",
            name="ck_uav_channelized_map_status",
        ),
        CheckConstraint("coordinate_system = 'GCJ02'", name="ck_uav_channelized_map_coordinate_system"),
    )


class VisualRegistration(Base):
    __tablename__ = "uav_visual_registrations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    map_version_id: Mapped[str] = mapped_column(
        ForeignKey("uav_channelized_map_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("uav_video_sources.profile_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    source_image_path: Mapped[str] = mapped_column(String(500), nullable=False)
    orthophoto_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    control_points: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    homography_pixel_to_enu: Mapped[list | None] = mapped_column(JSON, nullable=True)
    residuals: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("uav_users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "map_version_id", "source_profile_id",
            name="uq_uav_visual_registration_map_source",
        ),
        CheckConstraint(
            "status IN ('draft','registered','verified','rejected')",
            name="ck_uav_visual_registration_status",
        ),
    )


class LaneAnnotationTaskRecord(Base):
    __tablename__ = "uav_lane_annotation_tasks"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    inter_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    road_data_version: Mapped[str] = mapped_column(String(100), nullable=False)
    map_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("uav_channelized_map_versions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", index=True)
    image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    annotation: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("uav_users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=lambda: datetime.now(UTC), nullable=False
    )


class DeviceIntersectionBinding(Base):
    __tablename__ = "uav_device_intersection_bindings"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    device_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    inter_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    road_data_version: Mapped[str] = mapped_column(String(100), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class DroneRecord(Base):
    __tablename__ = "uav_drones"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    serial_number: Mapped[str | None] = mapped_column(String(160), nullable=True, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    default_inter_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    default_video_source_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    default_telemetry_source_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=lambda: datetime.now(UTC), nullable=False
    )


class VideoSourceRecord(Base):
    __tablename__ = "uav_video_sources"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(40), nullable=False, unique=True, index=True)
    drone_id: Mapped[str] = mapped_column(ForeignKey("uav_drones.id", ondelete="CASCADE"), index=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    location: Mapped[str] = mapped_column(Text, nullable=False)
    credential_ref: Mapped[str | None] = mapped_column(String(300), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    validation_status: Mapped[str] = mapped_column(String(24), nullable=False, default="unknown")
    validation_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=lambda: datetime.now(UTC), nullable=False
    )


class TelemetrySourceRecord(Base):
    __tablename__ = "uav_telemetry_sources"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(40), nullable=False, unique=True, index=True)
    drone_id: Mapped[str] = mapped_column(ForeignKey("uav_drones.id", ondelete="CASCADE"), index=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    location: Mapped[str] = mapped_column(Text, nullable=False)
    credential_ref: Mapped[str | None] = mapped_column(String(300), nullable=True)
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    validation_status: Mapped[str] = mapped_column(String(24), nullable=False, default="unknown")
    validation_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=lambda: datetime.now(UTC), nullable=False
    )


class FlightPlanRecord(Base):
    __tablename__ = "uav_flight_plans"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    drone_id: Mapped[str] = mapped_column(ForeignKey("uav_drones.id"), index=True)
    video_source_id: Mapped[str] = mapped_column(ForeignKey("uav_video_sources.id"))
    telemetry_source_id: Mapped[str] = mapped_column(ForeignKey("uav_telemetry_sources.id"))
    inter_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    road_data_version: Mapped[str] = mapped_column(String(100), nullable=False)
    ai_mode: Mapped[str] = mapped_column(String(40), nullable=False, default="traffic_monitoring")
    schedule_type: Mapped[str] = mapped_column(String(16), nullable=False)
    schedule: Mapped[dict] = mapped_column(JSON, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Shanghai")
    state: Mapped[str] = mapped_column(String(24), nullable=False, default="draft", index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("uav_users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=lambda: datetime.now(UTC), nullable=False
    )


class MissionRecord(Base):
    __tablename__ = "uav_missions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    flight_plan_id: Mapped[str | None] = mapped_column(ForeignKey("uav_flight_plans.id"), nullable=True, index=True)
    parent_mission_id: Mapped[str | None] = mapped_column(ForeignKey("uav_missions.id"), nullable=True)
    retry_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trigger_type: Mapped[str] = mapped_column(String(24), nullable=False)
    drone_id: Mapped[str] = mapped_column(ForeignKey("uav_drones.id"), index=True)
    video_source_id: Mapped[str | None] = mapped_column(ForeignKey("uav_video_sources.id"), nullable=True)
    telemetry_source_id: Mapped[str | None] = mapped_column(ForeignKey("uav_telemetry_sources.id"), nullable=True)
    inter_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    road_data_version: Mapped[str] = mapped_column(String(100), nullable=False)
    scheduled_start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    scheduled_end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actual_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    actual_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending", index=True)
    reason_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    pipeline_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    context_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("uav_users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=lambda: datetime.now(UTC), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("flight_plan_id", "scheduled_start_at", name="uq_uav_mission_plan_occurrence"),
    )


class PipelineRecord(Base):
    __tablename__ = "uav_pipelines"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    mission_id: Mapped[str] = mapped_column(ForeignKey("uav_missions.id", ondelete="CASCADE"), unique=True)
    desired_status: Mapped[str] = mapped_column(String(24), nullable=False)
    observed_status: Mapped[str] = mapped_column(String(24), nullable=False)
    topic_name: Mapped[str] = mapped_column(String(120), nullable=False)
    camera_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    video_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=lambda: datetime.now(UTC), nullable=False
    )


class EventFeedback(Base):
    __tablename__ = "uav_event_feedback"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    source_system: Mapped[str] = mapped_column(String(80), nullable=False)
    source_event_id: Mapped[str] = mapped_column(String(80), nullable=False)
    platform_event_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    feedback_version: Mapped[int] = mapped_column(Integer, nullable=False)
    result: Mapped[str] = mapped_column(String(40), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    actor_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "source_system", "source_event_id", "feedback_version",
            name="uq_uav_feedback_source_version",
        ),
    )


class MessageInbox(Base):
    __tablename__ = "uav_message_inbox"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    source_system: Mapped[str] = mapped_column(String(80), nullable=False)
    message_id: Mapped[str] = mapped_column(String(160), nullable=False)
    topic: Mapped[str] = mapped_column(String(160), nullable=False)
    partition: Mapped[int] = mapped_column(Integer, nullable=False)
    offset: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="processed")
    dispatch_status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    dispatch_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_dispatch_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_dispatch_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fact_references: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("topic", "partition", "offset", name="uq_uav_inbox_topic_partition_offset"),
        UniqueConstraint("source_system", "message_id", name="uq_uav_inbox_source_message"),
    )


class MessageDeadLetter(Base):
    """Durable quarantine for permanently invalid inbound Kafka records."""

    __tablename__ = "uav_message_dead_letters"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    source_system: Mapped[str] = mapped_column(String(80), nullable=False)
    message_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    topic: Mapped[str] = mapped_column(String(160), nullable=False)
    partition: Mapped[int] = mapped_column(Integer, nullable=False)
    offset: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    reason_summary: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="quarantined")
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("topic", "partition", "offset", name="uq_uav_message_dlq_transport"),
    )
