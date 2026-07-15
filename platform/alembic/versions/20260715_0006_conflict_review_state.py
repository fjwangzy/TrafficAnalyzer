"""Move mutable conflict review state out of the append-only hypertable.

Revision ID: 20260715_0006
Revises: 20260715_0005
"""

from alembic import op
import sqlalchemy as sa


revision = "20260715_0006"
down_revision = "20260715_0005"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "uav_conflict_reviews" not in _tables():
        op.create_table(
            "uav_conflict_reviews",
            sa.Column("event_id", sa.String(80), primary_key=True),
            sa.Column("event_occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("inter_id", sa.String(100), nullable=False),
            sa.Column("review_status", sa.String(24), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("reviewed_by", sa.Integer(), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("review_reason", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["reviewed_by"], ["uav_users.id"]),
            sa.ForeignKeyConstraint(
                ["event_id", "event_occurred_at"],
                ["uav_conflict_events.id", "uav_conflict_events.occurred_at"],
                name="fk_uav_conflict_reviews_event",
                ondelete="CASCADE",
            ),
            sa.CheckConstraint(
                "review_status IN ('confirmed','rejected')",
                name="ck_uav_conflict_reviews_status",
            ),
        )
        op.create_index("ix_uav_conflict_reviews_inter_id", "uav_conflict_reviews", ["inter_id"])

    columns = _columns("uav_conflict_events")
    if "review_status" in columns:
        op.execute("""
            INSERT INTO uav_conflict_reviews
                (event_id,event_occurred_at,inter_id,review_status,revision,reviewed_by,reviewed_at,review_reason)
            SELECT id,occurred_at,inter_id,review_status,review_revision,reviewed_by,
                   COALESCE(reviewed_at,now()),review_reason
            FROM uav_conflict_events
            WHERE review_status IN ('confirmed','rejected')
            ON CONFLICT (event_id) DO NOTHING
        """)
        op.drop_constraint("ck_uav_conflict_review_status", "uav_conflict_events", type_="check")
        op.drop_constraint("fk_uav_conflict_events_reviewed_by_users", "uav_conflict_events", type_="foreignkey")
        for column in ("review_reason", "reviewed_at", "reviewed_by", "review_revision", "review_status"):
            op.drop_column("uav_conflict_events", column)


def downgrade() -> None:
    columns = _columns("uav_conflict_events")
    if "review_status" not in columns:
        op.add_column("uav_conflict_events", sa.Column("review_status", sa.String(24), server_default="pending", nullable=False))
        op.add_column("uav_conflict_events", sa.Column("review_revision", sa.Integer(), server_default="1", nullable=False))
        op.add_column("uav_conflict_events", sa.Column("reviewed_by", sa.Integer(), nullable=True))
        op.add_column("uav_conflict_events", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
        op.add_column("uav_conflict_events", sa.Column("review_reason", sa.Text(), nullable=True))
        op.create_foreign_key("fk_uav_conflict_events_reviewed_by_users", "uav_conflict_events", "uav_users", ["reviewed_by"], ["id"])
        op.create_check_constraint("ck_uav_conflict_review_status", "uav_conflict_events", "review_status IN ('pending','confirmed','rejected')")
        if "uav_conflict_reviews" in _tables():
            op.execute("""
                UPDATE uav_conflict_events AS event SET
                    review_status=review.review_status,
                    review_revision=review.revision,
                    reviewed_by=review.reviewed_by,
                    reviewed_at=review.reviewed_at,
                    review_reason=review.review_reason
                FROM uav_conflict_reviews AS review
                WHERE event.id=review.event_id AND event.occurred_at=review.event_occurred_at
            """)
    if "uav_conflict_reviews" in _tables():
        op.drop_table("uav_conflict_reviews")

