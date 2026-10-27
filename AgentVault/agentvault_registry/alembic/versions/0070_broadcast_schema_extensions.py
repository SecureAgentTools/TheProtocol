"""§bc2 T2.1 — AdminBroadcast schema extensions.

Revision ID: 0070_broadcast_schema_extensions
Revises: 0069_broadcast_event_emission_policies
Create Date: 2026-05-19

Adds the seven columns that unlock §bc2 (cta_url + cta_label + requires_ack
+ scheduled_for) + §bc3 (source_frame + idempotency_key — for federation
dedup) + §bc4 (target_org_id — for org-scoped broadcasts).

UNIQUE partial index on (source_frame, idempotency_key) WHERE
idempotency_key IS NOT NULL guards against duplicate materialization when
federated broadcasts replay over the EventStore Pub/Sub fan-out (§bc3).

All ADD COLUMN ops use IF NOT EXISTS for re-run safety. The partial index
is dropped + recreated on downgrade.

DEFENSE-IN-DEPTH: target_org_id has no FK constraint in this migration
because Organization.id is `character varying`. The FK is added in a
separate ALTER TABLE for clarity + reversibility.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0070_bc2_schema_ext"
down_revision: Union[str, None] = "0069_bc2_audit_policies"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # §bc2 T2.1 — schema columns. All NULLable so existing rows stay valid.
    op.execute("ALTER TABLE admin_broadcasts ADD COLUMN IF NOT EXISTS cta_url         VARCHAR(500);")
    op.execute("ALTER TABLE admin_broadcasts ADD COLUMN IF NOT EXISTS cta_label       VARCHAR(50);")
    op.execute("ALTER TABLE admin_broadcasts ADD COLUMN IF NOT EXISTS requires_ack    BOOLEAN NOT NULL DEFAULT false;")
    op.execute("ALTER TABLE admin_broadcasts ADD COLUMN IF NOT EXISTS scheduled_for   TIMESTAMP WITH TIME ZONE;")
    op.execute("ALTER TABLE admin_broadcasts ADD COLUMN IF NOT EXISTS source_frame    VARCHAR(100);")
    op.execute("ALTER TABLE admin_broadcasts ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(120);")
    op.execute("ALTER TABLE admin_broadcasts ADD COLUMN IF NOT EXISTS target_org_id   VARCHAR;")

    # FK to organizations — split out so it can be reverted independently.
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'admin_broadcasts_target_org_id_fkey'
            ) THEN
                ALTER TABLE admin_broadcasts
                ADD CONSTRAINT admin_broadcasts_target_org_id_fkey
                FOREIGN KEY (target_org_id) REFERENCES organizations(id)
                ON DELETE SET NULL;
            END IF;
        END$$;
    """)

    # Federation dedup index — partial so legacy rows without idempotency_key
    # don't collide.
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_broadcasts_idempotency_unique
        ON admin_broadcasts(source_frame, idempotency_key)
        WHERE idempotency_key IS NOT NULL;
    """)

    # Scheduler scan index — speeds up "WHERE scheduled_for <= NOW() AND
    # email_sent_at IS NULL AND is_active=TRUE" hot path in the scheduler.
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_broadcasts_scheduled_pending
        ON admin_broadcasts(scheduled_for)
        WHERE scheduled_for IS NOT NULL AND email_sent_at IS NULL AND is_active = TRUE;
    """)

    # Org-scoped query helper — speeds up "WHERE target_org_id IN (dev_org_ids)"
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_broadcasts_target_org_active
        ON admin_broadcasts(target_org_id, is_active)
        WHERE target_org_id IS NOT NULL;
    """)


def downgrade() -> None:
    # Drop indexes first
    op.execute("DROP INDEX IF EXISTS ix_broadcasts_target_org_active;")
    op.execute("DROP INDEX IF EXISTS ix_broadcasts_scheduled_pending;")
    op.execute("DROP INDEX IF EXISTS ix_broadcasts_idempotency_unique;")
    # Drop FK
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'admin_broadcasts_target_org_id_fkey'
            ) THEN
                ALTER TABLE admin_broadcasts
                DROP CONSTRAINT admin_broadcasts_target_org_id_fkey;
            END IF;
        END$$;
    """)
    # Then columns
    op.execute("ALTER TABLE admin_broadcasts DROP COLUMN IF EXISTS target_org_id;")
    op.execute("ALTER TABLE admin_broadcasts DROP COLUMN IF EXISTS idempotency_key;")
    op.execute("ALTER TABLE admin_broadcasts DROP COLUMN IF EXISTS source_frame;")
    op.execute("ALTER TABLE admin_broadcasts DROP COLUMN IF EXISTS scheduled_for;")
    op.execute("ALTER TABLE admin_broadcasts DROP COLUMN IF EXISTS requires_ack;")
    op.execute("ALTER TABLE admin_broadcasts DROP COLUMN IF EXISTS cta_label;")
    op.execute("ALTER TABLE admin_broadcasts DROP COLUMN IF EXISTS cta_url;")
