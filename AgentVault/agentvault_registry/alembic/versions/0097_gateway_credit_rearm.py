"""0097 — gateway-credit autonomous-recon bookkeeping (2026-06-19).

Adds `rearm_count` to exchange_gateway_credits so the gateway_float_keeper can autonomously
RECONCILE the gateway sub-ledger: when the gateway is kept solvent, a 'failed' (attempts-exhausted)
repat credit is re-armed (status→'pending', attempts→0, rearm_count+1) so the repat worker retries
it; a credit that exhausts GATEWAY_RECON_MAX_REARM re-arm generations and still fails is moved to a
terminal 'abandoned' status (genuinely undeliverable — a receiver problem the keeper can't fix —
surfaced for ops instead of hot-looping). Δ-neutral: status/counter only, money stays on the gateway
(the keeper maintains it as float). Pairs with migration 0096 (gateway_float_keeper_config).

IDEMPOTENT — migration_bridge.py resets alembic_version to 0001_squash on every container boot, so
every post-squash migration REPLAYS. ADD COLUMN IF NOT EXISTS.
"""
from alembic import op
from sqlalchemy import text

revision: str = "0097_gateway_credit_rearm"
down_revision: str = "0096_gateway_float_keeper"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text(
        "ALTER TABLE exchange_gateway_credits ADD COLUMN IF NOT EXISTS rearm_count INTEGER NOT NULL DEFAULT 0"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("ALTER TABLE exchange_gateway_credits DROP COLUMN IF EXISTS rearm_count"))
