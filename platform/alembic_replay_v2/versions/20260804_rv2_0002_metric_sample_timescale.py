"""Make replay-v2 second metrics a policy-managed Timescale hypertable.

Revision ID: 20260804_rv2_0002
Revises: 20260804_rv2_0001
"""

import sqlalchemy as sa

from alembic import op


revision = "20260804_rv2_0002"
down_revision = "20260804_rv2_0001"
branch_labels = None
depends_on = None


TABLE = "uav_replay_v2_traffic_metric_samples"


def upgrade() -> None:
    bind = op.get_bind()
    available = bind.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM pg_available_extensions WHERE name='timescaledb')")
    ).scalar()
    if not available:
        return

    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
    # Timescale requires every uniqueness constraint to include the partition
    # column.  The V2 inbox remains the global message idempotency boundary.
    op.execute(
        f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS {TABLE}_pkey"
    )
    op.execute(
        f"ALTER TABLE {TABLE} ADD CONSTRAINT {TABLE}_pkey PRIMARY KEY (id, sampled_at)"
    )
    op.execute(
        f"SELECT create_hypertable('{TABLE}', by_range('sampled_at'), "
        "if_not_exists => TRUE, migrate_data => TRUE)"
    )
    op.execute(
        f"ALTER TABLE {TABLE} SET ("
        "timescaledb.compress, "
        "timescaledb.compress_segmentby = 'mission_id,inter_id,source_profile_id', "
        "timescaledb.compress_orderby = 'sampled_at DESC')"
    )
    op.execute(
        f"SELECT add_compression_policy('{TABLE}', INTERVAL '7 days', if_not_exists => TRUE)"
    )
    op.execute(
        f"SELECT add_retention_policy('{TABLE}', INTERVAL '90 days', if_not_exists => TRUE)"
    )


def downgrade() -> None:
    raise RuntimeError("replay-v2 Timescale policy rollback requires explicit approved cleanup")
