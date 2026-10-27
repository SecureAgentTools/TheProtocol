"""0117 — THE GUILD goes CROSS-REGISTRY (2026-07-08).

Additive-only. Marks bids/workers that live on a PEER registry, placed via the federation channel
(mirrors the contracts cross-registry pattern: peer-authenticated federated endpoints + home-side
proxy). Money design (all existing rails, Δ=0):
  • remote bids allowed on NON-staked orders only (no remote escrow legs);
  • settle to a remote worker = staged saga: escrow_payout(treasury→poster, 'xf_stage') then
    /teg/cross-registry-transfer(poster→worker, poster's own JWT — the exact contracts payment
    rail) with a compensating re-deposit on failure. No new money path (rule-13).
IDEMPOTENT (IF NOT EXISTS), chains 0116.
"""
from alembic import op
from sqlalchemy import text

revision: str = "0117_guild_crossframe"
down_revision: str = "0116_guild_staked_work"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # A bid placed by an agent homed on a peer registry (via the federation channel). NULL ⇒ local.
    bind.execute(text("ALTER TABLE guild_bids ADD COLUMN IF NOT EXISTS home_registry_url VARCHAR(300)"))
    # Copied from the winning bid at award — drives the staged cross-registry settle saga.
    bind.execute(text("ALTER TABLE guild_work_orders ADD COLUMN IF NOT EXISTS worker_home_registry VARCHAR(300)"))


def downgrade() -> None:
    pass
