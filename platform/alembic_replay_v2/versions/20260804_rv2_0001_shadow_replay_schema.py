"""Create isolated replay-v2 shadow facts.

Revision ID: 20260804_rv2_0001
Revises: None
"""

from app.models.replay_v2 import REPLAY_V2_TABLES

from alembic import op


revision = "20260804_rv2_0001"
down_revision = None
branch_labels = ("replay_v2",)
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    for table in REPLAY_V2_TABLES:
        table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    raise RuntimeError("replay-v2 shadow facts require explicit approved cleanup")
