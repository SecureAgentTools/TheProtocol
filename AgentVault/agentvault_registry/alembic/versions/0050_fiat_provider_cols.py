"""Add payment_provider discriminator + provider-named columns + dispute fields (PB-3 W1).

Revision ID: 0050_fiat_provider_cols
Revises: 0049_op_cli_action_policy
Create Date: 2026-05-12

PB-3 (BL-2) Webhook Fiat Layer — W1 schema extension.

Adds:
  - payment_provider VARCHAR(32) NOT NULL DEFAULT 'stripe' (with index)
  - provider_session_id / provider_event_id / provider_payment_id VARCHAR(255)
  - disputed_at TIMESTAMPTZ + dispute_reason VARCHAR(255)
  - Composite UNIQUE indexes (payment_provider, provider_event_id) +
    (payment_provider, provider_session_id) — different PSPs may issue
    identical session/event-id strings.

Backfills existing Stripe rows by copying stripe_*_id values to
provider_*_id columns. The old stripe_*_id columns stay in place; a
subsequent 0053_fiat_drop_stripe_cols.py (deferred ~30 days per
Webhook_Fiat_Layer_Strategy.md §A.7) drops them after Stripe path is
verified routing through new columns.

This migration is IDEMPOTENT (raw SQL with IF NOT EXISTS / ON CONFLICT
DO NOTHING / partial backfill conditional on NULL) per
feedback_migration_use_raw_sql_if_not_exists.md — required because
cloud-op operators run migration_bridge → 0001_squash → upgrade head
on every boot.

Revision-id length: 28 chars (alembic_version.version_num is varchar(32)).
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "0050_fiat_provider_cols"
down_revision: Union[str, None] = "0049_op_cli_action_policy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # ── New columns (additive, idempotent) ────────────────────────────
    bind.execute(text("""
        ALTER TABLE fiat_purchases
          ADD COLUMN IF NOT EXISTS payment_provider VARCHAR(32) NOT NULL DEFAULT 'stripe';
    """))
    bind.execute(text("""
        ALTER TABLE fiat_purchases
          ADD COLUMN IF NOT EXISTS provider_session_id VARCHAR(255);
    """))
    bind.execute(text("""
        ALTER TABLE fiat_purchases
          ADD COLUMN IF NOT EXISTS provider_event_id VARCHAR(255);
    """))
    bind.execute(text("""
        ALTER TABLE fiat_purchases
          ADD COLUMN IF NOT EXISTS provider_payment_id VARCHAR(255);
    """))
    bind.execute(text("""
        ALTER TABLE fiat_purchases
          ADD COLUMN IF NOT EXISTS disputed_at TIMESTAMPTZ;
    """))
    bind.execute(text("""
        ALTER TABLE fiat_purchases
          ADD COLUMN IF NOT EXISTS dispute_reason VARCHAR(255);
    """))

    # ── Backfill from Stripe-named columns (only where NEW columns are NULL) ──
    # Idempotent: re-running this migration won't overwrite values already set
    # by W2 handler refactor.
    bind.execute(text("""
        UPDATE fiat_purchases
        SET provider_session_id = stripe_session_id
        WHERE provider_session_id IS NULL AND stripe_session_id IS NOT NULL;
    """))
    bind.execute(text("""
        UPDATE fiat_purchases
        SET provider_event_id = stripe_event_id
        WHERE provider_event_id IS NULL AND stripe_event_id IS NOT NULL;
    """))
    bind.execute(text("""
        UPDATE fiat_purchases
        SET provider_payment_id = stripe_payment_intent_id
        WHERE provider_payment_id IS NULL AND stripe_payment_intent_id IS NOT NULL;
    """))

    # ── Composite UNIQUE constraints (provider, *) ──────────────────────
    # Per strategy §3.1 E1 — different PSPs may emit identical event-id strings;
    # the dedup key MUST include payment_provider.
    bind.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_fiat_purchases_provider_event
          ON fiat_purchases (payment_provider, provider_event_id)
          WHERE provider_event_id IS NOT NULL;
    """))
    bind.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_fiat_purchases_provider_session
          ON fiat_purchases (payment_provider, provider_session_id)
          WHERE provider_session_id IS NOT NULL;
    """))
    bind.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_fiat_purchases_provider
          ON fiat_purchases (payment_provider);
    """))
    bind.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_fiat_purchases_disputed
          ON fiat_purchases (disputed_at)
          WHERE disputed_at IS NOT NULL;
    """))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("DROP INDEX IF EXISTS idx_fiat_purchases_disputed;"))
    bind.execute(text("DROP INDEX IF EXISTS idx_fiat_purchases_provider;"))
    bind.execute(text("DROP INDEX IF EXISTS uq_fiat_purchases_provider_session;"))
    bind.execute(text("DROP INDEX IF EXISTS uq_fiat_purchases_provider_event;"))
    bind.execute(text("ALTER TABLE fiat_purchases DROP COLUMN IF EXISTS dispute_reason;"))
    bind.execute(text("ALTER TABLE fiat_purchases DROP COLUMN IF EXISTS disputed_at;"))
    bind.execute(text("ALTER TABLE fiat_purchases DROP COLUMN IF EXISTS provider_payment_id;"))
    bind.execute(text("ALTER TABLE fiat_purchases DROP COLUMN IF EXISTS provider_event_id;"))
    bind.execute(text("ALTER TABLE fiat_purchases DROP COLUMN IF EXISTS provider_session_id;"))
    bind.execute(text("ALTER TABLE fiat_purchases DROP COLUMN IF EXISTS payment_provider;"))
