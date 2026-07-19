"""Add recoverable canonical-message dispatch state.

Revision ID: 20260717_0013
Revises: 20260716_0012
"""

from alembic import op
import sqlalchemy as sa


revision = "20260717_0013"
down_revision = "20260716_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("uav_message_inbox")}
    if "dispatch_status" not in columns:
        op.add_column(
            "uav_message_inbox",
            sa.Column("dispatch_status", sa.String(24), nullable=False, server_default="pending"),
        )
    if "dispatched_at" not in columns:
        op.add_column(
            "uav_message_inbox",
            sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "dispatch_attempts" not in columns:
        op.add_column(
            "uav_message_inbox",
            sa.Column("dispatch_attempts", sa.Integer(), nullable=False, server_default="0"),
        )
    if "last_dispatch_error" not in columns:
        op.add_column(
            "uav_message_inbox",
            sa.Column("last_dispatch_error", sa.Text(), nullable=True),
        )
    if "last_dispatch_attempt_at" not in columns:
        op.add_column(
            "uav_message_inbox",
            sa.Column("last_dispatch_attempt_at", sa.DateTime(timezone=True), nullable=True),
        )
    op.execute(
        "UPDATE uav_message_inbox "
        "SET dispatch_status='dispatched', dispatched_at=processed_at "
        "WHERE status='processed' AND dispatch_status='pending'"
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("uav_message_inbox")}
    if "last_dispatch_attempt_at" in columns:
        op.drop_column("uav_message_inbox", "last_dispatch_attempt_at")
    if "last_dispatch_error" in columns:
        op.drop_column("uav_message_inbox", "last_dispatch_error")
    if "dispatch_attempts" in columns:
        op.drop_column("uav_message_inbox", "dispatch_attempts")
    if "dispatched_at" in columns:
        op.drop_column("uav_message_inbox", "dispatched_at")
    if "dispatch_status" in columns:
        op.drop_column("uav_message_inbox", "dispatch_status")
