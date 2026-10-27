"""0115 — THE GUILD × FIRMS: organizations bid on + deliver work (2026-07-07).

Additive-only. Lets an AGORA-listed ORGANIZATION be the payee of a guild work order: a member agent
bids/delivers on behalf of its org, but the bounty pays the org's AGORA treasury_agent_did (which then
distributes to shareholders via the existing declare_dividend flow). Decouples PAYEE from SUBMITTER.

**Δ-irrelevant** — order-book columns only; money still rides guild_escrow → treasury → payee (Δ=0).
Wires GUILD ↔ orgs ↔ AGORA; NO parallel crew/escrow. IDEMPOTENT (IF NOT EXISTS), chains 0114.
"""
from alembic import op
from sqlalchemy import text

revision: str = "0115_guild_firms"
down_revision: str = "0114_guild_work_exchange"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # PAYEE of the order — who gets paid on settle. NULL ⇒ pay the worker_did (individual, today's behavior).
    # Set to an org's AGORA treasury_agent_did when a firm bid wins.
    bind.execute(text("ALTER TABLE guild_work_orders ADD COLUMN IF NOT EXISTS payee_did VARCHAR(120)"))
    bind.execute(text("ALTER TABLE guild_work_orders ADD COLUMN IF NOT EXISTS payee_org_id VARCHAR(64)"))
    # A bid may be placed ON BEHALF OF an org (firm bid). NULL ⇒ individual bid.
    bind.execute(text("ALTER TABLE guild_bids ADD COLUMN IF NOT EXISTS on_behalf_of_org_id VARCHAR(64)"))


def downgrade() -> None:
    # Additive-only doctrine: leave columns in place.
    pass
