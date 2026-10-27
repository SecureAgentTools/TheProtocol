"""0116 — THE GUILD: staked work (bidder collateral, 2026-07-07).

Additive-only. A task can REQUIRE bidders to lock a stake; the awarded worker's stake is RELEASED on
success, or SLASHED to the poster on failure / lost dispute. Reuses the GUILD escrow (guild_escrow) —
the same treasury-backed per-order lock the bounty already uses — NOT the veToken staking (FIFO, no
per-task earmark) nor the enforcement slasher (cache-only, can't pay the poster).

**Δ-irrelevant** — order-book columns only; every stake leg is a zero-sum treasury transfer via
guild_escrow (lock=bidder→treasury, release/refund=treasury→bidder, slash=treasury→poster). Slash is a
TRANSFER, not a burn → Δ=0. IDEMPOTENT (IF NOT EXISTS), chains 0115.
"""
from alembic import op
from sqlalchemy import text

revision: str = "0116_guild_staked_work"
down_revision: str = "0115_guild_firms"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # Optional collateral the poster requires bidders to lock (0/NULL ⇒ no stake required).
    bind.execute(text("ALTER TABLE guild_work_orders ADD COLUMN IF NOT EXISTS stake_required NUMERIC(30,10)"))
    # Per-bid stake: amount locked, its escrow ref, and lifecycle status.
    bind.execute(text("ALTER TABLE guild_bids ADD COLUMN IF NOT EXISTS stake_amount NUMERIC(30,10)"))
    bind.execute(text("ALTER TABLE guild_bids ADD COLUMN IF NOT EXISTS stake_escrow_ref VARCHAR(90)"))
    bind.execute(text("ALTER TABLE guild_bids ADD COLUMN IF NOT EXISTS stake_status VARCHAR(16)"))  # held|released|slashed


def downgrade() -> None:
    pass
