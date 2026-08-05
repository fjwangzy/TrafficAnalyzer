"""Isolated replay-v2 fact models.

These tables share the canonical ``road9`` database but never share physical
write targets with the live monitoring facts.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ReplayV2Mission(Base):
    __tablename__ = "uav_replay_v2_missions"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    inter_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    source_profile_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    pipeline_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    run_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    coordinate_coverage_ratio: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    journey_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    behavior_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_point_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retained_point_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    algorithm_versions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    accuracy: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    sealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReplayV2MessageInbox(Base):
    __tablename__ = "uav_replay_v2_message_inbox"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    message_id: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    message_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    msg_type: Mapped[str] = mapped_column(String(80), nullable=False)
    topic: Mapped[str] = mapped_column(String(180), nullable=False)
    partition: Mapped[int] = mapped_column(Integer, nullable=False)
    offset: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    fact_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    audit_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("topic", "partition", "offset", name="uq_uav_replay_v2_inbox_offset"),
    )


class ReplayV2MessageDeadLetter(Base):
    __tablename__ = "uav_replay_v2_message_dead_letters"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    topic: Mapped[str] = mapped_column(String(180), nullable=False)
    partition: Mapped[int] = mapped_column(Integer, nullable=False)
    offset: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    reason_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    quarantined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReplayV2TrackEvent(Base):
    __tablename__ = "uav_replay_v2_track_events"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    mission_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    inter_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    source_profile_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    track_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    source_runtime_track_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    vehicle_class: Mapped[str | None] = mapped_column(String(80), nullable=True)
    yolo_class_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    yolo_class_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    turn_behavior: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    movement_key: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    matched_lane_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    matched_link_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    started_offset_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ended_offset_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_point_count: Mapped[int] = mapped_column(Integer, nullable=False)
    retained_point_count: Mapped[int] = mapped_column(Integer, nullable=False)
    sampling: Mapped[dict] = mapped_column(JSON, nullable=False)
    termination_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("mission_id", "track_id", name="uq_uav_replay_v2_track_mission"),
    )


class ReplayV2TrackPoint(Base):
    __tablename__ = "uav_replay_v2_track_points"

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    mission_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    track_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    point_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    offset_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    source_timestamp_sec: Mapped[float] = mapped_column(Float, nullable=False)
    frame_num: Mapped[int] = mapped_column(BigInteger, nullable=False)
    pixel_x: Mapped[float] = mapped_column(Float, nullable=False)
    pixel_y: Mapped[float] = mapped_column(Float, nullable=False)
    enu_x_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    enu_y_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude_gcj02: Mapped[float | None] = mapped_column(Float, nullable=True)
    latitude_gcj02: Mapped[float | None] = mapped_column(Float, nullable=True)
    instant_speed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    ema_speed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    velocity_east_mps: Mapped[float | None] = mapped_column(Float, nullable=True)
    velocity_north_mps: Mapped[float | None] = mapped_column(Float, nullable=True)
    speed_quality: Mapped[str | None] = mapped_column(String(80), nullable=True)
    point_quality: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    sampling_boundary: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    __table_args__ = (
        UniqueConstraint("mission_id", "track_id", "point_seq", name="uq_uav_replay_v2_point_seq"),
    )


class _TimedBehavior:
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    mission_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    track_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    start_offset_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_offset_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_status: Mapped[str] = mapped_column(String(24), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(160), nullable=True)
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    algorithm_version: Mapped[str] = mapped_column(String(100), nullable=False)


class ReplayV2Episode(_TimedBehavior, Base):
    __tablename__ = "uav_replay_v2_episodes"


class ReplayV2Maneuver(_TimedBehavior, Base):
    __tablename__ = "uav_replay_v2_maneuvers"


class ReplayV2ConflictEvent(Base):
    __tablename__ = "uav_replay_v2_conflict_events"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    mission_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    inter_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    offset_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    severity: Mapped[str | None] = mapped_column(String(24), nullable=True)
    prediction_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    ttc_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    pet_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence: Mapped[dict | list | None] = mapped_column(JSON, nullable=True)


class ReplayV2TelemetryMetric(Base):
    __tablename__ = "uav_replay_v2_telemetry_metrics"

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    mission_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    offset_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    drone_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    longitude_gcj02: Mapped[float | None] = mapped_column(Float, nullable=True)
    latitude_gcj02: Mapped[float | None] = mapped_column(Float, nullable=True)
    altitude_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    speed_mps: Mapped[float | None] = mapped_column(Float, nullable=True)
    heading_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_status: Mapped[str] = mapped_column(String(24), nullable=False)


class ReplayV2TrafficMetricSample(Base):
    __tablename__ = "uav_replay_v2_traffic_metric_samples"

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    mission_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    inter_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    source_profile_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    sampled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False, index=True
    )
    vehicle_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active_tracks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avg_speed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    queue_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    coverage_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)


class _ReplayV2Aggregate:
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    inter_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    source_profile_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    mission_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    calc_version: Mapped[str] = mapped_column(String(80), nullable=False)
    vehicle_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avg_speed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    p85_speed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    stopped_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    queue_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    release_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    geometric_u_turn_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    inferred_red_signal_queue_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    coverage_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)


class ReplayV2IntersectionMetric5Min(_ReplayV2Aggregate, Base):
    __tablename__ = "uav_replay_v2_intersection_metrics_5min"

    __table_args__ = (
        UniqueConstraint("window_start", "inter_id", "source_profile_id", "mission_id", "calc_version", name="uq_uav_replay_v2_intersection_5min"),
    )


class ReplayV2LinkMetric5Min(_ReplayV2Aggregate, Base):
    __tablename__ = "uav_replay_v2_link_metrics_5min"

    link_id: Mapped[str] = mapped_column(String(100), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "window_start", "inter_id", "source_profile_id", "mission_id",
            "calc_version", "link_id", name="uq_uav_replay_v2_link_5min",
        ),
    )


class ReplayV2LaneMetric5Min(_ReplayV2Aggregate, Base):
    __tablename__ = "uav_replay_v2_lane_metrics_5min"

    lane_id: Mapped[str] = mapped_column(String(100), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "window_start", "inter_id", "source_profile_id", "mission_id",
            "calc_version", "lane_id", name="uq_uav_replay_v2_lane_5min",
        ),
    )


class ReplayV2TurnMetric5Min(_ReplayV2Aggregate, Base):
    __tablename__ = "uav_replay_v2_turn_metrics_5min"

    movement_key: Mapped[str] = mapped_column(String(120), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "window_start", "inter_id", "source_profile_id", "mission_id",
            "calc_version", "movement_key", name="uq_uav_replay_v2_turn_5min",
        ),
    )


class ReplayV2InterEvaluation5MinMM(Base):
    __tablename__ = "uav_replay_v2_inter_evaluation_5min_mm"

    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    inter_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    source_profile_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_version: Mapped[str] = mapped_column(String(80), nullable=False)
    sample_days: Mapped[int] = mapped_column(Integer, nullable=False)
    vehicle_count: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_speed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    saturation: Mapped[float | None] = mapped_column(Float, nullable=True)
    saturation_reason: Mapped[str | None] = mapped_column(String(160), nullable=True)
    quality_status: Mapped[str] = mapped_column(String(24), nullable=False)

    __table_args__ = (
        UniqueConstraint("inter_id", "source_profile_id", "day_of_week", "step_index", "profile_version", name="uq_uav_replay_v2_inter_mm"),
    )


REPLAY_V2_TABLES = (
    ReplayV2Mission.__table__,
    ReplayV2MessageInbox.__table__,
    ReplayV2MessageDeadLetter.__table__,
    ReplayV2TrackEvent.__table__,
    ReplayV2TrackPoint.__table__,
    ReplayV2Episode.__table__,
    ReplayV2Maneuver.__table__,
    ReplayV2ConflictEvent.__table__,
    ReplayV2TelemetryMetric.__table__,
    ReplayV2TrafficMetricSample.__table__,
    ReplayV2IntersectionMetric5Min.__table__,
    ReplayV2LinkMetric5Min.__table__,
    ReplayV2LaneMetric5Min.__table__,
    ReplayV2TurnMetric5Min.__table__,
    ReplayV2InterEvaluation5MinMM.__table__,
)
