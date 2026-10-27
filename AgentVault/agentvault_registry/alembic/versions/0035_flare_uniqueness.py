"""PB-1 — Flare uniqueness + buyer customization (2026-05-09).

Revision ID: 0035_flare_uniqueness
Revises: 0034_fiat_purchase_names

Hardens the cosmetic flare into a genuinely distinct, bespoke digital
artifact. Adds 7 columns to `developers` (the canonical flare identity
holder — agent flare is just a pointer to which agent currently wears it):

  • flare_id              VARCHAR(36) UNIQUE — UUID generated on first grant,
                                              preserved across tier upgrades
  • flare_display_name    VARCHAR(80)        — buyer-supplied label (company,
                                              cause, handle — anything they
                                              want associated with the flare)
  • flare_tagline         VARCHAR(160)       — short prose tagline shown on
                                              hover/profile
  • flare_logo_url        VARCHAR(500)       — optional HTTPS image URL
                                              (renders in lg-sized badges)
  • flare_link_url        VARCHAR(500)       — optional clickable link target
  • flare_cause           VARCHAR(80)        — optional category tag
                                              ("open-source", "AI safety", …)
  • flare_accent_color    VARCHAR(20)        — optional hex/HSL within the
                                              tier-allowed gamut

Non-transferability: the flare_id never moves between developers. Agent
flare moves only within a developer's owned agents (existing
/fiat/flare/move semantics). Refunds DO NOT auto-strip flare (Strategy §7).

Backfill: existing developers with flare_tier set but no flare_id receive
a fresh UUID (one-time, idempotent). No data motion for un-flared devs.

Idempotent (ADD COLUMN IF NOT EXISTS).
"""
from alembic import op


revision = "0035_flare_uniqueness"
down_revision = "0034_fiat_purchase_names"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE developers
            ADD COLUMN IF NOT EXISTS flare_id              VARCHAR(36),
            ADD COLUMN IF NOT EXISTS flare_display_name    VARCHAR(80),
            ADD COLUMN IF NOT EXISTS flare_tagline         VARCHAR(160),
            ADD COLUMN IF NOT EXISTS flare_logo_url        VARCHAR(500),
            ADD COLUMN IF NOT EXISTS flare_link_url        VARCHAR(500),
            ADD COLUMN IF NOT EXISTS flare_cause           VARCHAR(80),
            ADD COLUMN IF NOT EXISTS flare_accent_color    VARCHAR(20);
    """)
    # Postgres-only: partial unique index (one-row-per-uuid, NULLs ignored).
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_developers_flare_id
        ON developers(flare_id) WHERE flare_id IS NOT NULL;
    """)
    # Backfill: any developer with flare_tier set but no flare_id gets one.
    # gen_random_uuid() requires the pgcrypto extension (already enabled in
    # all production DBs — fiat_pricing_config.0032 uses it too).
    op.execute("""
        UPDATE developers
        SET flare_id = gen_random_uuid()::varchar(36)
        WHERE flare_tier IS NOT NULL AND flare_id IS NULL;
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_developers_flare_id;")
    op.execute("ALTER TABLE developers DROP COLUMN IF EXISTS flare_accent_color;")
    op.execute("ALTER TABLE developers DROP COLUMN IF EXISTS flare_cause;")
    op.execute("ALTER TABLE developers DROP COLUMN IF EXISTS flare_link_url;")
    op.execute("ALTER TABLE developers DROP COLUMN IF EXISTS flare_logo_url;")
    op.execute("ALTER TABLE developers DROP COLUMN IF EXISTS flare_tagline;")
    op.execute("ALTER TABLE developers DROP COLUMN IF EXISTS flare_display_name;")
    op.execute("ALTER TABLE developers DROP COLUMN IF EXISTS flare_id;")
