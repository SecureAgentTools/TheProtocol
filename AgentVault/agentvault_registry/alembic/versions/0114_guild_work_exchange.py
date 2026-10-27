"""0114 — THE GUILD: agent work exchange (2026-07-07).

Additive-only ORDER BOOK for the agent labor market (gated GUILD_ENABLED, default OFF).
**Δ-irrelevant**: money NEVER lives in these tables — bounties are escrowed on the TEG via the
existing /teg/transfer path (a `@guild_escrow` mover, guildref-tagged, exactly like AGORA's exref),
so every bounty leg is a zero-sum transfer and the supply invariant is untouched. These tables are
the order book + append-only audit only.

IDEMPOTENT — replays every boot via migration_bridge. All DDL IF NOT EXISTS. Chains 0113.
"""
from alembic import op
from sqlalchemy import text

revision: str = "0114_guild_work_exchange"
down_revision: str = "0113_phone_fabric"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # A posted task (work order). Money is escrowed on the TEG, referenced by escrow_ref.
    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS guild_work_orders (
            id             VARCHAR(40) PRIMARY KEY,             -- gwo_<hex>
            poster_did     VARCHAR(120) NOT NULL,
            title          VARCHAR(200) NOT NULL,
            spec           TEXT,                                -- the task description / acceptance criteria
            bounty         NUMERIC(30,10) NOT NULL,
            currency       VARCHAR(12) NOT NULL,
            fee_bps        INTEGER NOT NULL DEFAULT 0,          -- protocol fee (basis points) taken on settle
            status         VARCHAR(20) NOT NULL DEFAULT 'open', -- open|awarded|submitted|verified|settled|disputed|refunded|cancelled|expired
            required_skills JSONB,                              -- optional tag filter
            min_reputation NUMERIC(10,4),                       -- optional gate on bidders
            deadline       TIMESTAMPTZ,                         -- bidding/award deadline
            awarded_bid_id INTEGER,
            worker_did     VARCHAR(120),
            escrow_ref     VARCHAR(80),                         -- guildref:{id} — the TEG escrow tag
            deliverable    JSONB,                               -- worker submission (uri/text/hash + optional phone_session_id)
            dispute_id     VARCHAR(80),                         -- link to the dispute system when contested
            fee_charged    NUMERIC(30,10),
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            awarded_at     TIMESTAMPTZ,
            submitted_at   TIMESTAMPTZ,
            settled_at     TIMESTAMPTZ
        )
    """))
    bind.execute(text("CREATE INDEX IF NOT EXISTS idx_guild_orders_status ON guild_work_orders (status)"))
    bind.execute(text("CREATE INDEX IF NOT EXISTS idx_guild_orders_poster ON guild_work_orders (poster_did)"))
    bind.execute(text("CREATE INDEX IF NOT EXISTS idx_guild_orders_worker ON guild_work_orders (worker_did)"))
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_guild_orders_open ON guild_work_orders (status) WHERE status = 'open'"
    ))

    # A bid on an open order.
    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS guild_bids (
            id           SERIAL PRIMARY KEY,
            order_id     VARCHAR(40) NOT NULL REFERENCES guild_work_orders(id) ON DELETE CASCADE,
            bidder_did   VARCHAR(120) NOT NULL,
            price        NUMERIC(30,10) NOT NULL,      -- <= bounty
            eta_seconds  INTEGER,
            pitch        TEXT,
            reputation   NUMERIC(10,4),                -- snapshot at bid time (for ranking)
            status       VARCHAR(16) NOT NULL DEFAULT 'open',   -- open|awarded|released|withdrawn
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_guild_bid_once UNIQUE (order_id, bidder_did)   -- one live bid per agent per order
        )
    """))
    bind.execute(text("CREATE INDEX IF NOT EXISTS idx_guild_bids_order ON guild_bids (order_id, status)"))

    # Append-only lifecycle audit.
    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS guild_order_events (
            id          BIGSERIAL PRIMARY KEY,
            order_id    VARCHAR(40) NOT NULL REFERENCES guild_work_orders(id) ON DELETE CASCADE,
            seq         INTEGER NOT NULL,
            event_type  VARCHAR(24) NOT NULL,          -- posted|bid|awarded|submitted|verified|disputed|settled|refunded|cancelled|expired
            actor_did   VARCHAR(120),
            payload     JSONB,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))
    bind.execute(text("CREATE INDEX IF NOT EXISTS idx_guild_events_order ON guild_order_events (order_id, seq)"))


def downgrade() -> None:
    # Additive-only doctrine: leave tables in place (avoids downgrade crash-loop).
    pass
