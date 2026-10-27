"""PB-1 — Configurable fiat tier pricing (DB-backed, versioned, 2026-05-09).

Revision ID: 0032_fiat_pricing_config
Revises: 0031_fiat_purchases

Replaces the hardcoded EUR→AVT tier constants in services/stripe_checkout.py
with a versioned, DB-stored config. Singleton-with-history: exactly one row
is active at any time; every change inserts a new row + archives the old.

Seeds version 1 with the original constants:
  €1–€19.99   → 2000 AVT/EUR (base)
  €20–€99.99  → 2500 AVT/EUR (+25% bonus)
  €100–€500   → 3000 AVT/EUR (+50% bonus)

Operators can update via admin endpoint (admin_treasury gate). Future
versions can change tier breakpoints, rates, min/max EUR, or even add new
currencies — without code changes or new migrations.

Idempotent (IF NOT EXISTS / WHERE NOT EXISTS) so migration_bridge replays
on every container boot remain safe.
"""
from alembic import op


revision = "0032_fiat_pricing_config"
down_revision = "0031_fiat_purchases"
branch_labels = None
depends_on = None


_DEFAULT_CONFIG_JSON = """{
  "tiers": [
    { "floor_eur": "1.00",   "avt_per_eur": "2000", "tier_label": "tier_1_base",    "bonus_label": "" },
    { "floor_eur": "20.00",  "avt_per_eur": "2500", "tier_label": "tier_2_value",   "bonus_label": "+25%" },
    { "floor_eur": "100.00", "avt_per_eur": "3000", "tier_label": "tier_3_premium", "bonus_label": "+50%" }
  ],
  "min_eur": "1.00",
  "max_eur": "500.00",
  "currency": "EUR"
}"""


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS fiat_pricing_config (
            id                          VARCHAR(36) PRIMARY KEY,
            version                     INTEGER NOT NULL UNIQUE,
            config                      JSONB NOT NULL,
            is_active                   BOOLEAN NOT NULL DEFAULT false,
            note                        VARCHAR(500),
            created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_by_developer_id     INTEGER REFERENCES developers(id) ON DELETE SET NULL,
            deactivated_at              TIMESTAMPTZ
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_fiat_pricing_active ON fiat_pricing_config(is_active) WHERE is_active = true;")
    op.execute("CREATE INDEX IF NOT EXISTS idx_fiat_pricing_version ON fiat_pricing_config(version);")
    # Partial unique index: at most one active row at a time. Postgres-only.
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_fiat_pricing_only_one_active
        ON fiat_pricing_config(is_active) WHERE is_active = true;
    """)

    # Seed v1 default IFF no rows exist yet (idempotent across boot replays).
    op.execute(f"""
        INSERT INTO fiat_pricing_config (id, version, config, is_active, note, created_at)
        SELECT gen_random_uuid()::varchar(36), 1, '{_DEFAULT_CONFIG_JSON}'::jsonb, true,
               'Initial default — PB-1 commitment from Business Model Part 6', NOW()
        WHERE NOT EXISTS (SELECT 1 FROM fiat_pricing_config);
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS fiat_pricing_config;")
