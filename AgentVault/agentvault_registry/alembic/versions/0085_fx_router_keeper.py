"""0085 — FX router keeper: config + dead-letter ledger (AAA+ op→op FX router liquidity).

The op→op FX route's `@fx_router` is an FX-settlement *suspense* account; `@fx_reserve`
is its funding pool. Under concurrency the booth source-lock (`@fx_router → @fx_reserve`)
can transiently outrun the ingress on the shared balance → `Insufficient balance` → route
fails. A funded, auto-managed suspense account is the AAA+ pattern (nostro liquidity mgmt).

Two single-purpose tables, both per-registry (each reserve frame configures its OWN router):
  - fx_router_keeper_config : single-row watermark config (FX Desk-editable; default OFF).
  - fx_route_dead_letters   : durable record of funds parked by a failed-compensation route,
                              so the keeper can refund the ORIGINAL SENDER, retry-until-settled.

IDEMPOTENT — migration_bridge.py resets alembic_version to 0001_squash on every container
boot, so every post-squash migration REPLAYS. All raw SQL is `IF NOT EXISTS` / `ON CONFLICT`.
"""
from alembic import op
from sqlalchemy import text

revision: str = "0085_fx_router_keeper"
down_revision: str = "0084_api_key_sha256_lookup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # ── single-row keeper config (id fixed to 'singleton'); default OFF / opt-in ──
    bind.execute(text(
        """
        CREATE TABLE IF NOT EXISTS fx_router_keeper_config (
            id                         VARCHAR(32)   PRIMARY KEY DEFAULT 'singleton',
            enabled                    BOOLEAN       NOT NULL DEFAULT false,
            target_float               NUMERIC(36,18) NOT NULL DEFAULT 0,
            min_float                  NUMERIC(36,18) NOT NULL DEFAULT 0,
            max_float                  NUMERIC(36,18) NOT NULL DEFAULT 0,
            source                     VARCHAR(32)   NOT NULL DEFAULT 'treasury',
            check_interval_sec         INTEGER       NOT NULL DEFAULT 60,
            max_move_per_cycle         NUMERIC(36,18) NOT NULL DEFAULT 0,
            dead_letter_refund_enabled BOOLEAN       NOT NULL DEFAULT true,
            dead_letter_max_retries    INTEGER       NOT NULL DEFAULT 8,
            updated_at                 TIMESTAMPTZ   DEFAULT now(),
            updated_by                 VARCHAR(255)
        )
        """
    ))
    bind.execute(text(
        "INSERT INTO fx_router_keeper_config (id) VALUES ('singleton') ON CONFLICT (id) DO NOTHING"
    ))

    # ── durable dead-letter ledger (funds parked at @fx_router by a failed route) ──
    bind.execute(text(
        """
        CREATE TABLE IF NOT EXISTS fx_route_dead_letters (
            id                  VARCHAR(64)   PRIMARY KEY,
            route_id            VARCHAR(64)   NOT NULL,
            origin_did          VARCHAR(120)  NOT NULL,
            origin_teg_id       VARCHAR(120),
            origin_registry_id  VARCHAR(120),
            amount              NUMERIC(36,18) NOT NULL,
            currency            VARCHAR(16)   NOT NULL DEFAULT 'AVT',
            parked_at_did       VARCHAR(120)  NOT NULL,
            phase               VARCHAR(32)   NOT NULL DEFAULT 'pre_conversion',
            status              VARCHAR(24)   NOT NULL DEFAULT 'pending',
            retries             INTEGER       NOT NULL DEFAULT 0,
            last_error          TEXT,
            resolution_tx       VARCHAR(120),
            created_at          TIMESTAMPTZ   NOT NULL DEFAULT now(),
            resolved_at         TIMESTAMPTZ
        )
        """
    ))
    # one dead-letter per route (idempotent recording from the hot path)
    bind.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_fx_route_dead_letters_route_id "
        "ON fx_route_dead_letters (route_id)"
    ))
    # worker scans pending rows
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_fx_route_dead_letters_status "
        "ON fx_route_dead_letters (status)"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("DROP TABLE IF EXISTS fx_route_dead_letters"))
    bind.execute(text("DROP TABLE IF EXISTS fx_router_keeper_config"))
