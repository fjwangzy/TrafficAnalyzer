"""Add typed trajectory analysis dimensions.

Revision ID: 20260721_0014
Revises: 20260717_0013
"""

import sqlalchemy as sa

from alembic import op

revision = "20260721_0014"
down_revision = "20260717_0013"
branch_labels = None
depends_on = None


TRACK_COLUMNS = (
    sa.Column("yolo_class_id", sa.Integer(), nullable=True),
    sa.Column("yolo_class_name", sa.String(80), nullable=True),
    sa.Column("yolo_model_id", sa.String(160), nullable=True),
    sa.Column("class_mapping_version", sa.String(120), nullable=True),
    sa.Column("start_road_id", sa.String(100), nullable=True),
    sa.Column("exit_road_id", sa.String(100), nullable=True),
)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("uav_track_events")}
    for column in TRACK_COLUMNS:
        if column.name not in columns:
            op.add_column("uav_track_events", column)

    # Only copy source fields that already exist in the canonical payload.  Raw
    # names and model identities are intentionally not inferred for old facts.
    op.execute(
        "UPDATE uav_track_events SET "
        "yolo_class_id = CASE "
        "WHEN payload->'data'->>'yolo_class_id' ~ '^-?[0-9]+$' "
        "THEN (payload->'data'->>'yolo_class_id')::integer ELSE NULL END, "
        "start_road_id = COALESCE(payload->'data'->>'start_road_id', payload->'data'->>'start_road'), "
        "exit_road_id = COALESCE(payload->'data'->>'exit_road_id', payload->'data'->>'exit_road') "
        "WHERE yolo_class_id IS NULL OR start_road_id IS NULL OR exit_road_id IS NULL"
    )

    indexes = {index["name"] for index in inspector.get_indexes("uav_track_events")}
    if "ix_uav_track_events_analysis_window" not in indexes:
        op.create_index(
            "ix_uav_track_events_analysis_window",
            "uav_track_events",
            ["inter_id", "ended_at"],
        )
    if "ix_uav_track_events_analysis_movement" not in indexes:
        op.create_index(
            "ix_uav_track_events_analysis_movement",
            "uav_track_events",
            ["inter_id", "start_road_id", "exit_road_id", "turn_behavior"],
        )
    if "ix_uav_track_events_analysis_yolo" not in indexes:
        op.create_index(
            "ix_uav_track_events_analysis_yolo",
            "uav_track_events",
            ["inter_id", "yolo_class_id", "yolo_class_name"],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    indexes = {index["name"] for index in inspector.get_indexes("uav_track_events")}
    for name in (
        "ix_uav_track_events_analysis_yolo",
        "ix_uav_track_events_analysis_movement",
        "ix_uav_track_events_analysis_window",
    ):
        if name in indexes:
            op.drop_index(name, table_name="uav_track_events")

    columns = {column["name"] for column in inspector.get_columns("uav_track_events")}
    for column in reversed(TRACK_COLUMNS):
        if column.name in columns:
            op.drop_column("uav_track_events", column.name)
