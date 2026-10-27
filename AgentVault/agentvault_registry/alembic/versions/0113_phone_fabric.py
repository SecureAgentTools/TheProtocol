"""0113 — PHONE FABRIC: capability-gated agent computer-use (2026-07-07).

Additive-only. Three tables backing agent phone-sessions (gated PHONE_FABRIC_ENABLED,
default OFF; backend mock by default). NO existing table touched, NO money path →
**Δ-irrelevant**: session METERING is a debit on the L4 capability token's own budget
counter (agent_capability_tokens.budget_spent), a deny-only pre-escrow control — it
moves no AVT. Any real per-session AVT charge (later) rides the existing /teg/transfer.

IDEMPOTENT — replays every boot via migration_bridge. All DDL IF NOT EXISTS. Chains 0112.
"""
from alembic import op
from sqlalchemy import text

revision: str = "0113_phone_fabric"
down_revision: str = "0112_device_push_registrations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # A leased phone instance (mock=synthetic/infinite; redroid=a real container).
    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS phone_pool_instances (
            id            SERIAL PRIMARY KEY,
            backend       VARCHAR(16) NOT NULL DEFAULT 'mock',
            handle        VARCHAR(120) NOT NULL,          -- adb endpoint / mock id
            status        VARCHAR(16) NOT NULL DEFAULT 'idle',   -- idle|leased|down
            leased_by     VARCHAR(120),                   -- session id holding it
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_phone_pool_backend_handle UNIQUE (backend, handle)
        )
    """))

    # One agent phone session, bound to the capability token that authorized it.
    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS phone_sessions (
            id                 VARCHAR(40) PRIMARY KEY,    -- pfs_<hex>
            agent_did          VARCHAR(120) NOT NULL,
            capability_token_id INTEGER,                   -- agent_capability_tokens.id
            backend            VARCHAR(16) NOT NULL DEFAULT 'mock',
            instance_id        INTEGER,                    -- phone_pool_instances.id
            status             VARCHAR(16) NOT NULL DEFAULT 'active',  -- active|ended|revoked|expired
            allowed_apps       JSONB,                      -- caveat snapshot at start
            max_actions        INTEGER,
            actions_used       INTEGER NOT NULL DEFAULT 0,
            no_screenshot      BOOLEAN NOT NULL DEFAULT FALSE,
            budget_currency    VARCHAR(12),
            budget_spent       NUMERIC(30,10) NOT NULL DEFAULT 0,   -- audit mirror of token debits
            current_app        VARCHAR(120),
            current_screen     VARCHAR(120),
            started_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at         TIMESTAMPTZ,
            ended_at           TIMESTAMPTZ,
            end_reason         VARCHAR(40)
        )
    """))
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_phone_sessions_agent ON phone_sessions (agent_did)"
    ))
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_phone_sessions_active "
        "ON phone_sessions (status) WHERE status = 'active'"
    ))

    # Append-only action audit — every tap/type/observe on a session.
    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS phone_session_actions (
            id            BIGSERIAL PRIMARY KEY,
            session_id    VARCHAR(40) NOT NULL REFERENCES phone_sessions(id) ON DELETE CASCADE,
            seq           INTEGER NOT NULL,
            action_type   VARCHAR(24) NOT NULL,           -- tap|type|swipe|key|launch|back|home|observe
            target        VARCHAR(240),
            payload       JSONB,
            cost          NUMERIC(30,10) NOT NULL DEFAULT 0,
            outcome       VARCHAR(16) NOT NULL DEFAULT 'ok',   -- ok|denied|error
            detail        TEXT,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_phone_actions_session ON phone_session_actions (session_id, seq)"
    ))


def downgrade() -> None:
    # Additive-only doctrine: leave tables in place (avoids downgrade crash-loop).
    pass
