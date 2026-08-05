"""Add missing business keys for Replay V2 road-grain DWS facts.

Revision ID: 20260805_rv2_0003
Revises: 20260804_rv2_0002
"""

from alembic import op


revision = "20260805_rv2_0003"
down_revision = "20260804_rv2_0002"
branch_labels = None
depends_on = None


CONSTRAINTS = (
    (
        "uq_uav_replay_v2_link_5min",
        "uav_replay_v2_link_metrics_5min",
        ("window_start", "inter_id", "source_profile_id", "mission_id", "calc_version", "link_id"),
    ),
    (
        "uq_uav_replay_v2_lane_5min",
        "uav_replay_v2_lane_metrics_5min",
        ("window_start", "inter_id", "source_profile_id", "mission_id", "calc_version", "lane_id"),
    ),
    (
        "uq_uav_replay_v2_turn_5min",
        "uav_replay_v2_turn_metrics_5min",
        ("window_start", "inter_id", "source_profile_id", "mission_id", "calc_version", "movement_key"),
    ),
)


def upgrade() -> None:
    for name, table, columns in CONSTRAINTS:
        op.create_unique_constraint(name, table, list(columns))


def downgrade() -> None:
    raise RuntimeError("replay-v2 shadow fact rollback requires explicit approved cleanup")
