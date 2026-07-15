"""Replace restore-unsafe regular-to-hypertable foreign key with triggers.

Revision ID: 20260715_0009
Revises: 20260715_0008
"""

from alembic import op


revision = "20260715_0009"
down_revision = "20260715_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DO $$
        DECLARE item record;
        BEGIN
          FOR item IN
            SELECT conname FROM pg_constraint
            WHERE conrelid='public.uav_conflict_reviews'::regclass
              AND contype='f'
              AND conname <> 'uav_conflict_reviews_reviewed_by_fkey'
          LOOP
            EXECUTE format(
              'ALTER TABLE public.uav_conflict_reviews DROP CONSTRAINT IF EXISTS %I',
              item.conname
            );
          END LOOP;
        END $$
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION public.uav_validate_conflict_review_event()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM public.uav_conflict_events
            WHERE id=NEW.event_id AND occurred_at=NEW.event_occurred_at
          ) THEN
            RAISE EXCEPTION 'conflict review references missing event % at %',
              NEW.event_id, NEW.event_occurred_at
              USING ERRCODE='foreign_key_violation';
          END IF;
          RETURN NEW;
        END $$
    """)
    op.execute("DROP TRIGGER IF EXISTS uav_conflict_review_event_guard ON public.uav_conflict_reviews")
    op.execute("""
        CREATE TRIGGER uav_conflict_review_event_guard
        BEFORE INSERT OR UPDATE OF event_id,event_occurred_at
        ON public.uav_conflict_reviews
        FOR EACH ROW EXECUTE FUNCTION public.uav_validate_conflict_review_event()
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION public.uav_cascade_conflict_review_delete()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          DELETE FROM public.uav_conflict_reviews
          WHERE event_id=OLD.id AND event_occurred_at=OLD.occurred_at;
          RETURN OLD;
        END $$
    """)
    op.execute("DROP TRIGGER IF EXISTS uav_conflict_review_delete_cascade ON public.uav_conflict_events")
    op.execute("""
        CREATE TRIGGER uav_conflict_review_delete_cascade
        BEFORE DELETE ON public.uav_conflict_events
        FOR EACH ROW EXECUTE FUNCTION public.uav_cascade_conflict_review_delete()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS uav_conflict_review_delete_cascade ON public.uav_conflict_events")
    op.execute("DROP FUNCTION IF EXISTS public.uav_cascade_conflict_review_delete()")
    op.execute("DROP TRIGGER IF EXISTS uav_conflict_review_event_guard ON public.uav_conflict_reviews")
    op.execute("DROP FUNCTION IF EXISTS public.uav_validate_conflict_review_event()")
    op.execute("""
        ALTER TABLE public.uav_conflict_reviews
          ADD CONSTRAINT fk_uav_conflict_reviews_event
          FOREIGN KEY (event_id,event_occurred_at)
          REFERENCES public.uav_conflict_events(id,occurred_at)
          ON DELETE CASCADE
    """)
