"""Incremental trajectory relationships and transactional ingest receipts."""

import sqlalchemy as sa

from alembic import op

revision = "20261104_rv2_0006"
down_revision = "20261019_rv2_0005"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "uav_replay_v2_track_chunks",
        sa.Column("logical_message_id", sa.String(160), primary_key=True),
        sa.Column("chunk_seq", sa.Integer(), primary_key=True),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "uav_replay_v2_ingest_receipts",
        sa.Column("message_id", sa.String(160), primary_key=True),
        sa.Column("message_hash", sa.String(64), nullable=False),
        sa.Column("deployment_id", sa.String(100), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_uav_replay_v2_ingest_receipts_status", "uav_replay_v2_ingest_receipts", ["status"]
    )
    op.create_table(
        "uav_replay_v2_track_relations",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("mission_id", sa.String(80), nullable=False),
        sa.Column("predecessor_id", sa.String(100), nullable=False),
        sa.Column("successor_id", sa.String(100), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.UniqueConstraint("mission_id", "predecessor_id", name="uq_uav_relation_predecessor"),
        sa.UniqueConstraint("mission_id", "successor_id", name="uq_uav_relation_successor"),
    )
    op.create_index(
        "ix_uav_replay_v2_track_relations_mission_id",
        "uav_replay_v2_track_relations",
        ["mission_id"],
    )


def downgrade():
    raise RuntimeError(
        "incremental facts require a compatible consumer; restore a verified backup instead"
    )
