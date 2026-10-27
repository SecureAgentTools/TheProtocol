"""ZKP Attestation persistence (Phase 1).

Revision ID: 0020_zkp_attestations_table
Revises: 0019_astraeus_phase1

Creates the `attestations` table — Phase 1 columns only. Lifecycle (expiry +
revocation), bundle cache, and dispute back-references are added in 0021,
0022, and 0023 respectively.

IDEMPOTENCY: migration_bridge.py re-stamps alembic_version to 0001_squash on
every boot, so all post-squash migrations replay. Every op uses IF NOT EXISTS
so replay is a no-op.
"""

from alembic import op
from sqlalchemy import text


revision = "0020_zkp_attestations_table"
down_revision = "0019_astraeus_phase1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # pgcrypto provides gen_random_uuid(); enabled by an earlier migration.
    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS attestations (
            id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_did                VARCHAR(255) NOT NULL,
            circuit_id               VARCHAR(255) NOT NULL,
            circuit_version          VARCHAR(64)  NOT NULL,
            public_inputs            JSON         NOT NULL,
            proof_b64                TEXT,
            proof_hash               VARCHAR(64)  NOT NULL,
            policy_parameters_hash   VARCHAR(64),
            verified                 BOOLEAN      NOT NULL,
            failure_reason           VARCHAR(500),
            submitted_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            verified_at              TIMESTAMPTZ,
            event_id                 UUID
        )
    """))

    # Single-column indexes for plain filtering.
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_attestations_agent_did "
        "ON attestations (agent_did)"
    ))
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_attestations_circuit_id "
        "ON attestations (circuit_id)"
    ))
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_attestations_submitted_at "
        "ON attestations (submitted_at DESC)"
    ))

    # Composite indexes for the common access patterns:
    # - paginated agent timeline
    # - paginated circuit timeline
    # - verified-only / failed-only filters
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_attestations_agent_submitted "
        "ON attestations (agent_did, submitted_at DESC)"
    ))
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_attestations_circuit_submitted "
        "ON attestations (circuit_id, submitted_at DESC)"
    ))
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_attestations_verified_submitted "
        "ON attestations (verified, submitted_at DESC)"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("DROP TABLE IF EXISTS attestations"))
