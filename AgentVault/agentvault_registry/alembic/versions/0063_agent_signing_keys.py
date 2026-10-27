"""agent_signing_keys table — Option C Phase 9.a JWS shadow mode.

Revision ID: 0063_agent_signing_keys
Revises: 0062_agent_card_pullsync
Create Date: 2026-05-17

§pass36 Phase 9.a — every active agent has at least one EdDSA signing key
recorded here. The Q-C W5 path already populates `agents.public_key_jwk` at
create time (server-generated EdDSA); this migration adds a rotation_seq +
expiration grace window on top so old keys remain valid for verification for
N days after rotation.

Wire format (RFC 7515 detached JWS, `kid = <agent_did>#<rotation_seq>`) is
implemented in `theprotocol.auth.jws_card`. Registry verifier:
`services/a2a_v1/jws_verifier.py`.

3-flag staircase (env, all default-off):
  JWS_VERIFY_ENABLED   — master kill; when false, no verification anywhere.
  JWS_ENFORCE          — when true, invalid sigs reject (default false = shadow).
  JWS_REQUIRE_SIGNATURE — when true, unsigned cards also reject (final hardening).

Also seeds two event_emission_policies for the rotate flow.

Idempotency: raw SQL with IF NOT EXISTS / ON CONFLICT DO NOTHING per the
0061/0062 precedent.
"""
from alembic import op
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = '0063_agent_signing_keys'
down_revision = '0062_agent_card_pullsync'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Table.
    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS agent_signing_keys (
            agent_did    VARCHAR(255) NOT NULL,
            rotation_seq INTEGER NOT NULL,
            public_jwk   JSONB NOT NULL,
            algorithm    VARCHAR(32) NOT NULL DEFAULT 'EdDSA',
            created_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            expires_at   TIMESTAMP WITH TIME ZONE,
            PRIMARY KEY (agent_did, rotation_seq)
        )
    """))

    # 2. Indexes — speed up active-key lookups + expiring-soon queries.
    bind.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_agent_signing_keys_did
        ON agent_signing_keys (agent_did)
    """))
    bind.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_agent_signing_keys_expires
        ON agent_signing_keys (expires_at) WHERE expires_at IS NOT NULL
    """))

    # 3. Backfill from agents.public_key_jwk so existing agents have at least
    #    one rotation_seq=1 row immediately. The registry's existing
    #    /agents/{did}/public-key endpoint already reads from agents.public_key_jwk
    #    so the table starts in a self-consistent state.
    bind.execute(text("""
        INSERT INTO agent_signing_keys (agent_did, rotation_seq, public_jwk, algorithm, created_at)
        SELECT
            did,
            1 AS rotation_seq,
            public_key_jwk AS public_jwk,
            COALESCE(public_key_jwk->>'alg', 'EdDSA') AS algorithm,
            COALESCE(created_at, NOW()) AS created_at
        FROM agents
        WHERE public_key_jwk IS NOT NULL
        ON CONFLICT (agent_did, rotation_seq) DO NOTHING
    """))

    # 4. Event emission policies for the rotate + verify flows.
    bind.execute(text("""
        INSERT INTO event_emission_policies
          (event_type, emit_from_teg, emit_from_registry, skip_in_projection,
           description, updated_at)
        VALUES
          ('AgentSigningKeyRotated', false, true, true,
           'Option C Phase 9.a — admin rotated an agent signing key. The old key remains valid for KEY_ROTATION_GRACE_DAYS (default 7) for verifier compatibility.',
           NOW()),
          ('AgentCardJWSVerifyFailed', false, true, true,
           'Option C Phase 9.a — verifier rejected (or in shadow mode, would have rejected) a card signature. Audit trail; emitted at most once per agent per minute via reactor throttle.',
           NOW())
        ON CONFLICT (event_type) DO NOTHING
    """))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("""
        DELETE FROM event_emission_policies
        WHERE event_type IN ('AgentSigningKeyRotated', 'AgentCardJWSVerifyFailed')
    """))
    bind.execute(text("DROP INDEX IF EXISTS ix_agent_signing_keys_expires"))
    bind.execute(text("DROP INDEX IF EXISTS ix_agent_signing_keys_did"))
    bind.execute(text("DROP TABLE IF EXISTS agent_signing_keys"))
