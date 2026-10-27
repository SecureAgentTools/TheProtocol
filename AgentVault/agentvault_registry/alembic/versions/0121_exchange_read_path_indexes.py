"""0121 — exchange read-path indexes (2026-07-09).

Additive-only. Two covering indexes for the AGORA read path, root-caused from the
frame-c "high error rate" incident (client-timeout disconnects on /exchange/listings
and /.well-known/stock-card.json while frame-c-db sat at ~175% CPU):

  ix_exchange_trades_listing_created
      The sparkline/price-history query (listing_id = $1 AND created_at >= $2
      ORDER BY seq) had no (listing_id, created_at) path — the planner walked
      ix_exchange_trades_seller by created_at and filtered, ~15.5k buffers/call.
      With this index: index-only scan, ~1k buffers (measured 74ms → 12ms).

  ix_exchange_orders_escrow_live
      The venue-wide escrow invariant sum (side = $1 AND escrow_amount > $2 AND
      status NOT IN (...)) was a parallel seq scan over the full 1.1M-row table,
      ~40k buffers/call, running near-constantly (solvency card, invariant checks,
      auditor probes). With this index: index-only scan, ~4k buffers
      (measured 1.65s → 0.32s per worker; stock-card.json 8s → 0.02s).

Both created live on frame-c with CREATE INDEX CONCURRENTLY on 2026-07-09; this
migration makes them durable and carries them to the rest of the fleet on the next
roll. IDEMPOTENT (IF NOT EXISTS), chains 0120. Plain CREATE INDEX here (not
CONCURRENTLY — alembic runs in a txn); on frames where the index already exists
it is a no-op, elsewhere the tables are small enough to build inline at boot.
"""
from alembic import op
from sqlalchemy import text

revision: str = "0121_exchange_read_path_indexes"
down_revision: str = "0120_developer_tos_consent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_exchange_trades_listing_created "
        "ON exchange_trades (listing_id, created_at) INCLUDE (seq, price)"
    ))
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_exchange_orders_escrow_live "
        "ON exchange_orders (side, status) INCLUDE (escrow_amount, matched_notional, escrow_refunded)"
    ))


def downgrade() -> None:
    # Additive-only doctrine: indexes are harmless to keep; drop manually if ever needed.
    pass
