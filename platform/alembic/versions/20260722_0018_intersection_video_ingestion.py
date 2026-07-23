"""Add stable intersection projects and video-ingestion workflow.

Revision ID: 20260722_0018
Revises: 20260721_0017
"""

import sqlalchemy as sa
from alembic import op


revision = "20260722_0018"
down_revision = "20260721_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "uav_intersection_projects",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("inter_id", sa.String(100), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("center_gcj02", sa.JSON(), nullable=True),
        sa.Column("stage", sa.String(24), nullable=False, server_default="discovered"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("uav_users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "stage IN ('discovered','road_matched','source_ready','keyframes_ready','drafting','checking','published','retired')",
            name="ck_uav_intersection_project_stage",
        ),
        sa.UniqueConstraint("inter_id", name="uq_uav_intersection_projects_inter_id"),
    )
    op.create_index("ix_uav_intersection_projects_inter_id", "uav_intersection_projects", ["inter_id"])
    op.create_index("ix_uav_intersection_projects_stage", "uav_intersection_projects", ["stage"])

    op.create_table(
        "uav_video_ingestion_jobs",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("project_id", sa.String(40), sa.ForeignKey("uav_intersection_projects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("mode", sa.String(24), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="uploaded"),
        sa.Column("source_profile_id", sa.String(40), sa.ForeignKey("uav_video_sources.profile_id", ondelete="SET NULL"), nullable=True),
        sa.Column("drone_id", sa.String(40), sa.ForeignKey("uav_drones.id"), nullable=True),
        sa.Column("video_location", sa.String(500), nullable=True),
        sa.Column("telemetry_location", sa.String(500), nullable=True),
        sa.Column("telemetry_type", sa.String(24), nullable=True),
        sa.Column("hover_evidence", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("candidate_intersections", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("uav_users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("mode IN ('video_first','project_first')", name="ck_uav_video_ingestion_mode"),
        sa.CheckConstraint(
            "status IN ('uploaded','parsing','hover_detected','candidates_ready','awaiting_confirmation','bound','failed')",
            name="ck_uav_video_ingestion_status",
        ),
    )
    op.create_index("ix_uav_video_ingestion_jobs_project_id", "uav_video_ingestion_jobs", ["project_id"])
    op.create_index("ix_uav_video_ingestion_jobs_status", "uav_video_ingestion_jobs", ["status"])
    op.create_index("ix_uav_video_ingestion_jobs_source_profile_id", "uav_video_ingestion_jobs", ["source_profile_id"])
    op.create_index("ix_uav_video_ingestion_jobs_drone_id", "uav_video_ingestion_jobs", ["drone_id"])

    op.create_table(
        "uav_source_intersection_bindings",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("source_profile_id", sa.String(40), sa.ForeignKey("uav_video_sources.profile_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("project_id", sa.String(40), sa.ForeignKey("uav_intersection_projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("inter_id", sa.String(100), nullable=True),
        sa.Column("start_offset_sec", sa.Float(), nullable=False, server_default="0"),
        sa.Column("end_offset_sec", sa.Float(), nullable=True),
        sa.Column("binding_quality", sa.String(32), nullable=False),
        sa.Column("coordinate_evidence", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("confirmed_by", sa.Integer(), sa.ForeignKey("uav_users.id"), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "binding_quality IN ('auto_high_confidence','admin_confirmed','manual_unverified','rejected')",
            name="ck_uav_source_intersection_binding_quality",
        ),
        sa.UniqueConstraint("source_profile_id", "project_id", "start_offset_sec", "end_offset_sec", name="uq_uav_source_intersection_binding_segment"),
    )
    op.create_index("ix_uav_source_intersection_bindings_source", "uav_source_intersection_bindings", ["source_profile_id"])
    op.create_index("ix_uav_source_intersection_bindings_project", "uav_source_intersection_bindings", ["project_id"])
    op.create_index("ix_uav_source_intersection_bindings_inter", "uav_source_intersection_bindings", ["inter_id"])

    op.create_table(
        "uav_calibration_review_records",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("map_version_id", sa.String(40), sa.ForeignKey("uav_channelized_map_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("result", sa.String(24), nullable=False),
        sa.Column("issues", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("checklist", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("uav_users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("result IN ('submitted','approved','rejected')", name="ck_uav_calibration_review_result"),
    )
    op.create_index("ix_uav_calibration_review_records_map", "uav_calibration_review_records", ["map_version_id"])

    # Backfill one workflow project per latest known RoadContext inter_id.
    op.execute(
        """
        INSERT INTO uav_intersection_projects (id, inter_id, name, center_gcj02, stage, revision)
        SELECT 'IPR-' || substr(md5(latest.inter_id), 1, 24), latest.inter_id,
               COALESCE(latest.payload->'intersection'->>'name', latest.inter_id),
               latest.payload->'intersection'->'center_gcj02',
               CASE WHEN latest.quality_status = 'verified' THEN 'road_matched' ELSE 'discovered' END,
               1
        FROM (
            SELECT DISTINCT ON (inter_id) inter_id, payload, quality_status
            FROM uav_road_context_snapshots
            ORDER BY inter_id, created_at DESC
        ) AS latest
        ON CONFLICT (inter_id) DO NOTHING
        """
    )


def downgrade() -> None:
    raise RuntimeError("intersection project and ingestion audit data are intentionally irreversible")
