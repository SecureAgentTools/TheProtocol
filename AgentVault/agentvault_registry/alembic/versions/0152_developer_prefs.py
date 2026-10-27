"""DEVELOPER PREFS (2026-08-22, §POCKETBRIDGE3) — one tiny key/value rail per developer.

Batch 3 needs two things the schema had no home for: a watchlist of starred
tickers that FOLLOWS THE ACCOUNT across phone and desktop (D3-2: synced), and
the session price-alert rules the server-side watcher reads so a push can reach
a closed app (D3-4). Neither fits the existing storage: `developers.
notification_prefs` is the legacy notification blob the resolver owns,
`developer_notification_prefs` is strictly (type, channel, enabled) rows, and
`device_push_registrations.prefs` is per-DEVICE narrowing. A per-ticker alert
rule is none of those shapes.

So: one row per (developer, key), value JSONB, keys allowlisted at the router
(`pocket.watchlist`, `pocket.price_alerts`, `pocket.assistant`) with a size cap
— deliberately NOT a general dumping ground. Δ-irrelevant: no money columns,
nothing the supply audit reads.

Additive only. Revision ID: 0152_developer_prefs
Revises: 0151_flare_shop
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0152_developer_prefs"
down_revision = "0151_flare_shop"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "developer_prefs",
        sa.Column("developer_id", sa.Integer, sa.ForeignKey("developers.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", JSONB, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    # The price-alert watcher scans by key across developers each cycle.
    op.create_index("ix_developer_prefs_key", "developer_prefs", ["key"])


def downgrade() -> None:
    op.drop_index("ix_developer_prefs_key", table_name="developer_prefs")
    op.drop_table("developer_prefs")
