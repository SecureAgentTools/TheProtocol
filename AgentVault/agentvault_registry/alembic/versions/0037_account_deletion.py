"""W2 — User-initiated account deletion / GDPR Art. 17 erasure (2026-05-09).

Revision ID: 0037_account_deletion
Revises: 0036_fiat_tos_consent

Adds three columns to `developers` to support the user-initiated
deletion flow with a 14-day cooling-off period:

  • deletion_status         VARCHAR(20)  — one of {NULL, 'pending_deletion',
                                          'anonymized'}. NULL ≡ active. Stored
                                          as a string (not enum) so future
                                          states can be added without a DDL.
  • deletion_requested_at   TIMESTAMPTZ  — when the user clicked "delete me".
                                          The 14-day cooling-off worker reads
                                          this to decide which rows to
                                          anonymize.
  • anonymized_at           TIMESTAMPTZ  — when the row was actually wiped of
                                          PII. Final state.

Plus a composite index `(deletion_status, deletion_requested_at)` so the
daily worker scan stays cheap regardless of fleet size.

Anonymize-don't-hard-delete is a deliberate architectural choice: § 147
AO (German Fiscal Code) requires retention of financial records for
ten (10) years, and the EventStore is immutable by design. We keep the
Developer row as an FK referent and wipe the PII fields in-place. The
buyer's right of erasure is honored for non-financial PII; the financial
trail remains for the legal-hold window. See Privacy Policy § 4.5.

Idempotent (ADD COLUMN IF NOT EXISTS).
"""
from alembic import op


revision = "0037_account_deletion"
down_revision = "0036_fiat_tos_consent"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE developers
            ADD COLUMN IF NOT EXISTS deletion_status        VARCHAR(20),
            ADD COLUMN IF NOT EXISTS deletion_requested_at  TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS anonymized_at          TIMESTAMPTZ;
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_developers_deletion_scan
        ON developers (deletion_status, deletion_requested_at)
        WHERE deletion_status IS NOT NULL;
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_developers_deletion_scan;")
    op.execute("ALTER TABLE developers DROP COLUMN IF EXISTS anonymized_at;")
    op.execute("ALTER TABLE developers DROP COLUMN IF EXISTS deletion_requested_at;")
    op.execute("ALTER TABLE developers DROP COLUMN IF EXISTS deletion_status;")
