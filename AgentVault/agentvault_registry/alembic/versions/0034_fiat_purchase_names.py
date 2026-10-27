"""PB-1 — Buyer-supplied names on fiat_purchases (2026-05-09).

Revision ID: 0034_fiat_purchase_names
Revises: 0033_flare_columns

Adds two optional columns to `fiat_purchases` so the BuyAVT anonymous flow
can accept buyer-provided names for the auto-created Developer + Agent:

  • requested_developer_name VARCHAR(64) — desired developer account name
  • requested_agent_name     VARCHAR(64) — desired first-agent name

The webhook handler (`_resolve_or_create_anonymous` / `_bootstrap_agent_for_developer`)
prefers these over the previous `{email-local-part}-{rand-hex}` slug. If a
provided developer name collides with an existing Developer.name (UNIQUE),
the handler falls back to the auto-suffix logic.

Both columns are NULL for the logged-in flow (existing names are already set).

Idempotent (ADD COLUMN IF NOT EXISTS) so migration_bridge replays remain safe.
"""
from alembic import op


revision = "0034_fiat_purchase_names"
down_revision = "0033_flare_columns"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE fiat_purchases
            ADD COLUMN IF NOT EXISTS requested_developer_name VARCHAR(64),
            ADD COLUMN IF NOT EXISTS requested_agent_name     VARCHAR(64);
    """)


def downgrade():
    op.execute("ALTER TABLE fiat_purchases DROP COLUMN IF EXISTS requested_agent_name;")
    op.execute("ALTER TABLE fiat_purchases DROP COLUMN IF EXISTS requested_developer_name;")
