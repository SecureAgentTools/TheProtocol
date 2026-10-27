"""0130 — THE GUILD ⇄ CONTRACT SPINE link (P3a mirror mode, 2026-07-25).

One nullable column: a guild order awarded while `GUILD_MINTS_CONTRACTS=true` mints a spine
contract (`origin_surface='guild'`, escrow_ref ADOPTS the existing `guildref:{oid}` — rail keys
never change mid-flight) and records it here. Mirror mode only: guild money paths are UNTOUCHED;
the contract row is a ledger view whose nightly agreement with the order is the P3b cutover gate.

IDEMPOTENT — replays every boot. Chains 0129.
"""
from alembic import op
from sqlalchemy import text

revision: str = "0130_guild_contract_link"
down_revision: str = "0129_contract_spine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text(
        "ALTER TABLE guild_work_orders ADD COLUMN IF NOT EXISTS contract_id VARCHAR(40) REFERENCES contracts(id)"
    ))
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_guild_orders_contract ON guild_work_orders (contract_id) WHERE contract_id IS NOT NULL"
    ))


def downgrade() -> None:
    pass
