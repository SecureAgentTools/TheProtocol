"""0088 — AGORA core: organization stock exchange (listings/IPO, CLOB, dividends, participants).

AGORA = the org equity exchange (STRATEGY_2026-06-12_AGORA_LOCKED_IMPLEMENTATION.md).
Shares are a registry-local asset ledger — they NEVER touch the TEG; every AVT/BVT leg
moves through the TEG escrow account `teg:system:exchange_escrow` via the admin mover,
so the supply invariant is untouched by construction (transit-neutral transfers only).

Tables (all venue-local; participant columns are PLAIN DID STRINGS by doctrine —
foreign agents must remain representable, so NO FK to the local agents table):
  - exchange_listings        : one row per listed org (ticker, shares, IPO, fees, status)
  - org_share_positions      : the share ledger (qty/locked_qty per DID per listing)
  - exchange_orders          : CLOB orders (funding->open lifecycle; escrow accounting)
  - exchange_trades          : immutable tape (seq BIGSERIAL); settle_status drives worker
  - exchange_dividends/_legs : declared dividends + per-holder payout legs
  - exchange_ipo_purchases   : fixed-price primary sales
  - exchange_participants    : compliance registry (D25 — "no anonymous ghosts"):
                               owner-developer identity per trading DID; local agents
                               auto-verify, foreign agents verify via DevCard (§9)
  - exchange_flags           : venue-level kill switches (global_halt)

Also seeds the 8 AGORA event-emission-policy rows (registry-emitted, skip_in_projection —
the money trail is the TEG legs' LedgerBalanceChanged stream, not these domain events).

IDEMPOTENT — migration_bridge.py resets alembic_version to 0001_squash on every container
boot, so every post-squash migration REPLAYS. All raw SQL is `IF NOT EXISTS` /
`ON CONFLICT DO NOTHING`. Forward-only downgrade per house style.
"""
from alembic import op
from sqlalchemy import text

revision: str = "0088_agora_core"
down_revision: str = "0087_smartsend_backend"
branch_labels = None
depends_on = None


