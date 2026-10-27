"""0102 — P2.2 designated external market-maker + maker rebate (2026-06-22).

Adds the maker-rebate fee leg + designated-MM registration. All money mechanics
are gated behind EXCHANGE_MAKER_REBATE_ENABLED (default off) in the service layer;
this DDL is purely additive + idempotent + Δ-neutral (it stores a fee
*redistribution* slice, never a new money flow — see exchange_service._match).

  exchange_listings.maker_rebate_bps           INTEGER NOT NULL DEFAULT 0
  exchange_listings.rebate_requires_registration BOOLEAN NOT NULL DEFAULT true
  exchange_trades.fee_maker_rebate             NUMERIC(36,18) NOT NULL DEFAULT 0
  exchange_trades.maker_did                    VARCHAR(120)   NULL
  exchange_participants.market_maker           BOOLEAN NOT NULL DEFAULT false
  exchange_market_makers                       new table (one row per listing×MM agent)

Replayed by migration_bridge on every boot so ops / new-deploys auto-cover.
"""
from alembic import op
from sqlalchemy import text

revision: str = "0102_maker_rebate"
down_revision: str = "0101_exchange_proposal_action"
branch_labels = None
depends_on = None


def upgrade() -> None:
    b = op.get_bind()
    # (A) maker rebate economics — listing config + per-trade stamp
    b.execute(text("ALTER TABLE exchange_listings ADD COLUMN IF NOT EXISTS maker_rebate_bps INTEGER NOT NULL DEFAULT 0"))
    b.execute(text("ALTER TABLE exchange_listings ADD COLUMN IF NOT EXISTS rebate_requires_registration BOOLEAN NOT NULL DEFAULT true"))
    b.execute(text("ALTER TABLE exchange_trades ADD COLUMN IF NOT EXISTS fee_maker_rebate NUMERIC(36,18) NOT NULL DEFAULT 0"))
    b.execute(text("ALTER TABLE exchange_trades ADD COLUMN IF NOT EXISTS maker_did VARCHAR(120)"))
    # (B) designated-MM role
    b.execute(text("ALTER TABLE exchange_participants ADD COLUMN IF NOT EXISTS market_maker BOOLEAN NOT NULL DEFAULT false"))
    b.execute(
        text(
            "CREATE TABLE IF NOT EXISTS exchange_market_makers ("
            " id BIGSERIAL PRIMARY KEY,"
            " listing_id VARCHAR(36) NOT NULL REFERENCES exchange_listings(id),"
            " agent_did VARCHAR(120) NOT NULL,"
            " status VARCHAR(16) NOT NULL DEFAULT 'active',"
            " min_uptime_pct INTEGER,"
            " max_spread_bps INTEGER,"
            " granted_by_dev INTEGER NOT NULL,"
            " created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
            " updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
            " CONSTRAINT uq_exchange_market_makers_listing_agent UNIQUE (listing_id, agent_did)"
            ")"
        )
    )
    b.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_exchange_market_makers_listing"
            " ON exchange_market_makers (listing_id, status)"
        )
    )


def downgrade() -> None:
    b = op.get_bind()
    b.execute(text("DROP TABLE IF EXISTS exchange_market_makers"))
    b.execute(text("ALTER TABLE exchange_participants DROP COLUMN IF EXISTS market_maker"))
    b.execute(text("ALTER TABLE exchange_trades DROP COLUMN IF EXISTS maker_did"))
    b.execute(text("ALTER TABLE exchange_trades DROP COLUMN IF EXISTS fee_maker_rebate"))
    b.execute(text("ALTER TABLE exchange_listings DROP COLUMN IF EXISTS rebate_requires_registration"))
    b.execute(text("ALTER TABLE exchange_listings DROP COLUMN IF EXISTS maker_rebate_bps"))
