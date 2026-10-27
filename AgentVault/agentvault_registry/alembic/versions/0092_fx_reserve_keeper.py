"""0092 — FX-reserve peg keeper config (cross-frame FX auto-peg, 2026-06-17).

Adds the single-row config table for the leader-elected `fx_reserve_keeper` worker, which
holds each reserve frame's `@fx_reserve` (the AMM pool that defines the cross-frame rate)
within a [min, target, max] band — RATIO-PEG (tracking frames derive target from the anchor
reserve), MOVE-ONLY (treasury <-> reserve, Δ-neutral; never auto-mints). Default OFF / opt-in
(also gated by env FX_RESERVE_KEEPER_ENABLED). FX-Desk editable.

IDEMPOTENT — migration_bridge.py resets alembic_version to 0001_squash on every container
boot, so every post-squash migration REPLAYS. All raw SQL is `IF NOT EXISTS` / `ON CONFLICT`.
"""
from alembic import op
from sqlalchemy import text

revision: str = "0092_fx_reserve_keeper"
down_revision: str = "0091_gateway_credits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # ── single-row keeper config (id fixed to 'singleton'); default OFF / opt-in ──
    bind.execute(text(
        """
        CREATE TABLE IF NOT EXISTS fx_reserve_keeper_config (
            id                  VARCHAR(32)    PRIMARY KEY DEFAULT 'singleton',
            enabled             BOOLEAN        NOT NULL DEFAULT false,
            anchor_currency     VARCHAR(16)    NOT NULL DEFAULT 'AVT',
            ratio_vs_anchor     NUMERIC(36,18) NOT NULL DEFAULT 1,
            target_float        NUMERIC(36,18) NOT NULL DEFAULT 0,
            min_float           NUMERIC(36,18) NOT NULL DEFAULT 0,
            max_float           NUMERIC(36,18) NOT NULL DEFAULT 0,
            deadband_pct        NUMERIC(8,6)   NOT NULL DEFAULT 0.05,
            source              VARCHAR(32)    NOT NULL DEFAULT 'treasury',
            max_move_per_cycle  NUMERIC(36,18) NOT NULL DEFAULT 0,
            check_interval_sec  INTEGER        NOT NULL DEFAULT 60,
            operator_mode       VARCHAR(16)    NOT NULL DEFAULT 'worker',
            updated_at          TIMESTAMPTZ    DEFAULT now(),
            updated_by          VARCHAR(255)
        )
        """
    ))
    bind.execute(text(
        "INSERT INTO fx_reserve_keeper_config (id) VALUES ('singleton') ON CONFLICT (id) DO NOTHING"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("DROP TABLE IF EXISTS fx_reserve_keeper_config"))
