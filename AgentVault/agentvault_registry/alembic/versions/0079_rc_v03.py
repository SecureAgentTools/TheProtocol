"""Registry Card v0.3 — singleton card table + signing keys + peer card cache.

Revision ID: 0079_rc_v03
Revises: 0078_pass58_policy_complete
Create Date: 2026-05-21

Spec: sessionlogs2026/SPEC_2026-05-21_REGISTRY_CARD_v0.3.md
Plan: sessionlogs2026/PLAN_2026-05-21_REGISTRY_CARD_v0.3_IMPLEMENTATION.md (Phase 1)

What this migration does (idempotent — safe to re-run, per migration_bridge contract):

  1. CREATE TABLE registry_card     (singleton — the local registry's own card)
  2. CREATE TABLE registry_signing_keys (mirror of agent_signing_keys for the registry tier)
  3. ALTER peer_registries ADD:
       cached_registry_card JSONB        — peer's v0.3 card body (full JSON)
       card_last_pulled_at  TIMESTAMPTZ  — when federation_sync last fetched
       card_etag            VARCHAR(64)  — for If-None-Match round-trip
       card_signature_verified BOOLEAN   — 3-way SPIFFE verify result
       card_signature_kid   VARCHAR(255) — kid used for the verified signature
  4. INSERT 'RegistryCardUpdated' into event_emission_policies (ETag-only audit event)

Notes:
  - No flare-* columns touched → sovereign-immunity guard not needed
    (see feedback_destructive_migrations_sovereign_immune.md).
  - Revision id is 14 chars, well under 24-char limit
    (see feedback_alembic_revision_id_32char_limit.md).
  - INSERT uses ON CONFLICT (event_type) DO NOTHING for re-run safety.
  - event_emission_policies has NO created_at column
    (see feedback_agent_card_pullsync_worker.md gotcha #1).
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "0079_rc_v03"
down_revision: Union[str, None] = "0078_pass58_policy_complete"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Idempotent schema additions for Registry Card v0.3."""

    # 1. Singleton local card table.
    op.execute(text("""
        CREATE TABLE IF NOT EXISTS registry_card (
            id          INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
            card_json   JSONB NOT NULL,
            card_etag   VARCHAR(80) NOT NULL,
            updated_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_by  INTEGER REFERENCES developers(id) ON DELETE SET NULL
        )
    """))

    # 2. Registry-tier signing-key history (mirror AgentSigningKey at models.py:509).
    op.execute(text("""
        CREATE TABLE IF NOT EXISTS registry_signing_keys (
            registry_spiffe_id      VARCHAR(255) NOT NULL,
            rotation_seq            INTEGER NOT NULL,
            public_jwk              JSONB NOT NULL,
            private_pem_encrypted   TEXT NOT NULL,
            algorithm               VARCHAR(32) NOT NULL DEFAULT 'EdDSA',
            created_at              TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            expires_at              TIMESTAMP WITH TIME ZONE NULL,
            PRIMARY KEY (registry_spiffe_id, rotation_seq)
        )
    """))
    op.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_registry_signing_keys_spiffe
            ON registry_signing_keys (registry_spiffe_id)
    """))
    op.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_registry_signing_keys_expires
            ON registry_signing_keys (expires_at)
            WHERE expires_at IS NOT NULL
    """))

    # 3. Extend peer_registries for cached peer cards.
    op.execute(text("""
        ALTER TABLE peer_registries
            ADD COLUMN IF NOT EXISTS cached_registry_card    JSONB,
            ADD COLUMN IF NOT EXISTS card_last_pulled_at     TIMESTAMP WITH TIME ZONE,
            ADD COLUMN IF NOT EXISTS card_etag               VARCHAR(80),
            ADD COLUMN IF NOT EXISTS card_signature_verified BOOLEAN DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS card_signature_kid      VARCHAR(255)
    """))

    # 4. Event-emission policy for RegistryCardUpdated (ETag-only payload).
    op.execute(text("""
        INSERT INTO event_emission_policies
            (event_type, emit_from_teg, emit_from_registry,
             skip_in_projection, description, updated_at)
        VALUES (
            'RegistryCardUpdated',
            FALSE,
            TRUE,
            TRUE,
            'Registry Card v0.3 visual/economic/commitment publish. Audit-only; ETag-only payload (spiffe_id, card_etag, updated_at). Receivers fetch full card via /.well-known/registry-card.json on demand.',
            NOW()
        )
        ON CONFLICT (event_type) DO NOTHING
    """))


def downgrade() -> None:
    """Drop in reverse order. Preserves event_emission_policies (additive policy data)."""
    op.execute(text("""
        DELETE FROM event_emission_policies WHERE event_type = 'RegistryCardUpdated'
    """))
    op.execute(text("""
        ALTER TABLE peer_registries
            DROP COLUMN IF EXISTS card_signature_kid,
            DROP COLUMN IF EXISTS card_signature_verified,
            DROP COLUMN IF EXISTS card_etag,
            DROP COLUMN IF EXISTS card_last_pulled_at,
            DROP COLUMN IF EXISTS cached_registry_card
    """))
    op.execute(text("DROP INDEX IF EXISTS ix_registry_signing_keys_expires"))
    op.execute(text("DROP INDEX IF EXISTS ix_registry_signing_keys_spiffe"))
    op.execute(text("DROP TABLE IF EXISTS registry_signing_keys"))
    op.execute(text("DROP TABLE IF EXISTS registry_card"))
