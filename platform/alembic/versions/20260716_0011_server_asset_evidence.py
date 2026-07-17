"""Reference allowlisted server assets without copying original media.

Revision ID: 20260716_0011
Revises: 20260715_0010
"""

import sqlalchemy as sa
from alembic import op


revision = "20260716_0011"
down_revision = "20260715_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    evidence_columns = {column["name"] for column in inspector.get_columns("uav_evidence_items")}
    if "storage_backend" not in evidence_columns:
        op.add_column(
            "uav_evidence_items",
            sa.Column("storage_backend", sa.String(length=24), nullable=False, server_default="managed"),
        )
    batch_columns = {column["name"] for column in inspector.get_columns("uav_capture_batches")}
    if "source_profile_id" not in batch_columns:
        op.add_column("uav_capture_batches", sa.Column("source_profile_id", sa.String(length=40)))
        op.create_index("ix_uav_capture_batches_source_profile_id", "uav_capture_batches", ["source_profile_id"])
    tables = set(inspector.get_table_names())
    if "uav_lane_annotation_tasks" not in tables:
        op.create_table(
            "uav_lane_annotation_tasks",
            sa.Column("id", sa.String(length=100), primary_key=True),
            sa.Column("inter_id", sa.String(length=100), nullable=False),
            sa.Column("road_data_version", sa.String(length=100), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
            sa.Column("image_path", sa.String(length=500)),
            sa.Column("annotation", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("confirmed_by", sa.Integer(), sa.ForeignKey("uav_users.id")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_uav_lane_annotation_tasks_inter_id", "uav_lane_annotation_tasks", ["inter_id"])
        op.create_index("ix_uav_lane_annotation_tasks_status", "uav_lane_annotation_tasks", ["status"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "uav_lane_annotation_tasks" in inspector.get_table_names():
        op.drop_table("uav_lane_annotation_tasks")
    batch_columns = {column["name"] for column in inspector.get_columns("uav_capture_batches")}
    if "source_profile_id" in batch_columns:
        indexes = {item["name"] for item in inspector.get_indexes("uav_capture_batches")}
        if "ix_uav_capture_batches_source_profile_id" in indexes:
            op.drop_index("ix_uav_capture_batches_source_profile_id", table_name="uav_capture_batches")
        op.drop_column("uav_capture_batches", "source_profile_id")
    evidence_columns = {column["name"] for column in inspector.get_columns("uav_evidence_items")}
    if "storage_backend" in evidence_columns:
        op.drop_column("uav_evidence_items", "storage_backend")
