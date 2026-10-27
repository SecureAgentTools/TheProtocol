"""Add flare_encirclement_overlay column (§28, 2026-05-13).

Revision ID: 0054_flare_encirclement_overlay
Revises: 0053_a2a_v1_cardshape

§28 promotes the "broken machine" family (glitch / cascade / panic) from
encirclement variants to an INDEPENDENT OVERLAY AXIS. Previously they were
mutually-exclusive with sauron/goth/obsidian/aurora/etc. — selecting "panic"
replaced your base encirclement. Now an overlay sits ON TOP of any base
variant, so a wearer can run blackhole+panic, aurora+glitch, sauron+cascade,
etc.

Schema:
  developers.flare_encirclement_overlay  VARCHAR(20) NULL
  agents.flare_encirclement_overlay      VARCHAR(20) NULL

Auto-migrate existing wearers: anyone with variant IN ('glitch', 'cascade',
'panic') gets the matching overlay set and their variant reset to 'sauron'
(the default base). The visual stays identical because the SVG overlay
renders the same effect — it's just no longer tied to .fc-encircle-
shadow_chancellor selector specificity.

For panic specifically, we map to 'panic-a' which is the first of three
tournament-round designs (§29). When user selects a winner, a follow-up
migration collapses panic-a/b/c → panic.

Raw SQL with IF NOT EXISTS per feedback_migration_use_raw_sql_if_not_exists.md
(migration_bridge resets to 0001_squash and replays the chain on every
sandbox boot — non-idempotent ops crash on second boot).
"""
from typing import Sequence, Union
from alembic import op
from sqlalchemy import text


revision: str = '0054_flare_encirclement_overlay'
down_revision: Union[str, None] = '0053_a2a_v1_cardshape'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("""
        ALTER TABLE developers
        ADD COLUMN IF NOT EXISTS flare_encirclement_overlay VARCHAR(20) NULL
    """))
    bind.execute(text("""
        ALTER TABLE agents
        ADD COLUMN IF NOT EXISTS flare_encirclement_overlay VARCHAR(20) NULL
    """))
    bind.execute(text("""
        UPDATE developers
           SET flare_encirclement_overlay = CASE
                 WHEN flare_encirclement_variant = 'glitch'  THEN 'glitch'
                 WHEN flare_encirclement_variant = 'cascade' THEN 'cascade'
                 WHEN flare_encirclement_variant = 'panic'   THEN 'panic-a'
               END,
               flare_encirclement_variant = 'sauron'
         WHERE flare_encirclement_variant IN ('glitch', 'cascade', 'panic')
           AND flare_encirclement_overlay IS NULL
    """))
    bind.execute(text("""
        UPDATE agents
           SET flare_encirclement_overlay = CASE
                 WHEN flare_encirclement_variant = 'glitch'  THEN 'glitch'
                 WHEN flare_encirclement_variant = 'cascade' THEN 'cascade'
                 WHEN flare_encirclement_variant = 'panic'   THEN 'panic-a'
               END,
               flare_encirclement_variant = 'sauron'
         WHERE flare_encirclement_variant IN ('glitch', 'cascade', 'panic')
           AND flare_encirclement_overlay IS NULL
    """))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("""
        ALTER TABLE agents      DROP COLUMN IF EXISTS flare_encirclement_overlay
    """))
    bind.execute(text("""
        ALTER TABLE developers  DROP COLUMN IF EXISTS flare_encirclement_overlay
    """))
