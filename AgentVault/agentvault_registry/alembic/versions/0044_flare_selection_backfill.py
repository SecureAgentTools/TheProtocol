"""Backfill selected_corner_flare + selected_encirclement_flare on flare-bearers (2026-05-13).

Revision ID: 0044_flare_selection_backfill
Revises: 0043_flare_celeb_agent_variant

After §12 (slot system, 0041) and §14 (variant system, 0042) shipped, the
display source-of-truth shifted from `flare_tier` (rank) to `selected_*_flare`
(user's display selection). Rows granted BEFORE the auto-populate logic was
added carry `flare_tier=<something>` with `selected_*_flare=NULL`. The frontend
UserAvatar used to fall back to `flare_tier` when selection was null — but
that legacy fallback made it impossible to distinguish:

  (a) "user never picked, default to tier"
  (b) "user clicked Hide corner/encirclement, respect null"

Result: clicking "Hide corner" in FlareManager updated the auth-store but
the badge reappeared on header/sidebar/Settings because the legacy fallback
resurrected it. Same for "Hide encirclement."

This migration normalizes existing rows so `null` truly means "user cleared
explicitly." Combined with dropping the frontend's legacy fallback, hide-corner
+ hide-encirclement now react immediately.

Three idempotent UPDATEs:

  1. Corner-class tiers (sentinel/architect/founder/operator/commander) where
     selected_corner_flare IS NULL → set selected_corner_flare = flare_tier.
     The user's most-recent earned rank is the natural default badge.

  2. Shadow Chancellor backers where selected_corner_flare IS NULL → set to
     'founder'. €500 cumulative implies at least one Founder-tier purchase in
     practice; 'founder' is the canonical companion corner.

  3. Shadow Chancellor backers where selected_encirclement_flare IS NULL →
     set to 'shadow_chancellor' (the only encirclement-class tier today).

All three filter on `selected_*_flare IS NULL`, so replay is a no-op (the
post-squash migration_bridge re-runs the chain every boot in sandbox).
"""
from typing import Sequence, Union
from alembic import op
from sqlalchemy import text


revision: str = '0044_flare_selection_backfill'
down_revision: Union[str, None] = '0043_flare_celeb_agent_variant'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Corner-class tiers default selected_corner_flare to their flare_tier.
    bind.execute(text("""
        UPDATE developers
        SET selected_corner_flare = flare_tier
        WHERE selected_corner_flare IS NULL
          AND flare_tier IN ('sentinel', 'architect', 'founder', 'operator', 'commander')
    """))

    # 2. Shadow Chancellor backers without a corner pick → default 'founder'.
    bind.execute(text("""
        UPDATE developers
        SET selected_corner_flare = 'founder'
        WHERE selected_corner_flare IS NULL
          AND flare_tier = 'shadow_chancellor'
    """))

    # 3. Shadow Chancellor backers without an encirclement pick → wear it.
    bind.execute(text("""
        UPDATE developers
        SET selected_encirclement_flare = 'shadow_chancellor'
        WHERE selected_encirclement_flare IS NULL
          AND flare_tier = 'shadow_chancellor'
    """))


def downgrade() -> None:
    # No-op: backfill is forward-only. We can't distinguish backfilled rows
    # from rows where the user genuinely picked the same value via the UI,
    # so reversing would corrupt explicit user choices. Leave the columns
    # populated on downgrade.
    pass
