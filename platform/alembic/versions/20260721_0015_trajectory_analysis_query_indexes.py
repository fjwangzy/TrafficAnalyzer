"""Add trajectory analysis source and lineage indexes.

Revision ID: 20260721_0015
Revises: 20260721_0014
"""

import sqlalchemy as sa

from alembic import op

revision = "20260721_0015"
down_revision = "20260721_0014"
branch_labels = None
depends_on = None


INDEXES = (
    (
        "ix_uav_track_events_analysis_source_window",
        ["inter_id", "source_profile_id", "ended_at"],
    ),
    (
        "ix_uav_track_events_analysis_lineage",
        ["mission_id", "pipeline_id", "track_id"],
    ),
)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    indexes = {index["name"] for index in inspector.get_indexes("uav_track_events")}
    for name, columns in INDEXES:
        if name not in indexes:
            op.create_index(name, "uav_track_events", columns)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    indexes = {index["name"] for index in inspector.get_indexes("uav_track_events")}
    for name, _ in reversed(INDEXES):
        if name in indexes:
            op.drop_index(name, table_name="uav_track_events")
