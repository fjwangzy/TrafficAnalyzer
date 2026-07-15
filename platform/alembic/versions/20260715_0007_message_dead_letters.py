"""Add durable quarantine for invalid inbound Kafka messages.

Revision ID: 20260715_0007
Revises: 20260715_0006
"""

from alembic import op
import sqlalchemy as sa


revision = "20260715_0007"
down_revision = "20260715_0006"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "uav_message_dead_letters" in _tables():
        return
    op.create_table(
        "uav_message_dead_letters",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("source_system", sa.String(80), nullable=False),
        sa.Column("message_id", sa.String(160), nullable=True),
        sa.Column("topic", sa.String(160), nullable=False),
        sa.Column("partition", sa.Integer(), nullable=False),
        sa.Column("offset", sa.BigInteger(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("reason_code", sa.String(80), nullable=False),
        sa.Column("reason_summary", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="quarantined"),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("topic", "partition", "offset", name="uq_uav_message_dlq_transport"),
    )
    op.create_index("ix_uav_message_dead_letters_status", "uav_message_dead_letters", ["status"])
    op.create_index(
        "ix_uav_message_dead_letters_source_message",
        "uav_message_dead_letters",
        ["source_system", "message_id"],
    )


def downgrade() -> None:
    if "uav_message_dead_letters" in _tables():
        op.drop_table("uav_message_dead_letters")
