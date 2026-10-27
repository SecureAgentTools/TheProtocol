"""0096 — AGORA gateway-float keeper config (gateway solvency, 2026-06-19).

Adds the single-row config table for the leader-elected `gateway_float_keeper` worker, which
keeps each venue frame's passport gateway (`did:theprotocol:agora-gateway-<ccy>`) solvent —
`gateway_liquid >= outstanding_repat_obligations + buffer` — MOVE-ONLY treasury→gateway via the
reward-funding waterfall (Δ-neutral; never auto-mints). Default OFF / opt-in (also gated by env
GATEWAY_KEEPER_ENABLED + EXCHANGE_PASSPORT_ENABLED). Pairs with the sweeper repat-reservation.

IDEMPOTENT — migration_bridge.py resets alembic_version to 0001_squash on every container boot,
so every post-squash migration REPLAYS. All raw SQL is `IF NOT EXISTS` / `ON CONFLICT`.
"""
from alembic import op
from sqlalchemy import text

revision: str = "0096_gateway_float_keeper"
down_revision: str = "0095_widen_exchange_flag_value"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # ── single-row keeper config (id fixed to 'singleton'); default OFF / opt-in ──
    bind.execute(text(
        """
        CREATE TABLE IF NOT EXISTS gateway_float_keeper_config (
            id                  VARCHAR(32)    PRIMARY KEY DEFAULT 'singleton',
            enabled             BOOLEAN        NOT NULL DEFAULT false,
            buffer              NUMERIC(36,18) NOT NULL DEFAULT 0,
            deadband_pct        NUMERIC(8,6)   NOT NULL DEFAULT 0.05,
            max_move_per_cycle  NUMERIC(36,18) NOT NULL DEFAULT 0,
            source              VARCHAR(32)    NOT NULL DEFAULT 'treasury',
            check_interval_sec  INTEGER        NOT NULL DEFAULT 60,
            operator_mode       VARCHAR(16)    NOT NULL DEFAULT 'worker',
            updated_at          TIMESTAMPTZ    DEFAULT now(),
            updated_by          VARCHAR(255)
        )
        """
    ))
    bind.execute(text(
        "INSERT INTO gateway_float_keeper_config (id) VALUES ('singleton') ON CONFLICT (id) DO NOTHING"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("DROP TABLE IF EXISTS gateway_float_keeper_config"))
