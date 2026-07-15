"""Create the ADR-019 road9 application and accident-survey baseline.

Revision ID: 20260714_0001
Revises: None
"""

from alembic import op

from app.core.database import Base
import app.models  # noqa: F401


revision = "20260714_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    # Production survey/evidence/audit records are intentionally not dropped by
    # an automatic downgrade. A reviewed forward migration is required.
    pass
