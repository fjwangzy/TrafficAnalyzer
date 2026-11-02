"""Keep Kafka offsets as provenance across replay Topic recreation.

Revision ID: 20261019_rv2_0005
Revises: 20260809_rv2_0004
"""

import sqlalchemy as sa

from alembic import op

revision = "20261019_rv2_0005"
down_revision = "20260809_rv2_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = "uav_replay_v2_message_inbox"
    inspector = sa.inspect(op.get_bind())
    if "ix_uav_replay_v2_inbox_offset" not in {
        index["name"] for index in inspector.get_indexes(table)
    }:
        op.create_index("ix_uav_replay_v2_inbox_offset", table, ["topic", "partition", "offset"])
    if "uq_uav_replay_v2_inbox_offset" in {
        constraint["name"] for constraint in inspector.get_unique_constraints(table)
    }:
        op.drop_constraint("uq_uav_replay_v2_inbox_offset", table, type_="unique")


def downgrade() -> None:
    raise RuntimeError("reused Kafka offsets cannot regain uniqueness without discarding inbox history")
