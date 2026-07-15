"""Add S4 candidate zones/rules, clue facts, and general evidence ownership.

Revision ID: 20260715_0008
Revises: 20260715_0007
"""

from alembic import op
import sqlalchemy as sa


revision = "20260715_0008"
down_revision = "20260715_0007"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "owner_type" not in _columns("uav_evidence_packages"):
        op.add_column("uav_evidence_packages", sa.Column("owner_type", sa.String(40), nullable=False, server_default="survey_task"))
        op.add_column("uav_evidence_packages", sa.Column("owner_id", sa.String(80), nullable=True))
        op.add_column("uav_evidence_packages", sa.Column("source_system", sa.String(80), nullable=False, server_default="uav_traffic_analyzer_ai"))
        op.add_column("uav_evidence_packages", sa.Column("source_event_id", sa.String(80), nullable=True))
        op.execute("UPDATE uav_evidence_packages SET owner_id=task_id WHERE owner_id IS NULL")
        op.create_index("ix_uav_evidence_packages_owner_id", "uav_evidence_packages", ["owner_id"])
        op.create_index("ix_uav_evidence_packages_source_event", "uav_evidence_packages", ["source_system", "source_event_id"])
        op.create_unique_constraint("uq_uav_evidence_package_owner_version", "uav_evidence_packages", ["owner_type", "owner_id", "version"])
        op.alter_column("uav_evidence_packages", "task_id", existing_type=sa.String(40), nullable=True)
        op.alter_column("uav_evidence_items", "task_id", existing_type=sa.String(40), nullable=True)

    event_columns = _columns("uav_ai_events")
    if "review_revision" not in event_columns:
        op.add_column("uav_ai_events", sa.Column("review_revision", sa.Integer(), nullable=False, server_default="1"))
        op.add_column("uav_ai_events", sa.Column("review_reason", sa.Text(), nullable=True))
        op.add_column("uav_ai_events", sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("uav_users.id"), nullable=True))
        op.add_column("uav_ai_events", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))

    tables = _tables()
    if "uav_enforcement_zones" not in tables:
        op.create_table(
            "uav_enforcement_zones",
            sa.Column("id", sa.String(40), primary_key=True),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("zone_type", sa.String(40), nullable=False),
            sa.Column("geometry", sa.JSON(), nullable=False),
            sa.Column("coordinate_system", sa.String(32), nullable=False),
            sa.Column("road_data_version", sa.String(100), nullable=True),
            sa.Column("source", sa.String(40), nullable=False, server_default="local_candidate"),
            sa.Column("status", sa.String(24), nullable=False, server_default="candidate"),
            sa.Column("schedule", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column("checksum", sa.String(64), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("uav_users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint("status IN ('candidate','retired')", name="ck_uav_enforcement_zone_local_status"),
            sa.CheckConstraint("source IN ('local_candidate','authority_snapshot')", name="ck_uav_enforcement_zone_source"),
        )
        op.create_index("ix_uav_enforcement_zones_type", "uav_enforcement_zones", ["zone_type"])
        op.create_index("ix_uav_enforcement_zones_status", "uav_enforcement_zones", ["status"])

    if "uav_enforcement_rules" not in tables:
        op.create_table(
            "uav_enforcement_rules",
            sa.Column("id", sa.String(40), primary_key=True),
            sa.Column("rule_version_id", sa.String(40), sa.ForeignKey("uav_rule_versions.id"), nullable=False, unique=True),
            sa.Column("zone_id", sa.String(40), sa.ForeignKey("uav_enforcement_zones.id"), nullable=True),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("clue_type", sa.String(40), nullable=False),
            sa.Column("definition", sa.JSON(), nullable=False),
            sa.Column("source", sa.String(40), nullable=False, server_default="local_candidate"),
            sa.Column("status", sa.String(24), nullable=False, server_default="candidate"),
            sa.Column("quality_status", sa.String(24), nullable=False, server_default="unverified"),
            sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("uav_users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint("status IN ('candidate','retired')", name="ck_uav_enforcement_rule_local_status"),
            sa.CheckConstraint("quality_status IN ('unverified','degraded','verified')", name="ck_uav_enforcement_rule_quality"),
        )
        op.create_index("ix_uav_enforcement_rules_zone", "uav_enforcement_rules", ["zone_id"])
        op.create_index("ix_uav_enforcement_rules_type", "uav_enforcement_rules", ["clue_type"])
        op.create_index("ix_uav_enforcement_rules_status", "uav_enforcement_rules", ["status"])

    if "uav_enforcement_clues" not in tables:
        op.create_table(
            "uav_enforcement_clues",
            sa.Column("event_id", sa.String(40), sa.ForeignKey("uav_ai_events.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("event_revision", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("track_id", sa.String(80), nullable=False),
            sa.Column("vehicle_class", sa.String(24), nullable=False),
            sa.Column("class_confidence", sa.Float(), nullable=True),
            sa.Column("classification_model_version", sa.String(120), nullable=True),
            sa.Column("clue_type", sa.String(40), nullable=False),
            sa.Column("zone_id", sa.String(40), nullable=True),
            sa.Column("zone_version", sa.String(40), nullable=True),
            sa.Column("rule_id", sa.String(40), nullable=True),
            sa.Column("rule_version", sa.String(40), nullable=True),
            sa.Column("matched_facts", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column("exclusion_result", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column("video_speed_kmh", sa.Float(), nullable=True),
            sa.Column("video_speed_method", sa.String(80), nullable=True),
            sa.Column("video_speed_quality", sa.String(24), nullable=True),
            sa.Column("video_speed_uncertainty", sa.Float(), nullable=True),
            sa.Column("radar_speed_kmh", sa.Float(), nullable=True),
            sa.Column("radar_device_id", sa.String(80), nullable=True),
            sa.Column("radar_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
            sa.Column("fused_speed_kmh", sa.Float(), nullable=True),
            sa.Column("fusion_method", sa.String(80), nullable=True),
            sa.Column("evidence_package_id", sa.String(40), sa.ForeignKey("uav_evidence_packages.id"), nullable=True),
            sa.Column("evidence_integrity_status", sa.String(24), nullable=False, server_default="unverified"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint("vehicle_class IN ('truck','non_truck','unknown')", name="ck_uav_enforcement_vehicle_class"),
        )
        op.create_index("ix_uav_enforcement_clues_type", "uav_enforcement_clues", ["clue_type"])
        op.create_index("ix_uav_enforcement_clues_zone", "uav_enforcement_clues", ["zone_id"])
        op.create_index("ix_uav_enforcement_clues_rule", "uav_enforcement_clues", ["rule_id"])

    if "uav_enforcement_review_audits" not in tables:
        op.create_table(
            "uav_enforcement_review_audits",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("event_id", sa.String(40), sa.ForeignKey("uav_ai_events.id", ondelete="CASCADE"), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("review_status", sa.String(32), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("uav_users.id"), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("event_id", "revision", name="uq_uav_enforcement_review_revision"),
        )
        op.create_index("ix_uav_enforcement_review_event", "uav_enforcement_review_audits", ["event_id"])


def downgrade() -> None:
    tables = _tables()
    for table in ("uav_enforcement_review_audits", "uav_enforcement_clues", "uav_enforcement_rules", "uav_enforcement_zones"):
        if table in tables:
            op.drop_table(table)
    event_columns = _columns("uav_ai_events")
    for column in ("reviewed_at", "reviewed_by", "review_reason", "review_revision"):
        if column in event_columns:
            op.drop_column("uav_ai_events", column)
    package_columns = _columns("uav_evidence_packages")
    if "owner_type" in package_columns:
        op.alter_column("uav_evidence_items", "task_id", existing_type=sa.String(40), nullable=False)
        op.alter_column("uav_evidence_packages", "task_id", existing_type=sa.String(40), nullable=False)
        op.drop_constraint("uq_uav_evidence_package_owner_version", "uav_evidence_packages", type_="unique")
        op.drop_index("ix_uav_evidence_packages_source_event", table_name="uav_evidence_packages")
        op.drop_index("ix_uav_evidence_packages_owner_id", table_name="uav_evidence_packages")
        for column in ("source_event_id", "source_system", "owner_id", "owner_type"):
            op.drop_column("uav_evidence_packages", column)
