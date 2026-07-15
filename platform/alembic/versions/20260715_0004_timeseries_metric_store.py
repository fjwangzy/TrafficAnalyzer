"""Add ADR-019 metric facts and transaction inbox metadata.

Revision ID: 20260715_0004
Revises: 20260715_0003

TimescaleDB remains an optional local capability during migration: when the
extension is installed the five time-series tables are converted to
hypertables.  A plain PostgreSQL development database receives the identical
schema and remains queryable, but readiness reports it as degraded.
"""

from alembic import op
import sqlalchemy as sa


revision = "20260715_0004"
down_revision = "20260715_0003"
branch_labels = None
depends_on = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _column_names(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _fact_columns(*, include_drone: bool = True) -> list[sa.Column]:
    columns = [
        sa.Column("source_system", sa.String(80), nullable=False),
        sa.Column("source_message_id", sa.String(160), nullable=False),
        sa.Column("msg_type", sa.String(80), nullable=False),
        sa.Column("schema_version", sa.String(80), nullable=False),
        sa.Column("produced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("topic", sa.String(160), nullable=False),
        sa.Column("partition", sa.Integer(), nullable=False),
        sa.Column("offset", sa.BigInteger(), nullable=False),
        sa.Column("camera_id", sa.String(80), nullable=True),
        sa.Column("intersection_id", sa.String(100), nullable=True),
        sa.Column("road_context_status", sa.String(32), nullable=False),
        sa.Column("source_time_raw", sa.JSON(), nullable=True),
        sa.Column("source_time_semantics", sa.String(32), nullable=False),
        sa.Column("time_quality", sa.String(24), nullable=False),
        sa.Column("quality_status", sa.String(24), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    ]
    if include_drone:
        columns.insert(8, sa.Column("drone_id", sa.String(100), nullable=True))
    return columns


def _create_tables() -> None:
    existing = _table_names()
    if "uav_traffic_metrics" not in existing:
        op.create_table(
            "uav_traffic_metrics",
            sa.Column("id", sa.String(80), nullable=False),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("inter_id", sa.String(100), nullable=False),
            sa.Column("road_data_version", sa.String(100), nullable=True),
            sa.Column("grain_type", sa.String(16), nullable=False),
            sa.Column("grain_key", sa.String(120), nullable=False),
            sa.Column("cars", sa.Float(), nullable=True),
            sa.Column("active_tracks", sa.Integer(), nullable=True),
            sa.Column("vehicle_count", sa.Integer(), nullable=True),
            sa.Column("flow_veh_per_min", sa.Float(), nullable=True),
            sa.Column("avg_speed_kmh", sa.Float(), nullable=True),
            sa.Column("congestion_index", sa.Float(), nullable=True),
            sa.Column("queue_length_m", sa.Float(), nullable=True),
            sa.Column("headway_sec", sa.Float(), nullable=True),
            sa.Column("queue_count", sa.Integer(), nullable=True),
            sa.Column("direction_flow", sa.JSON(), nullable=True),
            sa.Column("roads", sa.JSON(), nullable=True),
            sa.Column("link_id", sa.String(100), nullable=True),
            sa.Column("lane_id", sa.String(100), nullable=True),
            sa.Column("window_start", sa.DateTime(timezone=True), nullable=True),
            sa.Column("window_end", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expected_samples", sa.Integer(), nullable=True),
            sa.Column("actual_samples", sa.Integer(), nullable=True),
            sa.Column("dropped_samples", sa.Integer(), nullable=True),
            sa.Column("coverage_ratio", sa.Float(), nullable=True),
            sa.Column("drop_reason", sa.String(120), nullable=True),
            *_fact_columns(),
            sa.PrimaryKeyConstraint("id", "observed_at"),
            sa.CheckConstraint("source_system = 'uav_traffic_analyzer_ai'", name="ck_uav_traffic_metric_source"),
            sa.CheckConstraint("grain_type IN ('intersection','link','lane')", name="ck_uav_traffic_metric_grain"),
            sa.UniqueConstraint(
                "observed_at", "source_system", "source_message_id", "grain_type", "grain_key",
                name="uq_uav_traffic_metric_message_grain",
            ),
        )
        op.create_index("ix_uav_traffic_metrics_inter_id", "uav_traffic_metrics", ["inter_id"])
        op.create_index("ix_uav_traffic_metrics_inter_time", "uav_traffic_metrics", ["inter_id", "observed_at"])

    if "uav_track_events" not in existing:
        op.create_table(
            "uav_track_events",
            sa.Column("id", sa.String(80), primary_key=True),
            sa.Column("inter_id", sa.String(100), nullable=False),
            sa.Column("road_data_version", sa.String(100), nullable=True),
            sa.Column("track_id", sa.String(100), nullable=False),
            sa.Column("vehicle_class", sa.String(80), nullable=True),
            sa.Column("turn_behavior", sa.String(80), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("duration_sec", sa.Float(), nullable=True),
            sa.Column("avg_speed_kmh", sa.Float(), nullable=True),
            sa.Column("max_speed_kmh", sa.Float(), nullable=True),
            sa.Column("trajectory_px", sa.JSON(), nullable=True),
            sa.Column("trajectory_world_m", sa.JSON(), nullable=True),
            sa.Column("entry_point_m", sa.JSON(), nullable=True),
            sa.Column("exit_point_m", sa.JSON(), nullable=True),
            sa.Column("start_link_id", sa.String(100), nullable=True),
            sa.Column("end_link_id", sa.String(100), nullable=True),
            sa.Column("start_lane_id", sa.String(100), nullable=True),
            sa.Column("end_lane_id", sa.String(100), nullable=True),
            sa.Column("world_anchor_lat_lon", sa.JSON(), nullable=True),
            sa.Column("map_match_quality", sa.String(32), nullable=True),
            *_fact_columns(),
            sa.CheckConstraint("source_system = 'uav_traffic_analyzer_ai'", name="ck_uav_track_event_source"),
            sa.UniqueConstraint("source_system", "source_message_id", name="uq_uav_track_event_message"),
        )
        op.create_index("ix_uav_track_events_inter_id", "uav_track_events", ["inter_id"])
        op.create_index("ix_uav_track_events_track_id", "uav_track_events", ["track_id"])
        op.create_index("ix_uav_track_events_ended_at", "uav_track_events", ["ended_at"])

    if "uav_track_points" not in existing:
        op.create_table(
            "uav_track_points",
            sa.Column("id", sa.String(80), nullable=False),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("track_event_id", sa.String(80), nullable=False),
            sa.Column("inter_id", sa.String(100), nullable=False),
            sa.Column("track_id", sa.String(100), nullable=False),
            sa.Column("point_seq", sa.Integer(), nullable=False),
            sa.Column("pixel_x", sa.Float(), nullable=True),
            sa.Column("pixel_y", sa.Float(), nullable=True),
            sa.Column("world_x_m", sa.Float(), nullable=True),
            sa.Column("world_y_m", sa.Float(), nullable=True),
            *_fact_columns(),
            sa.PrimaryKeyConstraint("id", "observed_at"),
            sa.CheckConstraint("source_system = 'uav_traffic_analyzer_ai'", name="ck_uav_track_point_source"),
            sa.UniqueConstraint(
                "observed_at", "source_system", "source_message_id", "point_seq",
                name="uq_uav_track_point_message_seq",
            ),
        )
        op.create_index("ix_uav_track_points_track_event_id", "uav_track_points", ["track_event_id"])
        op.create_index("ix_uav_track_points_inter_id", "uav_track_points", ["inter_id"])
        op.create_index("ix_uav_track_points_track_id", "uav_track_points", ["track_id"])

    if "uav_conflict_events" not in existing:
        op.create_table(
            "uav_conflict_events",
            sa.Column("id", sa.String(80), nullable=False),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("inter_id", sa.String(100), nullable=False),
            sa.Column("road_data_version", sa.String(100), nullable=True),
            sa.Column("motor_id", sa.String(100), nullable=True),
            sa.Column("non_motor_id", sa.String(100), nullable=True),
            sa.Column("severity", sa.String(24), nullable=True),
            sa.Column("ttc_sec", sa.Float(), nullable=True),
            sa.Column("pet_sec", sa.Float(), nullable=True),
            sa.Column("distance_m", sa.Float(), nullable=True),
            sa.Column("conflict_scene", sa.String(120), nullable=True),
            sa.Column("prediction_type", sa.String(80), nullable=True),
            sa.Column("conflict_angle_deg", sa.Float(), nullable=True),
            sa.Column("risk_score", sa.Float(), nullable=True),
            sa.Column("evidence", sa.JSON(), nullable=True),
            sa.Column("motor_position_m", sa.JSON(), nullable=True),
            sa.Column("non_motor_position_m", sa.JSON(), nullable=True),
            sa.Column("world_anchor_lat_lon", sa.JSON(), nullable=True),
            *_fact_columns(),
            sa.PrimaryKeyConstraint("id", "occurred_at"),
            sa.CheckConstraint("source_system = 'uav_traffic_analyzer_ai'", name="ck_uav_conflict_event_source"),
            sa.UniqueConstraint(
                "occurred_at", "source_system", "source_message_id",
                name="uq_uav_conflict_event_message",
            ),
        )
        op.create_index("ix_uav_conflict_events_inter_id", "uav_conflict_events", ["inter_id"])
        op.create_index("ix_uav_conflict_events_inter_time", "uav_conflict_events", ["inter_id", "occurred_at"])

    if "uav_telemetry_metrics" not in existing:
        op.create_table(
            "uav_telemetry_metrics",
            sa.Column("id", sa.String(80), nullable=False),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("drone_id", sa.String(100), nullable=False),
            sa.Column("mission_id", sa.String(80), nullable=True),
            sa.Column("pipeline_id", sa.String(80), nullable=True),
            sa.Column("latitude", sa.Float(), nullable=True),
            sa.Column("longitude", sa.Float(), nullable=True),
            sa.Column("altitude_m", sa.Float(), nullable=True),
            sa.Column("relative_altitude_m", sa.Float(), nullable=True),
            sa.Column("speed_ms", sa.Float(), nullable=True),
            sa.Column("heading_deg", sa.Float(), nullable=True),
            sa.Column("battery_pct", sa.Float(), nullable=True),
            sa.Column("pitch_deg", sa.Float(), nullable=True),
            sa.Column("roll_deg", sa.Float(), nullable=True),
            sa.Column("gimbal_pitch_deg", sa.Float(), nullable=True),
            sa.Column("gimbal_yaw_deg", sa.Float(), nullable=True),
            sa.Column("is_hovering", sa.Boolean(), nullable=True),
            sa.Column("positioning_quality", sa.String(32), nullable=True),
            *_fact_columns(include_drone=False),
            sa.PrimaryKeyConstraint("id", "observed_at"),
            sa.CheckConstraint("source_system = 'uav_traffic_analyzer_ai'", name="ck_uav_telemetry_metric_source"),
            sa.UniqueConstraint(
                "observed_at", "source_system", "source_message_id",
                name="uq_uav_telemetry_metric_message",
            ),
        )
        op.create_index("ix_uav_telemetry_metrics_drone_id", "uav_telemetry_metrics", ["drone_id"])
        op.create_index("ix_uav_telemetry_metrics_drone_time", "uav_telemetry_metrics", ["drone_id", "observed_at"])

    if "uav_system_metrics" not in existing:
        op.create_table(
            "uav_system_metrics",
            sa.Column("id", sa.String(80), nullable=False),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("instance_id", sa.String(120), nullable=False),
            sa.Column("metric_name", sa.String(120), nullable=False),
            sa.Column("metric_value", sa.Float(), nullable=False),
            sa.Column("unit", sa.String(40), nullable=True),
            sa.Column("labels", sa.JSON(), nullable=False),
            *_fact_columns(),
            sa.PrimaryKeyConstraint("id", "observed_at"),
            sa.CheckConstraint("source_system = 'uav_traffic_analyzer_ai'", name="ck_uav_system_metric_source"),
            sa.UniqueConstraint(
                "observed_at", "source_system", "source_message_id", "metric_name",
                name="uq_uav_system_metric_message_name",
            ),
        )
        op.create_index("ix_uav_system_metrics_instance_id", "uav_system_metrics", ["instance_id"])
        op.create_index("ix_uav_system_metrics_name_time", "uav_system_metrics", ["metric_name", "observed_at"])


def _upgrade_inbox() -> None:
    columns = _column_names("uav_message_inbox")
    if "message_id" not in columns:
        op.add_column("uav_message_inbox", sa.Column("message_id", sa.String(160), nullable=True))
        op.execute("UPDATE uav_message_inbox SET message_id = id WHERE message_id IS NULL")
        op.alter_column("uav_message_inbox", "message_id", nullable=False)
        op.create_unique_constraint(
            "uq_uav_inbox_source_message", "uav_message_inbox", ["source_system", "message_id"]
        )
    if "fact_references" not in columns:
        op.add_column(
            "uav_message_inbox",
            sa.Column("fact_references", sa.JSON(), server_default=sa.text("'[]'::json"), nullable=False),
        )
    if "first_seen_at" not in columns:
        op.add_column(
            "uav_message_inbox",
            sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )


def _enable_timescale_if_available() -> None:
    bind = op.get_bind()
    available = bind.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM pg_available_extensions WHERE name='timescaledb')")
    ).scalar()
    if not available:
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
    for table, column in (
        ("uav_traffic_metrics", "observed_at"),
        ("uav_system_metrics", "observed_at"),
        ("uav_telemetry_metrics", "observed_at"),
        ("uav_track_points", "observed_at"),
        ("uav_conflict_events", "occurred_at"),
    ):
        op.execute(
            f"SELECT create_hypertable('{table}', by_range('{column}'), "
            "if_not_exists => TRUE, migrate_data => TRUE)"
        )


def upgrade() -> None:
    _create_tables()
    _upgrade_inbox()
    _enable_timescale_if_available()


def downgrade() -> None:
    for table in (
        "uav_system_metrics",
        "uav_telemetry_metrics",
        "uav_conflict_events",
        "uav_track_points",
        "uav_track_events",
        "uav_traffic_metrics",
    ):
        if table in _table_names():
            op.drop_table(table)
    columns = _column_names("uav_message_inbox")
    if "first_seen_at" in columns:
        op.drop_column("uav_message_inbox", "first_seen_at")
    if "fact_references" in columns:
        op.drop_column("uav_message_inbox", "fact_references")
    if "message_id" in columns:
        op.drop_constraint("uq_uav_inbox_source_message", "uav_message_inbox", type_="unique")
        op.drop_column("uav_message_inbox", "message_id")
