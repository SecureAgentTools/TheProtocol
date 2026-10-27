"""0108 — IRONKEY L3-D2: agent_delegation_grants (on-behalf-of delegation) (2026-07-04).

Additive table: a principal (dev/org/agent) delegates a subset of permissions TO an agent,
consulted ONLY when the presented agent token carries a matching ``act.sub`` claim. NO
existing data touched → **Δ-irrelevant** (authorization only ever DENIES pre-escrow). Inert
until ``AGENT_DELEGATION_MODE`` flips to shadow/enforce.

IDEMPOTENT — migration_bridge re-stamps alembic_version to 0001_squash every boot, so this
REPLAYS. All DDL is IF NOT EXISTS. Mirrors 0107.
"""
from alembic import op
from sqlalchemy import text

revision: str = "0108_agent_delegation"
down_revision: str = "0107_agent_ironkey"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS agent_delegation_grants (
            id BIGSERIAL PRIMARY KEY,
            principal_type TEXT NOT NULL,
            principal_ref TEXT NOT NULL,
            delegate_agent_did TEXT NOT NULL REFERENCES agents(did) ON DELETE CASCADE,
            permissions TEXT[] NOT NULL DEFAULT '{}',
            may_redelegate BOOLEAN NOT NULL DEFAULT FALSE,
            max_depth SMALLINT NOT NULL DEFAULT 1,
            granted_by_dev_id INTEGER NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at TIMESTAMPTZ NULL,
            revoked_at TIMESTAMPTZ NULL,
            revoke_reason TEXT NULL,
            CONSTRAINT ck_deleg_principal_type CHECK (principal_type IN ('dev','org','agent','service')),
            CONSTRAINT uq_agent_delegation UNIQUE (principal_type, principal_ref, delegate_agent_did)
        )
    """))
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_agent_deleg_delegate "
        "ON agent_delegation_grants(delegate_agent_did) WHERE revoked_at IS NULL"
    ))
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_agent_deleg_principal "
        "ON agent_delegation_grants(principal_ref)"
    ))


def downgrade() -> None:
    op.get_bind().execute(text("DROP TABLE IF EXISTS agent_delegation_grants"))
