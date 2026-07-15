"""Add durable technical review state to conflict facts.

Revision ID: 20260715_0005
Revises: 20260715_0004
"""

from alembic import op
import sqlalchemy as sa


revision = "20260715_0005"
down_revision = "20260715_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("uav_conflict_events")}
    if "review_status" not in columns:
        op.add_column(
            "uav_conflict_events",
            sa.Column("review_status", sa.String(24), server_default="pending", nullable=False),
        )
        op.add_column(
            "uav_conflict_events",
            sa.Column("review_revision", sa.Integer(), server_default="1", nullable=False),
        )
        op.add_column("uav_conflict_events", sa.Column("reviewed_by", sa.Integer(), nullable=True))
        op.add_column("uav_conflict_events", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
        op.add_column("uav_conflict_events", sa.Column("review_reason", sa.Text(), nullable=True))
        op.create_foreign_key(
            "fk_uav_conflict_events_reviewed_by_users",
            "uav_conflict_events", "uav_users", ["reviewed_by"], ["id"],
        )
        op.create_check_constraint(
            "ck_uav_conflict_review_status",
            "uav_conflict_events",
            "review_status IN ('pending','confirmed','rejected')",
        )


def downgrade() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("uav_conflict_events")}
    if "review_status" in columns:
        op.drop_constraint("ck_uav_conflict_review_status", "uav_conflict_events", type_="check")
        op.drop_constraint("fk_uav_conflict_events_reviewed_by_users", "uav_conflict_events", type_="foreignkey")
        for column in ("review_reason", "reviewed_at", "reviewed_by", "review_revision", "review_status"):
            op.drop_column("uav_conflict_events", column)

