"""0109 — IRONKEY L4: agent_capability_tokens (att_ attenuable capability chain) (2026-07-04).

Additive table modelled on a2a_payment_authorizations (apt_): SHA-256-stored, TTL'd,
state-machine, PLUS a self-referential ``parent_token_id`` chain + ``caveats`` JSONB +
budget. NO existing data touched → **Δ-irrelevant** (a capability authorizes; it never
moves money — every real transfer still clears the escrow rails). Inert until
``AGENT_DELEGATION_MODE`` is shadow/enforce.

IDEMPOTENT — replays every boot via migration_bridge. All DDL IF NOT EXISTS. Chains 0108.
"""
from alembic import op
from sqlalchemy import text

revision: str = "0109_agent_capability_tokens"
down_revision: str = "0108_agent_delegation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS agent_capability_tokens (
            id BIGSERIAL PRIMARY KEY,
            token_hash TEXT NOT NULL UNIQUE,
            token_prefix TEXT NOT NULL,
            issuer_agent_did TEXT NOT NULL REFERENCES agents(did) ON DELETE CASCADE,
            holder_agent_did TEXT NULL,
            parent_token_id BIGINT NULL REFERENCES agent_capability_tokens(id) ON DELETE CASCADE,
            depth SMALLINT NOT NULL DEFAULT 0,
            caveats JSONB NOT NULL DEFAULT '{}'::jsonb,
            budget_total NUMERIC(36,18) NULL,
            budget_spent NUMERIC(36,18) NOT NULL DEFAULT 0,
            currency TEXT NULL,
            max_uses INTEGER NULL,
            uses INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'issued',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at TIMESTAMPTZ NOT NULL,
            revoked_at TIMESTAMPTZ NULL,
            revoke_reason TEXT NULL,
            CONSTRAINT ck_cap_status CHECK (status IN ('issued','active','expired','revoked','exhausted')),
            CONSTRAINT ck_cap_depth CHECK (depth >= 0 AND depth <= 8),
            CONSTRAINT ck_cap_budget_nonneg CHECK (budget_spent >= 0)
        )
    """))
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_cap_issuer ON agent_capability_tokens(issuer_agent_did)"
    ))
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_cap_holder ON agent_capability_tokens(holder_agent_did) "
        "WHERE holder_agent_did IS NOT NULL"
    ))
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_cap_parent ON agent_capability_tokens(parent_token_id) "
        "WHERE parent_token_id IS NOT NULL"
    ))
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_cap_status ON agent_capability_tokens(status)"
    ))


def downgrade() -> None:
    op.get_bind().execute(text("DROP TABLE IF EXISTS agent_capability_tokens"))
