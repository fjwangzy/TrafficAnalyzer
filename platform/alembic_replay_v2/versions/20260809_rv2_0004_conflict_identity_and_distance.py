"""Retain Replay V2 TCC identity and path-intersection facts.

Revision ID: 20260809_rv2_0004
Revises: 20260805_rv2_0003
"""

import sqlalchemy as sa
from alembic import op


revision = "20260809_rv2_0004"
down_revision = "20260805_rv2_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "uav_replay_v2_conflict_events",
        sa.Column("motor_track_id", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "uav_replay_v2_conflict_events",
        sa.Column("non_motor_track_id", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "uav_replay_v2_conflict_events",
        sa.Column("distance_m", sa.Float(), nullable=True),
    )
    op.add_column(
        "uav_replay_v2_conflict_events",
        sa.Column("conflict_scene", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    raise RuntimeError("replay-v2 conflict fact rollback requires explicit approved cleanup")
