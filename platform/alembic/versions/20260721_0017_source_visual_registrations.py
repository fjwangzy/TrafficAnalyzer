"""Bind visual registrations to immutable source profiles.

Revision ID: 20260721_0017
Revises: 20260721_0016
"""

import sqlalchemy as sa
from alembic import op


revision = "20260721_0017"
down_revision = "20260721_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "uav_visual_registrations",
        sa.Column("source_profile_id", sa.String(40), nullable=True),
    )
    op.create_foreign_key(
        "fk_uav_visual_registrations_source_profile",
        "uav_visual_registrations",
        "uav_video_sources",
        ["source_profile_id"],
        ["profile_id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_uav_visual_registrations_source_profile_id",
        "uav_visual_registrations",
        ["source_profile_id"],
    )
    op.create_unique_constraint(
        "uq_uav_visual_registration_map_source",
        "uav_visual_registrations",
        ["map_version_id", "source_profile_id"],
    )


def downgrade() -> None:
    raise RuntimeError("source-specific GCJ-02 registrations are intentionally irreversible")
