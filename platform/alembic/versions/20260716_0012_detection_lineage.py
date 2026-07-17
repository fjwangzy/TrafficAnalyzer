"""Persist detector mission, pipeline, and source lineage on canonical facts.

Revision ID: 20260716_0012
Revises: 20260716_0011
"""

import sqlalchemy as sa
from alembic import op


revision = "20260716_0012"
down_revision = "20260716_0011"
branch_labels = None
depends_on = None


TABLE_COLUMNS = {
    "uav_traffic_metrics": ("mission_id", "pipeline_id", "source_profile_id"),
    "uav_track_events": ("mission_id", "pipeline_id", "source_profile_id"),
    "uav_track_points": ("mission_id", "pipeline_id", "source_profile_id"),
    "uav_conflict_events": ("mission_id", "pipeline_id", "source_profile_id"),
    "uav_telemetry_metrics": ("source_profile_id",),
}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table, columns in TABLE_COLUMNS.items():
        existing = {column["name"] for column in inspector.get_columns(table)}
        for column in columns:
            if column in existing:
                continue
            op.add_column(table, sa.Column(column, sa.String(length=80)))
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table, columns in reversed(tuple(TABLE_COLUMNS.items())):
        existing = {column["name"] for column in inspector.get_columns(table)}
        indexes = {item["name"] for item in inspector.get_indexes(table)}
        for column in reversed(columns):
            if column not in existing:
                continue
            index_name = f"ix_{table}_{column}"
            if index_name in indexes:
                op.drop_index(index_name, table_name=table)
            op.drop_column(table, column)
