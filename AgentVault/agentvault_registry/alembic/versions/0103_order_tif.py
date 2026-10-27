"""0103 — P5.1 advanced order types: TIF (IOC/FOK) + post-only (2026-06-22).

Adds time-in-force + post-only flags to exchange_orders. Both are opt-in PER
ORDER (absent ⇒ tif='gtc' / post_only=false ⇒ today's exact behavior), so NO
feature flag is needed and existing rows are unaffected. Purely additive +
idempotent + Δ-NEUTRAL: these flags only change WHETHER/HOW MUCH of an order
rests or whether it is accepted — they never create a new money flow. A BUY
still escrows the full qty·cap up front; IOC remainder cancels and refunds via
the existing refund_terminal_buys worker path (escrow → buyer), FOK / post-only
reject pre-escrow.

  exchange_orders.tif        VARCHAR(4) NOT NULL DEFAULT 'gtc'   (gtc|ioc|fok)
  exchange_orders.post_only  BOOLEAN    NOT NULL DEFAULT false

DEFERRED (noted in SPEC §5.1, NOT built this pass): stop / stop-limit
(stop_price + trigger scan) and iceberg (display_qty slice refill).

Replayed by migration_bridge on every boot so ops / new-deploys auto-cover.
"""
from alembic import op
from sqlalchemy import text

revision: str = "0103_order_tif"
down_revision: str = "0102_maker_rebate"
branch_labels = None
depends_on = None


def upgrade() -> None:
    b = op.get_bind()
    b.execute(text("ALTER TABLE exchange_orders ADD COLUMN IF NOT EXISTS tif VARCHAR(4) NOT NULL DEFAULT 'gtc'"))
    b.execute(text("ALTER TABLE exchange_orders ADD COLUMN IF NOT EXISTS post_only BOOLEAN NOT NULL DEFAULT false"))


def downgrade() -> None:
    b = op.get_bind()
    b.execute(text("ALTER TABLE exchange_orders DROP COLUMN IF EXISTS post_only"))
    b.execute(text("ALTER TABLE exchange_orders DROP COLUMN IF EXISTS tif"))
