"""ZKP Attestation lifecycle (Phase 2 — expiry + revocation).

Revision ID: 0021_attestation_lifecycle
Revises: 0020_zkp_attestations_table

Adds 5 columns + 1 partial index to `attestations`:
  - expires_at TIMESTAMPTZ
  - revoked_at TIMESTAMPTZ
  - revoked_by VARCHAR(255)         (agent DID or "admin:<dev_id>")
  - revoked_reason VARCHAR(500)
  - expired_emitted_at TIMESTAMPTZ  (daily idempotency for the expiry sweep)

Idempotent: every column is added with IF NOT EXISTS; index is also gated.
migration_bridge.py replays this on every boot, so guards must be sticky.
"""

from alembic import op
from sqlalchemy import text


revision = "0021_attestation_lifecycle"
down_revision = "0020_zkp_attestations_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # Phase 2 columns. Each is nullable so existing Phase-1 rows survive the
    # add. The expires_at default in router code (submit_attestation) keeps
    # new rows populated; old rows can stay NULL (treated as "no expiry").
    bind.execute(text(
        "ALTER TABLE attestations ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ"
    ))
    bind.execute(text(
        "ALTER TABLE attestations ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMPTZ"
    ))
    bind.execute(text(
        "ALTER TABLE attestations ADD COLUMN IF NOT EXISTS revoked_by VARCHAR(255)"
    ))
    bind.execute(text(
        "ALTER TABLE attestations ADD COLUMN IF NOT EXISTS revoked_reason VARCHAR(500)"
    ))
    bind.execute(text(
        "ALTER TABLE attestations ADD COLUMN IF NOT EXISTS expired_emitted_at TIMESTAMPTZ"
    ))

    # Partial index for the expiry sweeper's hot path:
    #   WHERE expires_at < NOW() AND revoked_at IS NULL AND expired_emitted_at IS NULL
    # Postgres can use the partial-index WHERE predicate directly — keeps the
    # sweep query O(matching) regardless of total table size.
    bind.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_attestations_expiry_pending
            ON attestations (expires_at)
            WHERE revoked_at IS NULL AND expired_emitted_at IS NULL
    """))

    # Plain index on revoked_at for admin "list revoked" queries.
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_attestations_revoked_at "
        "ON attestations (revoked_at) WHERE revoked_at IS NOT NULL"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("DROP INDEX IF EXISTS ix_attestations_revoked_at"))
    bind.execute(text("DROP INDEX IF EXISTS ix_attestations_expiry_pending"))
    bind.execute(text("ALTER TABLE attestations DROP COLUMN IF EXISTS expired_emitted_at"))
    bind.execute(text("ALTER TABLE attestations DROP COLUMN IF EXISTS revoked_reason"))
    bind.execute(text("ALTER TABLE attestations DROP COLUMN IF EXISTS revoked_by"))
    bind.execute(text("ALTER TABLE attestations DROP COLUMN IF EXISTS revoked_at"))
    bind.execute(text("ALTER TABLE attestations DROP COLUMN IF EXISTS expires_at"))
