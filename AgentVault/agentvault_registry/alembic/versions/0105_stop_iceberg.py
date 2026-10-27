"""0105 — P5.1 stop/stop-limit + iceberg columns on exchange_orders (2026-06-24).

Adds the stop trigger + iceberg display columns. Both opt-in per order; absent ⇒ today's
exact behavior (no feature flag) — purely additive + idempotent + Δ-NEUTRAL (an armed stop
escrows up front exactly like a normal order; it only changes WHEN the order matches, never
a new money flow).

  exchange_orders.stop_price   NUMERIC(36,18) NULL   (stop trigger; the order rests 'armed' until last crosses)
  exchange_orders.display_qty  BIGINT NULL           (iceberg visible slice; book-depth display)

Replayed by `alembic upgrade head` on every boot so ops / new-deploys auto-cover.
"""
from alembic import op
from sqlalchemy import text

revision: str = "0105_stop_iceberg"
down_revision: str = "0104_circuit_breaker"
branch_labels = None
depends_on = None


def upgrade() -> None:
    b = op.get_bind()
    b.execute(text("ALTER TABLE exchange_orders ADD COLUMN IF NOT EXISTS stop_price NUMERIC(36,18)"))
    b.execute(text("ALTER TABLE exchange_orders ADD COLUMN IF NOT EXISTS display_qty BIGINT"))
    # widen the status check to admit the stop lifecycle: 'armed' (resting, pre-trigger) + 'triggered'
    b.execute(text("ALTER TABLE exchange_orders DROP CONSTRAINT IF EXISTS exchange_orders_status_check"))
    b.execute(text(
        "ALTER TABLE exchange_orders ADD CONSTRAINT exchange_orders_status_check "
        "CHECK (status IN ('funding','open','partial','filled','cancelled','expired','rejected','armed','triggered'))"
    ))


def downgrade() -> None:
    b = op.get_bind()
    b.execute(text("ALTER TABLE exchange_orders DROP CONSTRAINT IF EXISTS exchange_orders_status_check"))
    b.execute(text(
        "ALTER TABLE exchange_orders ADD CONSTRAINT exchange_orders_status_check "
        "CHECK (status IN ('funding','open','partial','filled','cancelled','expired','rejected'))"
    ))
    b.execute(text("ALTER TABLE exchange_orders DROP COLUMN IF EXISTS display_qty"))
    b.execute(text("ALTER TABLE exchange_orders DROP COLUMN IF EXISTS stop_price"))
