"""0104 — P5.6 circuit-breaker: per-listing volatility auto-halt (2026-06-23).

Adds the breaker config + rolling-reference state to exchange_listings. cb_pct=0
⇒ breaker OFF for that listing (default = today's exact behaviour), so NO existing
row changes behaviour and NO schema-level flag is required (the runtime master gate
is env EXCHANGE_CB_ENABLED). Purely additive + idempotent + Δ-NEUTRAL: the breaker
only flips listing.status (trading↔halted) + tracks a reference price/time — it
never moves money or shares.

  exchange_listings.cb_pct          INTEGER NOT NULL DEFAULT 0   (move threshold, bps; 0=off)
  exchange_listings.cb_ref_price    NUMERIC(36,18) NULL          (rolling reference price)
  exchange_listings.cb_ref_at       TIMESTAMPTZ NULL             (when the reference was set)
  exchange_listings.cb_halted_until TIMESTAMPTZ NULL             (cb-halt expiry; place_order lazy-resumes)

Replayed by migration_bridge on every boot so ops / new-deploys auto-cover.
"""
from alembic import op
from sqlalchemy import text

revision: str = "0104_circuit_breaker"
down_revision: str = "0103_order_tif"
branch_labels = None
depends_on = None


def upgrade() -> None:
    b = op.get_bind()
    b.execute(text("ALTER TABLE exchange_listings ADD COLUMN IF NOT EXISTS cb_pct INTEGER NOT NULL DEFAULT 0"))
    b.execute(text("ALTER TABLE exchange_listings ADD COLUMN IF NOT EXISTS cb_ref_price NUMERIC(36,18)"))
    b.execute(text("ALTER TABLE exchange_listings ADD COLUMN IF NOT EXISTS cb_ref_at TIMESTAMPTZ"))
    b.execute(text("ALTER TABLE exchange_listings ADD COLUMN IF NOT EXISTS cb_halted_until TIMESTAMPTZ"))


def downgrade() -> None:
    b = op.get_bind()
    b.execute(text("ALTER TABLE exchange_listings DROP COLUMN IF EXISTS cb_halted_until"))
    b.execute(text("ALTER TABLE exchange_listings DROP COLUMN IF EXISTS cb_ref_at"))
    b.execute(text("ALTER TABLE exchange_listings DROP COLUMN IF EXISTS cb_ref_price"))
    b.execute(text("ALTER TABLE exchange_listings DROP COLUMN IF EXISTS cb_pct"))
