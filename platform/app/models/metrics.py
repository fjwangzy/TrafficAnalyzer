"""ADR-019 PostgreSQL/TimescaleDB traffic fact models.

The time-series tables use a composite primary key that includes the time
partition column, which is required by TimescaleDB hypertables.  Business
payloads are retained verbatim for audit/replay while frequently queried
dimensions remain typed columns.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class _MessageFact:
    source_system: Mapped[str] = mapped_column(String(80), nullable=False)
    source_message_id: Mapped[str] = mapped_column(String(160), nullable=False)
    msg_type: Mapped[str] = mapped_column(String(80), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(80), nullable=False)
    produced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    topic: Mapped[str] = mapped_column(String(160), nullable=False)
    partition: Mapped[int] = mapped_column(Integer, nullable=False)
    offset: Mapped[int] = mapped_column(BigInteger, nullable=False)
    camera_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    drone_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    intersection_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    road_context_status: Mapped[str] = mapped_column(String(32), nullable=False, default="missing")
    source_time_raw: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_time_semantics: Mapped[str] = mapped_column(String(32), nullable=False)
    time_quality: Mapped[str] = mapped_column(String(24), nullable=False)
    quality_status: Mapped[str] = mapped_column(String(24), nullable=False, default="unverified")
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)


class TrafficMetric(_MessageFact, Base):
    __tablename__ = "uav_traffic_metrics"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    inter_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    road_data_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    grain_type: Mapped[str] = mapped_column(String(16), nullable=False)
    grain_key: Mapped[str] = mapped_column(String(120), nullable=False)
    cars: Mapped[float | None] = mapped_column(Float, nullable=True)
    active_tracks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vehicle_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    flow_veh_per_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_speed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    congestion_index: Mapped[float | None] = mapped_column(Float, nullable=True)
    queue_length_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    headway_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    queue_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    direction_flow: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    roads: Mapped[list | None] = mapped_column(JSON, nullable=True)
    link_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lane_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expected_samples: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_samples: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dropped_samples: Mapped[int | None] = mapped_column(Integer, nullable=True)
    coverage_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    drop_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)

    __table_args__ = (
        CheckConstraint("source_system = 'uav_traffic_analyzer_ai'", name="ck_uav_traffic_metric_source"),
        CheckConstraint("grain_type IN ('intersection','link','lane')", name="ck_uav_traffic_metric_grain"),
        UniqueConstraint(
            "observed_at", "source_system", "source_message_id", "grain_type", "grain_key",
            name="uq_uav_traffic_metric_message_grain",
        ),
    )


class TrackEvent(_MessageFact, Base):
    __tablename__ = "uav_track_events"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    inter_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    road_data_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    track_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    vehicle_class: Mapped[str | None] = mapped_column(String(80), nullable=True)
    turn_behavior: Mapped[str | None] = mapped_column(String(80), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_speed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_speed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    trajectory_px: Mapped[list | None] = mapped_column(JSON, nullable=True)
    trajectory_world_m: Mapped[list | None] = mapped_column(JSON, nullable=True)
    entry_point_m: Mapped[list | None] = mapped_column(JSON, nullable=True)
    exit_point_m: Mapped[list | None] = mapped_column(JSON, nullable=True)
    start_link_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    end_link_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    start_lane_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    end_lane_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    world_anchor_lat_lon: Mapped[list | None] = mapped_column(JSON, nullable=True)
    map_match_quality: Mapped[str | None] = mapped_column(String(32), nullable=True)

    __table_args__ = (
        CheckConstraint("source_system = 'uav_traffic_analyzer_ai'", name="ck_uav_track_event_source"),
        UniqueConstraint("source_system", "source_message_id", name="uq_uav_track_event_message"),
    )


class TrackPoint(_MessageFact, Base):
    __tablename__ = "uav_track_points"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    track_event_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    inter_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    track_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    point_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    pixel_x: Mapped[float | None] = mapped_column(Float, nullable=True)
    pixel_y: Mapped[float | None] = mapped_column(Float, nullable=True)
    world_x_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    world_y_m: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (
        CheckConstraint("source_system = 'uav_traffic_analyzer_ai'", name="ck_uav_track_point_source"),
        UniqueConstraint(
            "observed_at", "source_system", "source_message_id", "point_seq",
            name="uq_uav_track_point_message_seq",
        ),
    )


class ConflictEvent(_MessageFact, Base):
    __tablename__ = "uav_conflict_events"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    inter_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    road_data_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    motor_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    non_motor_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    severity: Mapped[str | None] = mapped_column(String(24), nullable=True)
    ttc_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    pet_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    conflict_scene: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prediction_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    conflict_angle_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence: Mapped[list | dict | None] = mapped_column(JSON, nullable=True)
    motor_position_m: Mapped[list | None] = mapped_column(JSON, nullable=True)
    non_motor_position_m: Mapped[list | None] = mapped_column(JSON, nullable=True)
    world_anchor_lat_lon: Mapped[list | None] = mapped_column(JSON, nullable=True)
    __table_args__ = (
        CheckConstraint("source_system = 'uav_traffic_analyzer_ai'", name="ck_uav_conflict_event_source"),
        UniqueConstraint(
            "occurred_at", "source_system", "source_message_id",
            name="uq_uav_conflict_event_message",
        ),
    )


class ConflictReview(Base):
    __tablename__ = "uav_conflict_reviews"

    event_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    event_occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    inter_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    review_status: Mapped[str] = mapped_column(String(24), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("uav_users.id"), nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        # Migration 20260715_0009 installs restore-safe existence/cascade
        # triggers. A regular-table FK to a Timescale hypertable expands into
        # chunk constraints that pg_dump cannot recreate reliably.
        CheckConstraint(
            "review_status IN ('confirmed','rejected')",
            name="ck_uav_conflict_reviews_status",
        ),
    )


class TelemetryMetric(_MessageFact, Base):
    __tablename__ = "uav_telemetry_metrics"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    drone_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    mission_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    pipeline_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    altitude_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    relative_altitude_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    speed_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    heading_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    battery_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    pitch_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    roll_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    gimbal_pitch_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    gimbal_yaw_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_hovering: Mapped[bool | None] = mapped_column(nullable=True)
    positioning_quality: Mapped[str | None] = mapped_column(String(32), nullable=True)

    __table_args__ = (
        CheckConstraint("source_system = 'uav_traffic_analyzer_ai'", name="ck_uav_telemetry_metric_source"),
        UniqueConstraint(
            "observed_at", "source_system", "source_message_id",
            name="uq_uav_telemetry_metric_message",
        ),
    )


class SystemMetric(_MessageFact, Base):
    __tablename__ = "uav_system_metrics"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    instance_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    metric_name: Mapped[str] = mapped_column(String(120), nullable=False)
    metric_value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    labels: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    __table_args__ = (
        CheckConstraint("source_system = 'uav_traffic_analyzer_ai'", name="ck_uav_system_metric_source"),
        UniqueConstraint(
            "observed_at", "source_system", "source_message_id", "metric_name",
            name="uq_uav_system_metric_message_name",
        ),
    )
