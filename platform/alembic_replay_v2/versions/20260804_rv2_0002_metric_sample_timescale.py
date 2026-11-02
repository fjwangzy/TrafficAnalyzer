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
    from app.core.config import settings
    from app.core.timeseries import configure_timescale
    bind = op.get_bind()
    if settings.deployment_mode != "production":
        available = bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM pg_available_extensions WHERE name='timescaledb')"))
        if available:
            op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
    # Also used by explicit init-db after the DBA enables the extension later.
    configure_timescale(bind, replay_v2=True)


def downgrade() -> None:
    raise RuntimeError("replay-v2 Timescale policy rollback requires explicit approved cleanup")