# Single source of truth: the replay gate (/tmp proof harness) executes this exact list
# against a scratch PG twice; upgrade() executes it via alembic. Keep pure SQL strings.
STATEMENTS: list[str] = [
    # ------------------------------------------------------------------ listings
    """
    CREATE TABLE IF NOT EXISTS exchange_listings (
        id VARCHAR(36) PRIMARY KEY,
        organization_id VARCHAR(255) NOT NULL REFERENCES organizations(id),
        symbol VARCHAR(8) NOT NULL UNIQUE,
        display_name VARCHAR(255) NOT NULL,
        total_shares BIGINT NOT NULL CHECK (total_shares > 0),
        treasury_agent_did VARCHAR(120) NOT NULL,
        currency VARCHAR(8) NOT NULL DEFAULT 'AVT',
        ipo_price NUMERIC(36,18) NOT NULL CHECK (ipo_price > 0),
        ipo_float BIGINT NOT NULL CHECK (ipo_float >= 0),
        ipo_sold BIGINT NOT NULL DEFAULT 0 CHECK (ipo_sold >= 0),
        fee_bps INTEGER NOT NULL DEFAULT 30 CHECK (fee_bps >= 0 AND fee_bps <= 100),
        fee_org_split_bps INTEGER NOT NULL DEFAULT 6667 CHECK (fee_org_split_bps >= 0 AND fee_org_split_bps <= 10000),
        tick NUMERIC(36,18) NOT NULL DEFAULT 0.01 CHECK (tick > 0),
        band_pct INTEGER NOT NULL DEFAULT 25 CHECK (band_pct > 0 AND band_pct <= 100),
        approved BOOLEAN NOT NULL DEFAULT FALSE,
        status VARCHAR(12) NOT NULL DEFAULT 'ipo'
            CHECK (status IN ('ipo', 'trading', 'halted', 'delisted')),
        created_by_dev INTEGER NOT NULL,
        listing_fee_paid BOOLEAN NOT NULL DEFAULT FALSE,
        listing_fee_parked BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT ck_exchange_listings_float_le_total CHECK (ipo_float <= total_shares),
        CONSTRAINT ck_exchange_listings_sold_le_float CHECK (ipo_sold <= ipo_float)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_exchange_listings_org ON exchange_listings (organization_id)",
    "CREATE INDEX IF NOT EXISTS ix_exchange_listings_status ON exchange_listings (status)",
    # ------------------------------------------------------------------ share ledger
    """
    CREATE TABLE IF NOT EXISTS org_share_positions (
        id BIGSERIAL PRIMARY KEY,
        listing_id VARCHAR(36) NOT NULL REFERENCES exchange_listings(id),
        agent_did VARCHAR(120) NOT NULL,
        qty BIGINT NOT NULL DEFAULT 0,
        locked_qty BIGINT NOT NULL DEFAULT 0,
        avg_cost NUMERIC(36,18) NOT NULL DEFAULT 0,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_org_share_positions_listing_agent UNIQUE (listing_id, agent_did),
        CONSTRAINT ck_org_share_positions_locked CHECK (locked_qty >= 0 AND qty >= locked_qty)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_org_share_positions_agent ON org_share_positions (agent_did)",
    # ------------------------------------------------------------------ orders (the book)
    """
    CREATE TABLE IF NOT EXISTS exchange_orders (
        id VARCHAR(36) PRIMARY KEY,
        listing_id VARCHAR(36) NOT NULL REFERENCES exchange_listings(id),
        agent_did VARCHAR(120) NOT NULL,
        side VARCHAR(4) NOT NULL CHECK (side IN ('buy', 'sell')),
        order_type VARCHAR(6) NOT NULL CHECK (order_type IN ('limit', 'market')),
        price NUMERIC(36,18) CHECK (price IS NULL OR price > 0),
        qty BIGINT NOT NULL CHECK (qty > 0),
        remaining BIGINT NOT NULL CHECK (remaining >= 0),
        escrow_amount NUMERIC(36,18) NOT NULL DEFAULT 0 CHECK (escrow_amount >= 0),
        escrow_refunded NUMERIC(36,18) NOT NULL DEFAULT 0 CHECK (escrow_refunded >= 0),
        matched_notional NUMERIC(36,18) NOT NULL DEFAULT 0 CHECK (matched_notional >= 0),
        status VARCHAR(10) NOT NULL DEFAULT 'funding'
            CHECK (status IN ('funding', 'open', 'partial', 'filled', 'cancelled', 'expired', 'rejected')),
        client_order_id VARCHAR(64),
        ttl_expires_at TIMESTAMPTZ,
        reject_reason VARCHAR(255),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT ck_exchange_orders_remaining_le_qty CHECK (remaining <= qty)
    )
    """,
    # The book: best-price-first scans per listing/side over resting orders.
    "CREATE INDEX IF NOT EXISTS ix_exchange_orders_book ON exchange_orders (listing_id, side, status, price, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_exchange_orders_agent ON exchange_orders (agent_did, status)",
    "CREATE INDEX IF NOT EXISTS ix_exchange_orders_funding ON exchange_orders (status, created_at) WHERE status = 'funding'",
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_exchange_orders_client_ref
        ON exchange_orders (listing_id, agent_did, client_order_id)
        WHERE client_order_id IS NOT NULL
    """,
    # ------------------------------------------------------------------ trades (the tape)
    """
    CREATE TABLE IF NOT EXISTS exchange_trades (
        id VARCHAR(36) PRIMARY KEY,
        seq BIGSERIAL,
        listing_id VARCHAR(36) NOT NULL REFERENCES exchange_listings(id),
        buy_order_id VARCHAR(36) NOT NULL REFERENCES exchange_orders(id),
        sell_order_id VARCHAR(36) NOT NULL REFERENCES exchange_orders(id),
        buyer_did VARCHAR(120) NOT NULL,
        seller_did VARCHAR(120) NOT NULL,
        price NUMERIC(36,18) NOT NULL CHECK (price > 0),
        qty BIGINT NOT NULL CHECK (qty > 0),
        notional NUMERIC(36,18) NOT NULL CHECK (notional >= 0),
        fee_total NUMERIC(36,18) NOT NULL DEFAULT 0,
        fee_org NUMERIC(36,18) NOT NULL DEFAULT 0,
        fee_proto NUMERIC(36,18) NOT NULL DEFAULT 0,
        settle_status VARCHAR(20) NOT NULL DEFAULT 'pending_settlement'
            CHECK (settle_status IN ('pending_settlement', 'settled', 'settle_failed')),
        settle_attempts INTEGER NOT NULL DEFAULT 0,
        settle_tx_refs JSONB,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        settled_at TIMESTAMPTZ
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_exchange_trades_seq ON exchange_trades (seq)",
    "CREATE INDEX IF NOT EXISTS ix_exchange_trades_listing_seq ON exchange_trades (listing_id, seq DESC)",
    "CREATE INDEX IF NOT EXISTS ix_exchange_trades_pending ON exchange_trades (settle_status, created_at) WHERE settle_status = 'pending_settlement'",
    "CREATE INDEX IF NOT EXISTS ix_exchange_trades_buyer ON exchange_trades (buyer_did, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_exchange_trades_seller ON exchange_trades (seller_did, created_at)",
    # ------------------------------------------------------------------ dividends
    """
    CREATE TABLE IF NOT EXISTS exchange_dividends (
        id VARCHAR(36) PRIMARY KEY,
        listing_id VARCHAR(36) NOT NULL REFERENCES exchange_listings(id),
        epoch INTEGER NOT NULL,
        per_share NUMERIC(36,18) NOT NULL CHECK (per_share > 0),
        snapshot_seq BIGINT NOT NULL DEFAULT 0,
        total_amount NUMERIC(36,18) NOT NULL DEFAULT 0,
        pot_funded BOOLEAN NOT NULL DEFAULT FALSE,
        status VARCHAR(10) NOT NULL DEFAULT 'declared'
            CHECK (status IN ('declared', 'paying', 'paid', 'failed')),
        declared_by_dev INTEGER NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        paid_at TIMESTAMPTZ,
        CONSTRAINT uq_exchange_dividends_listing_epoch UNIQUE (listing_id, epoch)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS exchange_dividend_legs (
        id BIGSERIAL PRIMARY KEY,
        dividend_id VARCHAR(36) NOT NULL REFERENCES exchange_dividends(id),
        agent_did VARCHAR(120) NOT NULL,
        qty_at_snapshot BIGINT NOT NULL CHECK (qty_at_snapshot > 0),
        amount NUMERIC(36,18) NOT NULL CHECK (amount >= 0),
        status VARCHAR(10) NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending', 'paid', 'failed')),
        paid_at TIMESTAMPTZ,
        CONSTRAINT uq_exchange_dividend_legs UNIQUE (dividend_id, agent_did)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_exchange_dividend_legs_pending ON exchange_dividend_legs (status) WHERE status = 'pending'",
    # ------------------------------------------------------------------ IPO primary sales
    """
    CREATE TABLE IF NOT EXISTS exchange_ipo_purchases (
        id VARCHAR(36) PRIMARY KEY,
        listing_id VARCHAR(36) NOT NULL REFERENCES exchange_listings(id),
        agent_did VARCHAR(120) NOT NULL,
        qty BIGINT NOT NULL CHECK (qty > 0),
        amount NUMERIC(36,18) NOT NULL CHECK (amount > 0),
        status VARCHAR(10) NOT NULL DEFAULT 'funding'
            CHECK (status IN ('funding', 'allocated', 'settled', 'refunding', 'refunded', 'rejected')),
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_exchange_ipo_purchases_listing ON exchange_ipo_purchases (listing_id, status)",
    "CREATE INDEX IF NOT EXISTS ix_exchange_ipo_purchases_open ON exchange_ipo_purchases (status, created_at) WHERE status IN ('funding', 'allocated')",
    # ------------------------------------------------------------------ participants (D25 compliance registry)
    """
    CREATE TABLE IF NOT EXISTS exchange_participants (
        id BIGSERIAL PRIMARY KEY,
        agent_did VARCHAR(120) NOT NULL UNIQUE,
        home_registry VARCHAR(128) NOT NULL DEFAULT 'local',
        trust_domain VARCHAR(128),
        owner_dev_ref VARCHAR(128),
        owner_dev_name VARCHAR(255),
        owner_dev_contact VARCHAR(255),
        verification_source VARCHAR(16) NOT NULL DEFAULT 'local'
            CHECK (verification_source IN ('local', 'dev_card')),
        compliance_status VARCHAR(10) NOT NULL DEFAULT 'pending'
            CHECK (compliance_status IN ('verified', 'pending', 'blocked')),
        kyc JSONB,
        first_seen TIMESTAMPTZ NOT NULL DEFAULT now(),
        verified_at TIMESTAMPTZ,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_exchange_participants_status ON exchange_participants (compliance_status)",
    # ------------------------------------------------------------------ venue flags
    """
    CREATE TABLE IF NOT EXISTS exchange_flags (
        key VARCHAR(64) PRIMARY KEY,
        value VARCHAR(255) NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "INSERT INTO exchange_flags (key, value) VALUES ('global_halt', 'false') ON CONFLICT (key) DO NOTHING",
]

# AGORA domain events: registry-emitted audit/UX trail only. The money trail is the
# TEG legs' LedgerBalanceChanged stream, so every row is skip_in_projection=true.
_AGORA_EVENT_POLICIES = [
    "ExchangeListingCreated",
    "ExchangeListingApproved",
    "ExchangeOrderPlaced",
    "ExchangeOrderCancelled",
    "ExchangeTradeExecuted",
    "ExchangeDividendDeclared",
    "ExchangeDividendPaid",
    "ExchangeListingHalted",
]
_POLICY_DESC = "AGORA exchange domain event (audit/UX trail; money counted via TEG LedgerBalanceChanged) [0088]"
STATEMENTS += [
    f"""
    INSERT INTO event_emission_policies
        (event_type, emit_from_teg, emit_from_registry, skip_in_projection, description, updated_at)
    VALUES ('{evt}', false, true, true, '{_POLICY_DESC}', NOW())
    ON CONFLICT (event_type) DO NOTHING
    """
    for evt in _AGORA_EVENT_POLICIES
]


def upgrade() -> None:
    for stmt in STATEMENTS:
        op.execute(text(stmt))


def downgrade() -> None:
    # Forward-only (matches the squash-replay model); tables are additive.
    pass
