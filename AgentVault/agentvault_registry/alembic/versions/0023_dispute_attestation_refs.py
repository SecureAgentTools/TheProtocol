"""Disputes — referenced ZKP attestations (Phase 3 trust-chain).

Revision ID: 0023_dispute_attestation_refs
Revises: 0021_attestation_lifecycle

Adds `disputes.referenced_attestations` (JSON array of UUID strings).
The defendant in a dispute may cite verified attestations as exculpatory
evidence; the slashing weight is reduced by ZKP_DISPUTE_SLASH_REDUCTION
per matching attestation, capped at 0.5 cumulative.

NOTE: Phase 4 will add migration 0022_attestation_bundle_cache.py — order
of arrival, not numeric order, is what governs replay safety since each
migration's down_revision pins the chain. We use 0023 here so 0022 stays
reserved for Phase 4 as the plan specifies.

Idempotent: ALTER ADD COLUMN IF NOT EXISTS.
"""

from alembic import op
from sqlalchemy import text


revision = "0023_dispute_attestation_refs"
down_revision = "0021_attestation_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text(
        "ALTER TABLE disputes "
        "ADD COLUMN IF NOT EXISTS referenced_attestations JSON"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text(
        "ALTER TABLE disputes DROP COLUMN IF EXISTS referenced_attestations"
    ))
