"""Add S5 road context, S6 delivery ledger, and S9 mission persistence.

Revision ID: 20260715_0003
Revises: 20260714_0002
"""

from alembic import op
import sqlalchemy as sa


revision = "20260715_0003"
down_revision = "20260714_0002"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    # The historical baseline migration creates current metadata on a brand-new
    # database. In that path every 0003 object already exists; advancing the
    # revision is sufficient. Existing road9 databases at 0002 do not have the
    # S9 tables and therefore execute the explicit forward migration below.
    if "uav_drones" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "uav_road_context_snapshots",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("inter_id", sa.String(100), nullable=False),
        sa.Column("road_data_version", sa.String(100), nullable=False),
        sa.Column("source", sa.String(80), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("coordinate_reference", sa.JSON(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("quality_status", sa.String(24), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("inter_id", "road_data_version", name="uq_uav_road_context_inter_version"),
    )
    op.create_index("ix_uav_road_context_snapshots_inter_id", "uav_road_context_snapshots", ["inter_id"])

    op.create_table(
        "uav_visual_lane_bindings",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("inter_id", sa.String(100), nullable=False),
        sa.Column("road_data_version", sa.String(100), nullable=False),
        sa.Column("local_lane_id", sa.String(100), nullable=False),
        sa.Column("canonical_link_id", sa.String(100), nullable=True),
        sa.Column("canonical_lane_id", sa.String(100), nullable=True),
        sa.Column("roads_json", sa.String(500), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("confirmed_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["confirmed_by"], ["uav_users.id"]),
        sa.UniqueConstraint(
            "inter_id", "road_data_version", "local_lane_id",
            name="uq_uav_visual_binding_inter_version_lane",
        ),
    )
    op.create_index("ix_uav_visual_lane_bindings_inter_id", "uav_visual_lane_bindings", ["inter_id"])

    op.create_table(
        "uav_device_intersection_bindings",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("device_id", sa.String(100), nullable=False),
        sa.Column("inter_id", sa.String(100), nullable=False),
        sa.Column("road_data_version", sa.String(100), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_uav_device_intersection_bindings_device_id", "uav_device_intersection_bindings", ["device_id"])
    op.create_index("ix_uav_device_intersection_bindings_inter_id", "uav_device_intersection_bindings", ["inter_id"])

    op.add_column("uav_ai_events", sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("uav_ai_events", sa.Column("inter_id", sa.String(100), nullable=True))
    op.add_column("uav_ai_events", sa.Column("road_data_version", sa.String(100), nullable=True))
    op.add_column("uav_ai_events", sa.Column("quality_status", sa.String(24), server_default="unverified", nullable=False))
    op.add_column("uav_ai_events", sa.Column("payload_hash", sa.String(64), nullable=True))
    op.add_column("uav_ai_events", sa.Column("delivery_status", sa.String(24), server_default="not_queued", nullable=False))
    op.add_column("uav_event_outbox", sa.Column("source_system", sa.String(80), server_default="uav_traffic_analyzer_ai", nullable=False))
    op.add_column("uav_event_outbox", sa.Column("message_id", sa.String(80), nullable=True))
    op.add_column("uav_event_outbox", sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("uav_event_outbox", sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_uav_event_outbox_next_retry_at", "uav_event_outbox", ["next_retry_at"])
    op.add_column("uav_event_delivery_attempts", sa.Column("platform_event_id", sa.String(120), nullable=True))
    op.add_column("uav_event_delivery_attempts", sa.Column("receipt_payload", sa.JSON(), nullable=True))
    op.add_column("uav_dead_letters", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "uav_event_feedback",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("source_system", sa.String(80), nullable=False),
        sa.Column("source_event_id", sa.String(80), nullable=False),
        sa.Column("platform_event_id", sa.String(120), nullable=True),
        sa.Column("feedback_version", sa.Integer(), nullable=False),
        sa.Column("result", sa.String(40), nullable=False),
        sa.Column("reason_code", sa.String(80), nullable=True),
        sa.Column("actor_ref", sa.String(120), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "source_system", "source_event_id", "feedback_version",
            name="uq_uav_feedback_source_version",
        ),
    )
    op.create_table(
        "uav_message_inbox",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("source_system", sa.String(80), nullable=False),
        sa.Column("topic", sa.String(160), nullable=False),
        sa.Column("partition", sa.Integer(), nullable=False),
        sa.Column("offset", sa.Integer(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("topic", "partition", "offset", name="uq_uav_inbox_topic_partition_offset"),
    )

    op.create_table(
        "uav_drones",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("model", sa.String(120), nullable=True),
        sa.Column("serial_number", sa.String(160), nullable=True, unique=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("default_inter_id", sa.String(100), nullable=True),
        sa.Column("default_video_source_id", sa.String(40), nullable=True),
        sa.Column("default_telemetry_source_id", sa.String(40), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        *_timestamps(),
    )
    op.create_table(
        "uav_video_sources",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("profile_id", sa.String(40), nullable=False, unique=True),
        sa.Column("drone_id", sa.String(40), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("source_type", sa.String(16), nullable=False),
        sa.Column("location", sa.Text(), nullable=False),
        sa.Column("credential_ref", sa.String(300), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("validation_status", sa.String(24), nullable=False),
        sa.Column("validation_error_code", sa.String(80), nullable=True),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["drone_id"], ["uav_drones.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_uav_video_sources_profile_id", "uav_video_sources", ["profile_id"])
    op.create_index("ix_uav_video_sources_drone_id", "uav_video_sources", ["drone_id"])
    op.create_table(
        "uav_telemetry_sources",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("profile_id", sa.String(40), nullable=False, unique=True),
        sa.Column("drone_id", sa.String(40), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("source_type", sa.String(16), nullable=False),
        sa.Column("location", sa.Text(), nullable=False),
        sa.Column("credential_ref", sa.String(300), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("validation_status", sa.String(24), nullable=False),
        sa.Column("validation_error_code", sa.String(80), nullable=True),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["drone_id"], ["uav_drones.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_uav_telemetry_sources_profile_id", "uav_telemetry_sources", ["profile_id"])
    op.create_index("ix_uav_telemetry_sources_drone_id", "uav_telemetry_sources", ["drone_id"])
    op.create_table(
        "uav_flight_plans",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("drone_id", sa.String(40), nullable=False),
        sa.Column("video_source_id", sa.String(40), nullable=False),
        sa.Column("telemetry_source_id", sa.String(40), nullable=False),
        sa.Column("inter_id", sa.String(100), nullable=False),
        sa.Column("road_data_version", sa.String(100), nullable=False),
        sa.Column("ai_mode", sa.String(40), nullable=False),
        sa.Column("schedule_type", sa.String(16), nullable=False),
        sa.Column("schedule", sa.JSON(), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["drone_id"], ["uav_drones.id"]),
        sa.ForeignKeyConstraint(["video_source_id"], ["uav_video_sources.id"]),
        sa.ForeignKeyConstraint(["telemetry_source_id"], ["uav_telemetry_sources.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["uav_users.id"]),
    )
    op.create_index("ix_uav_flight_plans_drone_id", "uav_flight_plans", ["drone_id"])
    op.create_index("ix_uav_flight_plans_inter_id", "uav_flight_plans", ["inter_id"])
    op.create_index("ix_uav_flight_plans_state", "uav_flight_plans", ["state"])
    op.create_table(
        "uav_missions",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("flight_plan_id", sa.String(40), nullable=True),
        sa.Column("parent_mission_id", sa.String(40), nullable=True),
        sa.Column("retry_index", sa.Integer(), nullable=False),
        sa.Column("trigger_type", sa.String(24), nullable=False),
        sa.Column("drone_id", sa.String(40), nullable=False),
        sa.Column("video_source_id", sa.String(40), nullable=True),
        sa.Column("telemetry_source_id", sa.String(40), nullable=True),
        sa.Column("inter_id", sa.String(100), nullable=False),
        sa.Column("road_data_version", sa.String(100), nullable=False),
        sa.Column("scheduled_start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scheduled_end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actual_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("reason_code", sa.String(80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("pipeline_id", sa.String(40), nullable=True),
        sa.Column("context_snapshot", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["flight_plan_id"], ["uav_flight_plans.id"]),
        sa.ForeignKeyConstraint(["parent_mission_id"], ["uav_missions.id"]),
        sa.ForeignKeyConstraint(["drone_id"], ["uav_drones.id"]),
        sa.ForeignKeyConstraint(["video_source_id"], ["uav_video_sources.id"]),
        sa.ForeignKeyConstraint(["telemetry_source_id"], ["uav_telemetry_sources.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["uav_users.id"]),
        sa.UniqueConstraint("flight_plan_id", "scheduled_start_at", name="uq_uav_mission_plan_occurrence"),
    )
    op.create_index("ix_uav_missions_flight_plan_id", "uav_missions", ["flight_plan_id"])
    op.create_index("ix_uav_missions_drone_id", "uav_missions", ["drone_id"])
    op.create_index("ix_uav_missions_inter_id", "uav_missions", ["inter_id"])
    op.create_index("ix_uav_missions_scheduled_start_at", "uav_missions", ["scheduled_start_at"])
    op.create_index("ix_uav_missions_status", "uav_missions", ["status"])
    op.create_index("ix_uav_missions_pipeline_id", "uav_missions", ["pipeline_id"])
    op.create_table(
        "uav_pipelines",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("mission_id", sa.String(40), nullable=False, unique=True),
        sa.Column("desired_status", sa.String(24), nullable=False),
        sa.Column("observed_status", sa.String(24), nullable=False),
        sa.Column("topic_name", sa.String(120), nullable=False),
        sa.Column("camera_id", sa.Integer(), nullable=True),
        sa.Column("video_port", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["mission_id"], ["uav_missions.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("uav_pipelines")
    op.drop_table("uav_missions")
    op.drop_table("uav_flight_plans")
    op.drop_table("uav_telemetry_sources")
    op.drop_table("uav_video_sources")
    op.drop_table("uav_drones")
    op.drop_table("uav_message_inbox")
    op.drop_table("uav_event_feedback")
    op.drop_column("uav_dead_letters", "resolved_at")
    op.drop_column("uav_event_delivery_attempts", "receipt_payload")
    op.drop_column("uav_event_delivery_attempts", "platform_event_id")
    op.drop_index("ix_uav_event_outbox_next_retry_at", table_name="uav_event_outbox")
    op.drop_column("uav_event_outbox", "locked_at")
    op.drop_column("uav_event_outbox", "next_retry_at")
    op.drop_column("uav_event_outbox", "message_id")
    op.drop_column("uav_event_outbox", "source_system")
    op.drop_column("uav_ai_events", "delivery_status")
    op.drop_column("uav_ai_events", "payload_hash")
    op.drop_column("uav_ai_events", "quality_status")
    op.drop_column("uav_ai_events", "road_data_version")
    op.drop_column("uav_ai_events", "inter_id")
    op.drop_column("uav_ai_events", "occurred_at")
    op.drop_table("uav_device_intersection_bindings")
    op.drop_table("uav_visual_lane_bindings")
    op.drop_table("uav_road_context_snapshots")
