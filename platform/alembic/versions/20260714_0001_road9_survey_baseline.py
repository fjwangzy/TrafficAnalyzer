"""Create the ADR-019 road9 application and accident-survey baseline.

Revision ID: 20260714_0001
Revises: None
"""

import app.models  # noqa: F401
from alembic import op
from app.core.database import Base

revision = "20260714_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Replay V2 has its own migration track even though models share metadata.
    canonical_tables = [
        table for name, table in Base.metadata.tables.items()
        if not name.startswith("uav_replay_v2_")
    ]
    Base.metadata.create_all(bind=op.get_bind(), tables=canonical_tables, checkfirst=True)


def downgrade() -> None:
    # Production survey/evidence/audit records are intentionally not dropped by
    # an automatic downgrade. A reviewed forward migration is required.
    pass
