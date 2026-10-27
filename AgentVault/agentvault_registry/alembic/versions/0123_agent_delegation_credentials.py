"""0123 — IRONKEY ★2: cross-registry sub-agent delegation credentials (2026-07-18).

Additive-only. An agent A on registry-1 delegates a bounded permission subset to agent B on
registry-2: A's HOME signs an Ed25519 delegation credential (the existing attestation-signer
bundle) and ships it to B's HOME over the federation channel. B's HOME verifies the signature
against registry-1's published signing pubkey (fetched over the allowlisted mTLS peer channel,
same as guild travel credentials), records the credential HERE, and mints a LOCAL
``agent_delegation_grants`` row with principal ``agent:<A>`` — so B's authority is still
RESOLVED at B's own home. Ground-truth preserved: a peer can never mint authority here; the
receiving registry mints a bounded LOCAL grant from a VERIFIED credential, and can revoke it.
Δ-irrelevant (permission bookkeeping + signature verification only; no money).
IDEMPOTENT (IF NOT EXISTS), chains 0122.
"""
from alembic import op
from sqlalchemy import text

# NOTE: alembic_version.version_num is varchar(32) — the revision id MUST be ≤32 chars
# ("0123_agent_delegation_credentials" was 33 and failed StringDataRightTruncation on boot).
revision: str = "0123_agent_deleg_creds"
down_revision: str = "0122_peer_deactivation_reason"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS agent_delegation_credentials (
            id            VARCHAR(48) PRIMARY KEY,
            credential_id VARCHAR(64) NOT NULL,
            host_registry VARCHAR(300) NOT NULL,   -- the ISSUER's registry (where A lives)
            issuer_did    VARCHAR(120) NOT NULL,   -- delegating agent A (remote)
            delegate_did  VARCHAR(120) NOT NULL,   -- delegate agent B (local to this registry)
            permissions   TEXT[] NOT NULL DEFAULT '{}',
            caveats       JSONB,
            bundle        JSONB NOT NULL,          -- the full signed credential
            pubkey_id     VARCHAR(32),
            verified      BOOLEAN NOT NULL DEFAULT FALSE,
            grant_id      BIGINT,                  -- the agent_delegation_grants row minted from this
            revoked_at    TIMESTAMPTZ,
            received_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uix_adc_host_cred UNIQUE (host_registry, credential_id)
        )
    """))
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_adc_delegate ON agent_delegation_credentials (delegate_did, received_at DESC)"))
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_adc_issuer ON agent_delegation_credentials (issuer_did)"))


def downgrade() -> None:
    # Additive-only; never dropped on rollback (an older image tolerates the extra table).
    pass
