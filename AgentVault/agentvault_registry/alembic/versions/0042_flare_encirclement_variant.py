"""Flare encirclement variant — Shadow Chancellor aesthetic options (2026-05-12).

Revision ID: 0042_flare_encirclement_variant
Revises: 0041_flare_slot_selection

Adds `flare_encirclement_variant` to the developers table so shadow_chancellor
backers can pick the aesthetic of their avatar encirclement. Today only the
shadow_chancellor tier renders an encirclement; the variant column keeps the
TIER fixed (palette-locked) while allowing visual flavor:

  • 'sauron'    — pure black ring with red glowing eye-slit at 12 o'clock.
                  Default. Commander-specified. Menacing, watchful, static.
                  Color permanently black + crimson; no customization.
  • 'goth'      — original four-blob gooey purple halo (PB-1 §11/§12 ship).
                  Two layered halos rotating in opposite directions.
  • 'obsidian'  — pure black mirror with slow-shifting iridescent sheen.
                  No purple, no red. Hard polished stone aesthetic.
  • 'void'      — concentric event-horizon distortion rings.
                  Scientific/cosmic feel, no rotation.

The TIER stays palette-locked (FIXED_PALETTE_TIERS in FlareBadge.vue +
flare_accent_color is ignored for shadow_chancellor + commander). The VARIANT
is a separate axis — Commander mantra: tier is rank, variant is flavor.

Default 'sauron' on grant: backfilled here for any existing
shadow_chancellor dev whose row predates this migration. Future grants set
the variant explicitly inside `_evaluate_shadow_chancellor` and
`admin_grant_flare`.

Idempotent (raw SQL with IF NOT EXISTS) per the post-squash replay model.
"""
from typing import Sequence, Union
from alembic import op
from sqlalchemy import text


revision: str = '0042_flare_encirclement_variant'
down_revision: Union[str, None] = '0041_flare_slot_selection'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text(
        "ALTER TABLE developers "
        "ADD COLUMN IF NOT EXISTS flare_encirclement_variant VARCHAR(20) NULL"
    ))
    # Backfill: any existing shadow_chancellor dev gets the default 'sauron'
    # variant. Replay-safe — only updates rows where variant is still NULL.
    bind.execute(text("""
        UPDATE developers
        SET flare_encirclement_variant = 'sauron'
        WHERE flare_tier = 'shadow_chancellor'
          AND flare_encirclement_variant IS NULL
    """))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text(
        "ALTER TABLE developers DROP COLUMN IF EXISTS flare_encirclement_variant"
    ))
