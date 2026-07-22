"""Establish the GCJ-02 channelized-map rebuild baseline.

Revision ID: 20260721_0016
Revises: 20260721_0015
"""

import sqlalchemy as sa

from alembic import op


revision = "20260721_0016"
down_revision = "20260721_0015"
branch_labels = None
depends_on = None


def _columns(inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    op.create_table(
        "uav_channelized_map_versions",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("inter_id", sa.String(100), nullable=False),
        sa.Column("road_data_version", sa.String(100), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("coordinate_system", sa.String(16), nullable=False, server_default="GCJ02"),
        sa.Column("coordinate_transform_version", sa.String(80), nullable=False),
        sa.Column("anchor_gcj02", sa.JSON(), nullable=False),
        sa.Column("geometry_gcj02", sa.JSON(), nullable=False),
        sa.Column("geometry_enu_m", sa.JSON(), nullable=False),
        sa.Column("topology", sa.JSON(), nullable=False),
        sa.Column("quality", sa.JSON(), nullable=False),
        sa.Column("source_checksum", sa.String(64), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("uav_users.id"), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("inter_id", "version_no", name="uq_uav_channelized_map_inter_version"),
        sa.CheckConstraint(
            "status IN ('draft','candidate','link_verified','lane_verified','retired')",
            name="ck_uav_channelized_map_status",
        ),
        sa.CheckConstraint("coordinate_system = 'GCJ02'", name="ck_uav_channelized_map_coordinate_system"),
    )
    op.create_index("ix_uav_channelized_map_versions_inter_id", "uav_channelized_map_versions", ["inter_id"])
    op.create_index("ix_uav_channelized_map_versions_road_data_version", "uav_channelized_map_versions", ["road_data_version"])
    op.create_index("ix_uav_channelized_map_versions_status", "uav_channelized_map_versions", ["status"])

    op.create_table(
        "uav_visual_registrations",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("map_version_id", sa.String(40), sa.ForeignKey("uav_channelized_map_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_image_path", sa.String(500), nullable=False),
        sa.Column("orthophoto_path", sa.String(500), nullable=True),
        sa.Column("control_points", sa.JSON(), nullable=False),
        sa.Column("homography_pixel_to_enu", sa.JSON(), nullable=True),
        sa.Column("residuals", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("uav_users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('draft','registered','verified','rejected')", name="ck_uav_visual_registration_status"),
    )
    op.create_index("ix_uav_visual_registrations_map_version_id", "uav_visual_registrations", ["map_version_id"])

    inspector = sa.inspect(op.get_bind())
    binding_columns = _columns(inspector, "uav_visual_lane_bindings")
    for column in (
        sa.Column("map_version_id", sa.String(40), sa.ForeignKey("uav_channelized_map_versions.id", ondelete="CASCADE"), nullable=True),
        sa.Column("geometry_source", sa.String(32), nullable=False, server_default="link_offset_derived"),
        sa.Column("geometry_gcj02", sa.JSON(), nullable=True),
        sa.Column("geometry_enu_m", sa.JSON(), nullable=True),
        sa.Column("match_confidence", sa.Float(), nullable=True),
    ):
        if column.name not in binding_columns:
            op.add_column("uav_visual_lane_bindings", column)
    constraints = {item["name"] for item in inspector.get_unique_constraints("uav_visual_lane_bindings")}
    if "uq_uav_visual_binding_inter_version_lane" in constraints:
        op.drop_constraint("uq_uav_visual_binding_inter_version_lane", "uav_visual_lane_bindings", type_="unique")
    op.create_unique_constraint("uq_uav_visual_binding_map_lane", "uav_visual_lane_bindings", ["map_version_id", "local_lane_id"])
    op.create_check_constraint(
        "ck_uav_visual_binding_geometry_source",
        "uav_visual_lane_bindings",
        "geometry_source IN ('link_offset_derived','imagery_fitted','manual_override')",
    )
    op.create_index("ix_uav_visual_lane_bindings_map_version_id", "uav_visual_lane_bindings", ["map_version_id"])
    if "roads_json" in binding_columns:
        op.drop_column("uav_visual_lane_bindings", "roads_json")
    op.add_column("uav_lane_annotation_tasks", sa.Column("map_version_id", sa.String(40), nullable=True))
    op.create_foreign_key(
        "fk_uav_lane_annotation_tasks_map_version",
        "uav_lane_annotation_tasks",
        "uav_channelized_map_versions",
        ["map_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_uav_lane_annotation_tasks_map_version_id", "uav_lane_annotation_tasks", ["map_version_id"])

    _replace_spatial_columns()


def _replace_spatial_columns() -> None:
    inspector = sa.inspect(op.get_bind())
    replacements = {
        "uav_track_events": (
            (
                sa.Column("trajectory_enu_m", sa.JSON(), nullable=True),
                sa.Column("trajectory_gcj02", sa.JSON(), nullable=True),
                sa.Column("entry_point_enu_m", sa.JSON(), nullable=True),
                sa.Column("exit_point_enu_m", sa.JSON(), nullable=True),
                sa.Column("anchor_gcj02", sa.JSON(), nullable=True),
                sa.Column("map_version_id", sa.String(40), nullable=True),
                sa.Column("matched_lane_key", sa.String(100), nullable=True),
                sa.Column("source_lane_id", sa.String(100), nullable=True),
                sa.Column("matched_link_id", sa.String(100), nullable=True),
                sa.Column("movement_key", sa.String(120), nullable=True),
                sa.Column("map_match_confidence", sa.Float(), nullable=True),
            ),
            ("trajectory_world_m", "entry_point_m", "exit_point_m", "world_anchor_lat_lon"),
        ),
        "uav_track_points": (
            (
                sa.Column("enu_x_m", sa.Float(), nullable=True),
                sa.Column("enu_y_m", sa.Float(), nullable=True),
                sa.Column("position_gcj02", sa.JSON(), nullable=True),
            ),
            ("world_x_m", "world_y_m"),
        ),
        "uav_conflict_events": (
            (
                sa.Column("motor_position_enu_m", sa.JSON(), nullable=True),
                sa.Column("non_motor_position_enu_m", sa.JSON(), nullable=True),
                sa.Column("conflict_position_gcj02", sa.JSON(), nullable=True),
                sa.Column("anchor_gcj02", sa.JSON(), nullable=True),
            ),
            ("motor_position_m", "non_motor_position_m", "world_anchor_lat_lon"),
        ),
        "uav_telemetry_metrics": (
            (
                sa.Column("position_gcj02", sa.JSON(), nullable=True),
                sa.Column("coordinate_transform_version", sa.String(80), nullable=True),
            ),
            ("latitude", "longitude"),
        ),
    }
    for table, (additions, removals) in replacements.items():
        columns = _columns(inspector, table)
        for column in additions:
            if column.name not in columns:
                op.add_column(table, column)
        for name in removals:
            if name in columns:
                op.drop_column(table, name)
    op.create_index("ix_uav_track_events_map_version_id", "uav_track_events", ["map_version_id"])


def downgrade() -> None:
    raise RuntimeError("GCJ-02 clean rebuild is intentionally irreversible")
