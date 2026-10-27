"""PB-1 — Fiat Terms-of-Service consent (W1, 2026-05-09).

Revision ID: 0036_fiat_tos_consent
Revises: 0035_flare_uniqueness

Captures explicit Terms-of-Service acceptance on every fiat purchase row.
Required to close two compliance gaps:

  1. EU distance-contracts §312g BGB requires explicit pre-purchase
     acceptance of the agreed terms; ToS v1.4 § 13.3 (Fiat Purchases /
     Withdrawal-right carve-out per §356(5) BGB) demands that the buyer
     consent to immediate execution AND acknowledge loss of withdrawal
     right at the point of purchase.
  2. Audit trail. We record `tos_accepted_at` + `tos_version` so that we
     can later prove (per row) which version of terms the buyer agreed to
     and when. Both are nullable for backward compatibility — pre-W1 rows
     simply have NULL values.

No backfill: production has 1 real purchase + a handful of sandbox rows,
none of which need pretending they accepted v1.4 terms. NULL = unknown
acceptance; that's the truthful record.

Idempotent (ADD COLUMN IF NOT EXISTS).
"""
from alembic import op


revision = "0036_fiat_tos_consent"
down_revision = "0035_flare_uniqueness"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE fiat_purchases
            ADD COLUMN IF NOT EXISTS tos_accepted_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS tos_version VARCHAR(16);
    """)


def downgrade():
    op.execute("ALTER TABLE fiat_purchases DROP COLUMN IF EXISTS tos_version;")
    op.execute("ALTER TABLE fiat_purchases DROP COLUMN IF EXISTS tos_accepted_at;")
