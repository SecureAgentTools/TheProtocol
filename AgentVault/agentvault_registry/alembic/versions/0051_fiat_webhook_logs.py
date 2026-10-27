"""Add fiat_webhook_logs table — L1 idempotency + forensic replay (PB-3 W1).

Revision ID: 0051_fiat_webhook_logs
Revises: 0050_fiat_provider_cols
Create Date: 2026-05-12

PB-3 (BL-2) Webhook Fiat Layer — W1 idempotency infrastructure.

`fiat_webhook_logs` is the L1 idempotency layer per
Webhook_Fiat_Layer_Strategy.md §4.4. Every inbound PSP webhook gets a row
keyed on (payment_provider, provider_event_id) UNIQUE. Replays return 200
immediately without doing work; signature failures + parse failures are
logged for forensic analysis even though they never mutate FiatPurchase.

Per §147 AO retention guidance (deep-pass §A.11 F-region): this table is
the authoritative § 147 AO source-proof record (immutable + signed +
sequenced). Retain 10 years cluster-wide.

This migration is IDEMPOTENT (raw SQL with IF NOT EXISTS) per
feedback_migration_use_raw_sql_if_not_exists.md.

Revision-id length: 22 chars.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "0051_fiat_webhook_logs"
down_revision: Union[str, None] = "0050_fiat_provider_cols"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS fiat_webhook_logs (
          id                  BIGSERIAL PRIMARY KEY,
          payment_provider    VARCHAR(32) NOT NULL,
          provider_event_id   VARCHAR(255) NOT NULL,
          event_kind          VARCHAR(64) NOT NULL,
          received_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
          signature_valid     BOOLEAN NOT NULL,
          parse_success       BOOLEAN NOT NULL,
          fiat_purchase_id    VARCHAR(36),
          raw_body_sha256     VARCHAR(64) NOT NULL,
          processing_status   VARCHAR(20) NOT NULL DEFAULT 'received',
          error_detail        TEXT,
          source_ip           INET
        );
    """))
    bind.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_fiat_webhook_logs_event
          ON fiat_webhook_logs (payment_provider, provider_event_id);
    """))
    bind.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_fiat_webhook_logs_recv
          ON fiat_webhook_logs (payment_provider, received_at DESC);
    """))
    bind.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_fiat_webhook_logs_purchase
          ON fiat_webhook_logs (fiat_purchase_id)
          WHERE fiat_purchase_id IS NOT NULL;
    """))
    bind.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_fiat_webhook_logs_sig_fail
          ON fiat_webhook_logs (payment_provider, received_at DESC)
          WHERE signature_valid = false;
    """))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("DROP INDEX IF EXISTS idx_fiat_webhook_logs_sig_fail;"))
    bind.execute(text("DROP INDEX IF EXISTS idx_fiat_webhook_logs_purchase;"))
    bind.execute(text("DROP INDEX IF EXISTS idx_fiat_webhook_logs_recv;"))
    bind.execute(text("DROP INDEX IF EXISTS uq_fiat_webhook_logs_event;"))
    bind.execute(text("DROP TABLE IF EXISTS fiat_webhook_logs;"))
