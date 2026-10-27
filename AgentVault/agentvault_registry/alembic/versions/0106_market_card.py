"""0106 — federated_stock_cards.{market_json, market_epoch} (Federated Market Card, 2026-06-25).

Additive columns carrying an ADVISORY coarse price/sparkline block alongside the
cached catalog ({SYMBOL: {last, change_24h_pct, spark[≤24], as_of}}). NOT part of the
signed catalog digest (cosmetic — a forged sparkline can't move money; trading still
settles via passport + escrow + signed DevCard). `market_epoch` = floor(now/EPOCH)
advertised on the peer's stock_card link; the consumer re-fetches the stock card when
it advances (the catalog digest is trade-invariant, so it alone never would). Touches
no existing table data → Δ-irrelevant (read-only metadata).

IDEMPOTENT — migration_bridge.py resets alembic_version to 0001_squash on every
container boot, so every post-squash migration REPLAYS. All raw SQL is `IF NOT EXISTS`
(mirrors 0094_stock_card_via_fanout.py).
"""
from alembic import op
from sqlalchemy import text

revision: str = "0106_market_card"
down_revision: str = "0105_stop_iceberg"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text(
        "ALTER TABLE federated_stock_cards ADD COLUMN IF NOT EXISTS market_json JSON"
    ))
    bind.execute(text(
        "ALTER TABLE federated_stock_cards ADD COLUMN IF NOT EXISTS market_epoch BIGINT"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("ALTER TABLE federated_stock_cards DROP COLUMN IF EXISTS market_epoch"))
    bind.execute(text("ALTER TABLE federated_stock_cards DROP COLUMN IF EXISTS market_json"))
