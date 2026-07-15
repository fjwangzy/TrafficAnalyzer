"""Persist local telemetry replay synchronization configuration.

Revision ID: 20260715_0010
Revises: 20260715_0009
"""

import sqlalchemy as sa
from alembic import op


revision = "20260715_0010"
down_revision = "20260715_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "uav_telemetry_sources",
        sa.Column("config", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
    )


def downgrade() -> None:
    op.drop_column("uav_telemetry_sources", "config")
