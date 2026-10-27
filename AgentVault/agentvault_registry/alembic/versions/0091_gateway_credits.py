"""0091 — Passport repatriation sub-ledger (§V0064 P2, AGORA_Exchange.md §10).

exchange_gateway_credits: money that lands on the venue GATEWAY for a FOREIGN
DID (dividends, buy refunds) becomes an attributed credit row instead of an
anonymous gateway balance. The settlement worker (batch I) drains pending rows
home via /teg/send (auto-FX), Idempotency-Key `repat-{id}`. I-X5 checks
gateway balance >= Σ pending. `ref` is the writer's idempotency key.

IDEMPOTENT — migration_bridge replays every migration at each container boot.
"""
from alembic import op
from sqlalchemy import text

revision: str = "0091_gateway_credits"
down_revision: str = "0090_devcard_consent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(text("""
        CREATE TABLE IF NOT EXISTS exchange_gateway_credits (
            id BIGSERIAL PRIMARY KEY,
            did VARCHAR(120) NOT NULL,
            home_registry VARCHAR(128),
            currency VARCHAR(8) NOT NULL DEFAULT 'BVT',
            amount NUMERIC(36,18) NOT NULL,
            origin VARCHAR(24) NOT NULL,
            ref VARCHAR(128) NOT NULL UNIQUE,
            status VARCHAR(16) NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            tx_ref VARCHAR(128),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            paid_at TIMESTAMPTZ
        )
    """))
    op.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_xgc_status ON exchange_gateway_credits (status, created_at)"
    ))


def downgrade() -> None:
    # Forward-only (squash-replay model).
    pass
