"""0094 — federated_stock_cards.via_fanout (Federated Stock Cards fan-out CARRY, 2026-06-18).

Additive column: marks a cached catalog learned TRANSITIVELY via the registry-card
fan-out (a parent frame relayed a peer's cached catalog) vs locally direct-consumed
(full JWS verify). Direct rows (via_fanout=false) are AUTHORITATIVE and are never
clobbered by a carried copy — the multi-source-clobber guard, mirroring
feedback_registry_card_fanout_multisource_clobber. Touches no existing table data
→ Δ-irrelevant (read-only metadata).

IDEMPOTENT — migration_bridge.py resets alembic_version to 0001_squash on every
container boot, so every post-squash migration REPLAYS. All raw SQL is
`IF NOT EXISTS` (see 0093_federated_stock_cards.py for the same pattern).
"""
from alembic import op
from sqlalchemy import text

revision: str = "0094_stock_card_via_fanout"
down_revision: str = "0093_federated_stock_cards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text(
        "ALTER TABLE federated_stock_cards "
        "ADD COLUMN IF NOT EXISTS via_fanout BOOLEAN NOT NULL DEFAULT false"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("ALTER TABLE federated_stock_cards DROP COLUMN IF EXISTS via_fanout"))
