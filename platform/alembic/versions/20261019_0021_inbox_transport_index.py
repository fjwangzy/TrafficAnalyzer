"""Treat canonical Kafka offsets as provenance, not message identity.

Revision ID: 20261019_0021
Revises: 20260728_0020
"""

import sqlalchemy as sa

from alembic import op

revision = "20261019_0021"
down_revision = "20260728_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = "uav_message_inbox"
    inspector = sa.inspect(op.get_bind())
    if "ix_uav_inbox_topic_partition_offset" not in {
        index["name"] for index in inspector.get_indexes(table)
    }:
        op.create_index("ix_uav_inbox_topic_partition_offset", table, ["topic", "partition", "offset"])
    if "uq_uav_inbox_topic_partition_offset" in {
        constraint["name"] for constraint in inspector.get_unique_constraints(table)
    }:
        op.drop_constraint("uq_uav_inbox_topic_partition_offset", table, type_="unique")


def downgrade() -> None:
    raise RuntimeError("reused Kafka offsets cannot regain uniqueness without discarding inbox history")
