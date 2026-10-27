"""PB-1 — Flare cosmetic columns on developers + agents (2026-05-09).

Revision ID: 0033_flare_columns
Revises: 0032_fiat_pricing_config

Adds 3 cosmetic flare columns to `developers` and `agents`:
  • flare_tier               VARCHAR(32)   — 'sentinel' | 'architect' | 'founder' | NULL
  • flare_granted_at         TIMESTAMPTZ
  • flare_source_purchase_id VARCHAR(36)   — FK to fiat_purchases(id) ON DELETE SET NULL

Two flares per purchase (Profile + Agent), granted automatically by
`_handle_checkout_completed` after `_fund_via_reward_waterfall` succeeds.
Higher tier wins on multi-purchase (Founder > Architect > Sentinel).

Profile flare is permanent (auto-applied, never moved). Agent flare is movable —
the dev can re-assign it to any agent they own via POST /api/v1/fiat/flare/move/.

Cosmetic only — zero AVT effect, supply invariant unaffected.

Idempotent (IF NOT EXISTS / ADD COLUMN IF NOT EXISTS) so migration_bridge
replays on every container boot remain safe.
"""
from alembic import op


revision = "0033_flare_columns"
down_revision = "0032_fiat_pricing_config"
branch_labels = None
depends_on = None


def upgrade():
    # ----------------------------------------------------------------------
    # developers — profile flare (permanent, auto-applied)
    # ----------------------------------------------------------------------
    op.execute("""
        ALTER TABLE developers
            ADD COLUMN IF NOT EXISTS flare_tier               VARCHAR(32),
            ADD COLUMN IF NOT EXISTS flare_granted_at         TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS flare_source_purchase_id VARCHAR(36);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_developers_flare_tier
        ON developers(flare_tier) WHERE flare_tier IS NOT NULL;
    """)
    # Add FK to fiat_purchases.id (table created in 0031). ON DELETE SET NULL —
    # purging a purchase row clears the back-reference but keeps the badge.
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE constraint_name = 'fk_developers_flare_source_purchase'
            ) THEN
                ALTER TABLE developers
                ADD CONSTRAINT fk_developers_flare_source_purchase
                FOREIGN KEY (flare_source_purchase_id)
                REFERENCES fiat_purchases(id)
                ON DELETE SET NULL;
            END IF;
        END $$;
    """)

    # ----------------------------------------------------------------------
    # agents — agent flare (movable across agents owned by same developer)
    # ----------------------------------------------------------------------
    op.execute("""
        ALTER TABLE agents
            ADD COLUMN IF NOT EXISTS flare_tier               VARCHAR(32),
            ADD COLUMN IF NOT EXISTS flare_granted_at         TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS flare_source_purchase_id VARCHAR(36);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_agents_flare_tier
        ON agents(flare_tier) WHERE flare_tier IS NOT NULL;
    """)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE constraint_name = 'fk_agents_flare_source_purchase'
            ) THEN
                ALTER TABLE agents
                ADD CONSTRAINT fk_agents_flare_source_purchase
                FOREIGN KEY (flare_source_purchase_id)
                REFERENCES fiat_purchases(id)
                ON DELETE SET NULL;
            END IF;
        END $$;
    """)


def downgrade():
    op.execute("ALTER TABLE agents DROP CONSTRAINT IF EXISTS fk_agents_flare_source_purchase;")
    op.execute("DROP INDEX IF EXISTS idx_agents_flare_tier;")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS flare_source_purchase_id;")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS flare_granted_at;")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS flare_tier;")
    op.execute("ALTER TABLE developers DROP CONSTRAINT IF EXISTS fk_developers_flare_source_purchase;")
    op.execute("DROP INDEX IF EXISTS idx_developers_flare_tier;")
    op.execute("ALTER TABLE developers DROP COLUMN IF EXISTS flare_source_purchase_id;")
    op.execute("ALTER TABLE developers DROP COLUMN IF EXISTS flare_granted_at;")
    op.execute("ALTER TABLE developers DROP COLUMN IF EXISTS flare_tier;")
