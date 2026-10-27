"""§bc2 T2.5 — broadcast_email_failed table for per-batch retry.

Revision ID: 0071_broadcast_email_failed_table
Revises: 0070_broadcast_schema_extensions
Create Date: 2026-05-19

The previous `_send_broadcast_email` would silently lose batches of 50 if
ONE SMTP call in the loop raised — the exception propagated, the rest of
the batches never ran, and there was no record of which developers missed
the email. P2.12 in the §bc1-§bc5 plan.

This table captures every failed batch with its developer-id list + error
reason + next_retry_at. A separate `broadcast_email_retry_worker.py`
(BackgroundWorker subclass) sweeps it with exponential backoff
60s → 5min → 30min → 2h → 12h, then marks `dead_letter_at` and stops
retrying (operator must intervene manually).

All ops idempotent (CREATE IF NOT EXISTS).
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0071_bc2_email_failed"
down_revision: Union[str, None] = "0070_bc2_schema_ext"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS broadcast_email_failed (
            id                  BIGSERIAL PRIMARY KEY,
            broadcast_id        INTEGER NOT NULL REFERENCES admin_broadcasts(id) ON DELETE CASCADE,
            batch_index         INTEGER NOT NULL,
            developer_ids_json  JSONB NOT NULL,
            error_reason        VARCHAR(500),
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            retry_count         INTEGER NOT NULL DEFAULT 0,
            next_retry_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_retry_at       TIMESTAMPTZ,
            dead_letter_at      TIMESTAMPTZ,
            delivered_at        TIMESTAMPTZ
        );
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_broadcast_email_failed_pending
        ON broadcast_email_failed(next_retry_at)
        WHERE delivered_at IS NULL AND dead_letter_at IS NULL;
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_broadcast_email_failed_by_broadcast
        ON broadcast_email_failed(broadcast_id, created_at DESC);
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_broadcast_email_failed_by_broadcast;")
    op.execute("DROP INDEX IF EXISTS ix_broadcast_email_failed_pending;")
    op.execute("DROP TABLE IF EXISTS broadcast_email_failed;")
