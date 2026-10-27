"""Federation licences as issuer-signed certificates (§FEDLICENCE).

Revision ID: 0182_fed_licence_certs
Revises: 0181_legal_acceptances

His word 2026-09-28: the software is free to run, membership in the network is licensed. The genesis registry
signs each frame's network licence and every frame signs its own operators' licences, so a licence hash shown on a
registry card can be checked by anyone against the issuer's signature instead of being taken on the showing frame's
word (sessionlogs2026/DESIGN_2026-09-28_FEDERATION_LICENCE.md).

  federation_licence_keys    this registry's licence-signing keys (Ed25519, the private half encrypted at rest
                             exactly like the registry-card key)
  federation_licence_certs   every certificate this registry issued, holds or trusts, one row per (hash, role):
                             role issued · held · held_operator · root
  peer_registries.licence_*  the verdict this registry reached about a peer's licence (state, hash, when, why)
  frame_invitations.initiator_licence_*   the licence key, certificate and chain an initiator presents

Adds only; touches no existing column. Rolling back past this revision is two steps (downgrade first), and the
downgrade KEEPS every table and column: the root key and the certificates survive a rollback.
"""
from alembic import op

revision = "0182_fed_licence_certs"
down_revision = "0181_legal_acceptances"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS federation_licence_keys (
            id                     SERIAL PRIMARY KEY,
            kid                    VARCHAR(64) NOT NULL UNIQUE,
            public_jwk             JSONB NOT NULL,
            private_pem_encrypted  TEXT NOT NULL,
            created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
            retired_at             TIMESTAMPTZ NULL
        );
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS federation_licence_certs (
            id                SERIAL PRIMARY KEY,
            hash              VARCHAR(64) NOT NULL,
            role              VARCHAR(16) NOT NULL,
            lid               VARCHAR(36) NOT NULL,
            type              VARCHAR(16) NOT NULL,
            sub_trust_domain  VARCHAR(255) NOT NULL,
            sub_name          VARCHAR(255) NOT NULL,
            sub_url           VARCHAR(500) NULL,
            iss_trust_domain  VARCHAR(255) NOT NULL,
            network           VARCHAR(255) NULL,
            plan              VARCHAR(40) NOT NULL,
            issued_at         TIMESTAMPTZ NOT NULL,
            expires_at        TIMESTAMPTZ NULL,
            state             VARCHAR(16) NOT NULL DEFAULT 'active',
            state_reason      VARCHAR(240) NULL,
            jws               TEXT NOT NULL,
            chain             JSONB NOT NULL DEFAULT '[]'::jsonb,
            checked_at        TIMESTAMPTZ NULL,
            created_by        INTEGER NULL REFERENCES developers(id) ON DELETE SET NULL,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_federation_licence_certs_hash_role UNIQUE (hash, role)
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_federation_licence_certs_role_sub "
        "ON federation_licence_certs (role, sub_trust_domain, sub_name);"
    )
    op.execute("ALTER TABLE peer_registries ADD COLUMN IF NOT EXISTS licence_state VARCHAR(24) NULL;")
    op.execute("ALTER TABLE peer_registries ADD COLUMN IF NOT EXISTS licence_hash VARCHAR(64) NULL;")
    op.execute("ALTER TABLE peer_registries ADD COLUMN IF NOT EXISTS licence_checked_at TIMESTAMPTZ NULL;")
    op.execute("ALTER TABLE peer_registries ADD COLUMN IF NOT EXISTS licence_reason VARCHAR(240) NULL;")
    op.execute("ALTER TABLE frame_invitations ADD COLUMN IF NOT EXISTS initiator_licence_certificate TEXT NULL;")
    op.execute("ALTER TABLE frame_invitations ADD COLUMN IF NOT EXISTS initiator_licence_chain JSONB NULL;")
    op.execute("ALTER TABLE frame_invitations ADD COLUMN IF NOT EXISTS initiator_licence_key JSONB NULL;")


def downgrade() -> None:
    """Keeps every table and column ON PURPOSE (agentvault2-05's review): after a genesis ceremony
    federation_licence_keys holds the network's ROOT signing key, and federation_licence_certs every licence it
    issued; a rollback must never destroy them. An older image ignores tables and columns it does not map, and the
    upgrade is idempotent (IF NOT EXISTS), so a downgrade here moves only the version stamp."""
    return None
