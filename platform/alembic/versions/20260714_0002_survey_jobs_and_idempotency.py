"""Add recoverable survey ingestion jobs and request idempotency.

Revision ID: 20260714_0002
Revises: 20260714_0001
"""

from alembic import op
import sqlalchemy as sa


revision = "20260714_0002"
down_revision = "20260714_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    evidence_uniques = {item["name"] for item in inspector.get_unique_constraints("uav_evidence_items")}
    if "uav_evidence_items_storage_key_key" in evidence_uniques:
        op.drop_constraint("uav_evidence_items_storage_key_key", "uav_evidence_items", type_="unique")
    evidence_indexes = {item["name"] for item in inspector.get_indexes("uav_evidence_items")}
    if "ix_uav_evidence_items_storage_key" not in evidence_indexes:
        op.create_index("ix_uav_evidence_items_storage_key", "uav_evidence_items", ["storage_key"])
    if "uav_capture_ingestion_jobs" not in inspector.get_table_names():
        op.create_table(
            "uav_capture_ingestion_jobs",
            sa.Column("id", sa.String(length=40), primary_key=True),
            sa.Column("task_id", sa.String(length=40), nullable=False),
            sa.Column("batch_id", sa.String(length=40), nullable=False, unique=True),
            sa.Column("status", sa.String(length=24), nullable=False),
            sa.Column("attempt_count", sa.Integer(), nullable=False),
            sa.Column("max_attempts", sa.Integer(), nullable=False),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["task_id"], ["uav_survey_tasks.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["batch_id"], ["uav_capture_batches.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_uav_capture_ingestion_jobs_task_id", "uav_capture_ingestion_jobs", ["task_id"])
        op.create_index("ix_uav_capture_ingestion_jobs_status", "uav_capture_ingestion_jobs", ["status"])
    audit_uniques = {item["name"] for item in inspector.get_unique_constraints("uav_audit_logs")}
    if "uq_uav_audit_action_request" not in audit_uniques:
        op.create_unique_constraint("uq_uav_audit_action_request", "uav_audit_logs", ["action", "request_id"])


def downgrade() -> None:
    raise RuntimeError("survey evidence and ingestion job history requires a reviewed forward migration")
