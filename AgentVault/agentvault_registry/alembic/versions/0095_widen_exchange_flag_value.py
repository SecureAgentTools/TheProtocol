"""0095 — widen exchange_flags.value 255→TEXT (demand_director JSON overflow, 2026-06-18).

set_flag('demand_director', ...) stores a JSON of every network-wide ticker. Once the
sim-vue Demand Director discovers ALL venues' symbols (vs the old AdminExchange's local
~5), the value exceeds varchar(255) → asyncpg StringDataRightTruncationError → 500 on
PUT /api/v1/exchange/admin/demand-director. Widen the column to TEXT so any flag JSON fits.

Δ-IRRELEVANT — exchange_flags is the venue kill-switch / config table (key='global_halt',
'demand_director'), no balance data.

IDEMPOTENT — migration_bridge.py resets alembic_version to 0001_squash every container
boot, so post-squash migrations REPLAY. `ALTER COLUMN ... TYPE text` on an already-text
column is a no-op, so replaying is safe (mirrors the 0093/0094 idempotency pattern).
"""
from alembic import op
from sqlalchemy import text

revision: str = "0095_widen_exchange_flag_value"
down_revision: str = "0094_stock_card_via_fanout"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(text(
        "ALTER TABLE exchange_flags ALTER COLUMN value TYPE text"
    ))


def downgrade() -> None:
    # Not safely reversible — any stored value > 255 chars (e.g. the demand_director
    # JSON) would truncate. Intentional no-op.
    pass
