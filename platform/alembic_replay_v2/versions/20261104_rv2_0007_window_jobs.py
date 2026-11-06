"""Paged incremental aggregation, relation application and final manifest.

Old empty-database migrations build selected tables from the current model;
column/index checks also support that path without altering historical revisions.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261104_rv2_0007"
down_revision = "20261104_rv2_0006"
branch_labels = depends_on = None


def add_column(table, column):
    if column.name not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}:
        op.add_column(table, column)


def add_index(name, table, columns):
    if name not in {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}:
        op.create_index(name, table, columns)


def upgrade():
    add_column(
        "uav_replay_v2_missions", sa.Column("expected_relation_count", sa.Integer(), nullable=True)
    )
    add_column(
        "uav_replay_v2_missions", sa.Column("segment_manifest_hash", sa.String(64), nullable=True)
    )
    add_column(
        "uav_replay_v2_track_events", sa.Column("segment_digest", sa.String(64), nullable=True)
    )
    add_column(
        "uav_replay_v2_track_relations",
        sa.Column("state", sa.String(24), nullable=False, server_default="pending"),
    )
    add_index("ix_uav_replay_v2_track_relations_state", "uav_replay_v2_track_relations", ["state"])
    sa.Table(
        "uav_replay_v2_track_groups",
        sa.MetaData(),
        sa.Column("mission_id", sa.String(80), primary_key=True),
        sa.Column("track_id", sa.String(100), primary_key=True),
        sa.Column("root_track_id", sa.String(100), nullable=False),
    ).create(op.get_bind(), checkfirst=True)
    add_index(
        "ix_uav_replay_v2_track_groups_root_track_id",
        "uav_replay_v2_track_groups",
        ["root_track_id"],
    )
    sa.Table(
        "uav_replay_v2_track_windows",
        sa.MetaData(),
        sa.Column("mission_id", sa.String(80), primary_key=True),
        sa.Column("track_id", sa.String(100), primary_key=True),
        sa.Column("window_start", sa.DateTime(timezone=True), primary_key=True),
    ).create(op.get_bind(), checkfirst=True)
    add_index(
        "ix_uav_track_window_lookup",
        "uav_replay_v2_track_windows",
        ["mission_id", "window_start", "track_id"],
    )
    sa.Table(
        "uav_replay_v2_dirty_windows",
        sa.MetaData(),
        sa.Column("mission_id", sa.String(80), primary_key=True),
        sa.Column("window_start", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("processed_generation", sa.BigInteger(), nullable=False),
        sa.Column("dirty", sa.Integer(), nullable=False),
    ).create(op.get_bind(), checkfirst=True)
    add_index("ix_uav_replay_v2_dirty_windows_dirty", "uav_replay_v2_dirty_windows", ["dirty"])


def downgrade():
    raise RuntimeError("window jobs and incremental manifests require a compatible consumer")
