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
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("uav_telemetry_sources")}
    if "config" not in columns:
        op.add_column(
            "uav_telemetry_sources",
            sa.Column("config", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        )


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("uav_telemetry_sources")}
    if "config" in columns:
        op.drop_column("uav_telemetry_sources", "config")
