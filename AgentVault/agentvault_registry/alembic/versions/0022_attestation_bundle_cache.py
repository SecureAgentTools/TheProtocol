"""Attestation bundle cache (Phase 4 — signed exportable bundles).

Revision ID: 0022_attestation_bundle_cache
Revises: 0023_dispute_attestation_refs

Adds `attestations.bundle_json TEXT` (lazily populated cache of the
canonical signed-bundle JSON) and `attestations.signature_pubkey_id`
(the issuer's Ed25519 pubkey id at signing time, so verifiers can pin
which key signed which bundle even if the registry rotates).

NOTE: chains after 0023_dispute_attestation_refs because Phase 3 shipped
first in this batch — the numeric prefix `0022` is reserved by the plan
but its `down_revision` follows the on-disk arrival order.

Idempotent: ALTER ADD COLUMN IF NOT EXISTS.
"""

from alembic import op
from sqlalchemy import text


revision = "0022_attestation_bundle_cache"
down_revision = "0023_dispute_attestation_refs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text(
        "ALTER TABLE attestations ADD COLUMN IF NOT EXISTS bundle_json TEXT"
    ))
    bind.execute(text(
        "ALTER TABLE attestations ADD COLUMN IF NOT EXISTS signature_pubkey_id VARCHAR(64)"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text(
        "ALTER TABLE attestations DROP COLUMN IF EXISTS signature_pubkey_id"
    ))
    bind.execute(text(
        "ALTER TABLE attestations DROP COLUMN IF EXISTS bundle_json"
    ))
