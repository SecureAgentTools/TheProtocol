"""0107 — IRONKEY agent authorization: agent_role_grants + agent_spend_policies (2026-07-03).

Additive tables for agent-side RBAC (roles → permissions) + a per-agent spend policy
(money caveats, L2). NO existing table data is touched → **Δ-irrelevant** (authorization
only ever DENIES pre-escrow; it never moves money). Backfills the `legacy-full` role for
every existing agent so the rollout is byte-inert until `AGENT_RBAC_MODE` flips to
shadow/enforce.

IDEMPOTENT — migration_bridge.py resets alembic_version to 0001_squash on every container
boot, so every post-squash migration REPLAYS. All DDL is `IF NOT EXISTS`; the backfill is
`ON CONFLICT DO NOTHING` (unique per agent_did+grant_type+value). Mirrors 0106/0094.
"""
from alembic import op
from sqlalchemy import text

revision: str = "0107_agent_ironkey"
down_revision: str = "0106_market_card"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # --- agent_role_grants: one row per (agent, role|permission) grant --------
    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS agent_role_grants (
            id BIGSERIAL PRIMARY KEY,
            agent_did TEXT NOT NULL REFERENCES agents(did) ON DELETE CASCADE,
            grant_type TEXT NOT NULL DEFAULT 'role',
            value TEXT NOT NULL,
            granted_by_dev_id INTEGER NULL,
            granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at TIMESTAMPTZ NULL,
            CONSTRAINT ck_agent_role_grant_type CHECK (grant_type IN ('role','permission')),
            CONSTRAINT uq_agent_role_grant UNIQUE (agent_did, grant_type, value)
        )
    """))
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_agent_role_grants_agent_did "
        "ON agent_role_grants(agent_did)"
    ))
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_agent_role_grants_expires "
        "ON agent_role_grants(expires_at) WHERE expires_at IS NOT NULL"
    ))

    # --- agent_spend_policies: per-agent money caveats (L2) -------------------
    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS agent_spend_policies (
            agent_did TEXT PRIMARY KEY REFERENCES agents(did) ON DELETE CASCADE,
            max_per_tx NUMERIC(36,18) NULL,
            max_per_day NUMERIC(36,18) NULL,
            allowed_currencies TEXT[] NULL,
            counterparty_mode TEXT NOT NULL DEFAULT 'any',
            counterparty_allow TEXT[] NULL,
            require_approval_above NUMERIC(36,18) NULL,
            updated_by_dev_id INTEGER NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_agent_spend_cp_mode
                CHECK (counterparty_mode IN ('any','same_registry','allowlist'))
        )
    """))

    # --- backfill legacy-full for every existing agent (grandfather) ----------
    # Byte-inert: with AGENT_RBAC_MODE=off the grants are never read; the ratchet
    # to least-privilege replaces legacy-full explicitly, later + observably.
    bind.execute(text("""
        INSERT INTO agent_role_grants (agent_did, grant_type, value)
        SELECT did, 'role', 'legacy-full' FROM agents
        ON CONFLICT (agent_did, grant_type, value) DO NOTHING
    """))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("DROP TABLE IF EXISTS agent_spend_policies"))
    bind.execute(text("DROP TABLE IF EXISTS agent_role_grants"))
