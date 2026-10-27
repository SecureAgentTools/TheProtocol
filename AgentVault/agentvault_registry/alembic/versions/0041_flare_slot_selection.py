"""Multi-flare slot selection — corner + encirclement (2026-05-11).

Revision ID: 0041_flare_slot_selection
Revises: 0040_provisioning_eligibility

Splits flare display into two independent slots so a backer who has
unlocked multiple tiers can wear a different combination than just their
highest-rank earned flare:

  • selected_corner_flare        VARCHAR(32) NULLABLE
      User's chosen CORNER badge (sentinel | architect | founder | operator |
      commander). Independent of `flare_tier` (which stays as the rolled-up
      "highest ever earned"). Lets a Founder choose to display Sentinel for
      aesthetic reasons. Validation gate: must be ≤ rank of `flare_tier`.

  • selected_encirclement_flare  VARCHAR(32) NULLABLE
      User's chosen ENCIRCLEMENT around their avatar circle. Today only
      `shadow_chancellor` is encirclement-eligible. NULL = no encirclement
      shown around avatar.

The original `flare_tier` column is preserved as the source-of-truth for
"highest tier ever earned" (used by ranking, supply-invariant audits,
agent-card derivations). Selection columns drive display only.

Migration is idempotent (raw SQL with IF NOT EXISTS) per the post-squash
replay model.
"""
from typing import Sequence, Union
from alembic import op
from sqlalchemy import text


revision: str = '0041_flare_slot_selection'
down_revision: Union[str, None] = '0040_provisioning_eligibility'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    # Schema additions
    bind.execute(text(
        "ALTER TABLE developers "
        "ADD COLUMN IF NOT EXISTS selected_corner_flare VARCHAR(32) NULL"
    ))
    bind.execute(text(
        "ALTER TABLE developers "
        "ADD COLUMN IF NOT EXISTS selected_encirclement_flare VARCHAR(32) NULL"
    ))

    # Default-population for existing rows: copy flare_tier into the
    # appropriate slot. Run as UPDATE … WHERE flare_tier IS NOT NULL AND the
    # slot column is still NULL — replay-safe (no-op on second boot).
    bind.execute(text("""
        UPDATE developers
        SET selected_corner_flare = flare_tier
        WHERE flare_tier IS NOT NULL
          AND flare_tier IN ('sentinel', 'architect', 'founder', 'operator', 'commander')
          AND selected_corner_flare IS NULL
    """))
    bind.execute(text("""
        UPDATE developers
        SET selected_encirclement_flare = 'shadow_chancellor'
        WHERE flare_tier = 'shadow_chancellor'
          AND selected_encirclement_flare IS NULL
    """))
    # If a dev has shadow_chancellor flare_tier but their corner is null
    # (because shadow isn't a corner-tier value), default the corner to
    # 'founder' — they earned at least €100 single purchase to get the
    # cumulative threshold lift, so Founder is a reasonable default corner.
    # Replay-safe (skips when corner already set).
    bind.execute(text("""
        UPDATE developers
        SET selected_corner_flare = 'founder'
        WHERE flare_tier = 'shadow_chancellor'
          AND selected_corner_flare IS NULL
    """))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("ALTER TABLE developers DROP COLUMN IF EXISTS selected_encirclement_flare"))
    bind.execute(text("ALTER TABLE developers DROP COLUMN IF EXISTS selected_corner_flare"))
