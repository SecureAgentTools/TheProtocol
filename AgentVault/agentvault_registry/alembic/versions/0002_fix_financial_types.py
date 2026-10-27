"""Fix financial column types: Integer/Numeric(20,2) → Numeric(30,6)

Ensures all AVT monetary columns use consistent precision matching TEG (Numeric(36,18))
and the registry's balance columns (Numeric(30,6)). Prevents truncation of fractional amounts.

Revision ID: 0002_fix_financial_types
Revises: 0001_squash
Create Date: 2026-03-29
"""
from alembic import op
from sqlalchemy import text

revision = '0002_fix_financial_types'
down_revision = '0001_squash'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # Integer → Numeric(30,6)
    conn.execute(text("ALTER TABLE refactoring_upgrade_contracts ALTER COLUMN payment_amount TYPE NUMERIC(30,6) USING payment_amount::NUMERIC(30,6)"))
    conn.execute(text("ALTER TABLE cross_registry_settlements ALTER COLUMN requested_amount TYPE NUMERIC(30,6) USING requested_amount::NUMERIC(30,6)"))
    conn.execute(text("ALTER TABLE cross_registry_settlements ALTER COLUMN slashed_amount TYPE NUMERIC(30,6) USING slashed_amount::NUMERIC(30,6)"))
    conn.execute(text("ALTER TABLE cross_registry_settlements ALTER COLUMN minted_amount TYPE NUMERIC(30,6) USING minted_amount::NUMERIC(30,6)"))
    conn.execute(text("ALTER TABLE votes ALTER COLUMN voting_power TYPE NUMERIC(30,6) USING voting_power::NUMERIC(30,6)"))
    conn.execute(text("ALTER TABLE agents ALTER COLUMN reputation_bond_amount TYPE NUMERIC(30,6) USING reputation_bond_amount::NUMERIC(30,6)"))
    conn.execute(text("ALTER TABLE peer_registries ALTER COLUMN auto_slash_max_avt TYPE NUMERIC(30,6) USING auto_slash_max_avt::NUMERIC(30,6)"))

    # Numeric(20,2) → Numeric(30,6)
    conn.execute(text("ALTER TABLE stakes ALTER COLUMN amount TYPE NUMERIC(30,6)"))
    conn.execute(text("ALTER TABLE stake_transactions ALTER COLUMN amount TYPE NUMERIC(30,6)"))
    conn.execute(text("ALTER TABLE staking_rewards ALTER COLUMN amount TYPE NUMERIC(30,6)"))
    conn.execute(text("ALTER TABLE staking_apy_tiers ALTER COLUMN min_amount TYPE NUMERIC(30,6)"))


def downgrade() -> None:
    pass  # No downgrade — precision loss is irreversible
