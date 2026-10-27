"""0098 — treasury market-maker config (P2.1, 2026-06-21).

Creates `treasury_mm_config` (one row per listing) for the leader-elected
treasury_market_maker worker (P2.1) — two-sided treasury quoting, default OFF.
Δ-irrelevant (config only; the MM rides place_order → Δ=0). IDEMPOTENT — CREATE TABLE
IF NOT EXISTS (runs once via `alembic upgrade head`; the bridge does NOT replay on
prod single-head DBs).
"""
from alembic import op
from sqlalchemy import text

revision: str = "0098_treasury_mm_config"
down_revision: str = "0097_gateway_credit_rearm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text(
        """
        CREATE TABLE IF NOT EXISTS treasury_mm_config (
            listing_id      VARCHAR(36) PRIMARY KEY REFERENCES exchange_listings(id),
            enabled         BOOLEAN NOT NULL DEFAULT FALSE,
            spread_bps      INTEGER NOT NULL DEFAULT 200,
            quote_qty       BIGINT NOT NULL DEFAULT 100,
            reserve_shares  BIGINT NOT NULL DEFAULT 0,
            cash_floor      NUMERIC(36,18) NOT NULL DEFAULT 0,
            ref_mode        VARCHAR(8) NOT NULL DEFAULT 'last',
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    ))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("DROP TABLE IF EXISTS treasury_mm_config"))
