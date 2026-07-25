"""Add cruise tracking profiles, flight segments, and runtime quality lineage.

Revision ID: 20260723_0019
Revises: 20260722_0018
"""

import sqlalchemy as sa

from alembic import op

revision = "20260723_0019"
down_revision = "20260722_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "uav_flight_plans",
        sa.Column("tracking_profile", sa.String(32), nullable=True),
    )
    op.execute(
        "UPDATE uav_flight_plans SET tracking_profile = 'hover_only_legacy' "
        "WHERE tracking_profile IS NULL"
    )
    op.alter_column(
        "uav_flight_plans",
        "tracking_profile",
        nullable=False,
        server_default="hover_cruise_v1",
    )

    op.add_column(
        "uav_visual_registrations",
        sa.Column("registration_pose", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column(
        "uav_visual_registrations",
        sa.Column("camera_calibration", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column(
        "uav_visual_registrations",
        sa.Column("map_coverage_enu_m", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )

    op.add_column("uav_pipelines", sa.Column("flight_phase", sa.String(32), nullable=True))
    op.add_column("uav_pipelines", sa.Column("tracking_quality", sa.String(24), nullable=True))
    op.add_column(
        "uav_pipelines",
        sa.Column("formal_analytics_eligible", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "uav_pipelines",
        sa.Column("runtime_quality", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )

    op.create_table(
        "uav_flight_segments",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "source_profile_id",
            sa.String(40),
            sa.ForeignKey("uav_video_sources.profile_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "mission_id",
            sa.String(40),
            sa.ForeignKey("uav_missions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("start_offset_sec", sa.Float(), nullable=False),
        sa.Column("end_offset_sec", sa.Float(), nullable=False),
        sa.Column("phase", sa.String(32), nullable=False),
        sa.Column("quality_status", sa.String(24), nullable=False),
        sa.Column("classifier_version", sa.String(40), nullable=False),
        sa.Column("motion_statistics", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "map_version_id",
            sa.String(40),
            sa.ForeignKey("uav_channelized_map_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "phase IN ('hover_candidate','hover_verified','cruise_nadir','transition','unsupported_pose','telemetry_unavailable')",
            name="ck_uav_flight_segment_phase",
        ),
        sa.CheckConstraint(
            "quality_status IN ('verified','degraded','unverified')",
            name="ck_uav_flight_segment_quality",
        ),
    )
    op.create_index("ix_uav_flight_segments_source", "uav_flight_segments", ["source_profile_id"])
    op.create_index("ix_uav_flight_segments_mission", "uav_flight_segments", ["mission_id"])
    op.create_index("ix_uav_flight_segments_phase", "uav_flight_segments", ["phase"])
    op.create_index("ix_uav_flight_segments_map", "uav_flight_segments", ["map_version_id"])


def downgrade() -> None:
    raise RuntimeError("cruise tracking quality facts are intentionally irreversible")
