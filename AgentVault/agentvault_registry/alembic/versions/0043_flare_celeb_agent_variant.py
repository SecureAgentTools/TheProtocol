"""Flare celebration flag + per-agent variant column (2026-05-12).

Revision ID: 0043_flare_celeb_agent_variant
Revises: 0042_flare_encirclement_variant

Two tightly-related additions, shipped together:

1. **`developers.flare_celebration_seen_at TIMESTAMPTZ NULL`**
   One-shot acknowledgment timestamp for the Shadow Chancellor unlock modal.
   When NULL + flare_tier='shadow_chancellor' → frontend shows the celebration
   modal (pick your encirclement variant). When set, the modal stays
   suppressed forever. Exists so the upgrade moment lands once and only once.

2. **`agents.flare_encirclement_variant VARCHAR(20) NULL`**
   Mirrors the Developer column shipped in 0042. Lets agents that wear
   shadow_chancellor render a different aesthetic per-agent (Commander
   asked for completeness — agent-side variant picker on /my-agents).
   Backfill: any existing shadow_chancellor agent gets the default 'sauron'.

Both columns are idempotent (raw SQL with IF NOT EXISTS) per the post-squash
replay model. Backfill UPDATE statements check for NULL before assigning
so they're replay-safe.
"""
from typing import Sequence, Union
from alembic import op
from sqlalchemy import text


revision: str = '0043_flare_celeb_agent_variant'
down_revision: Union[str, None] = '0042_flare_encirclement_variant'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Developer celebration-seen flag
    bind.execute(text(
        "ALTER TABLE developers "
        "ADD COLUMN IF NOT EXISTS flare_celebration_seen_at "
        "TIMESTAMP WITH TIME ZONE NULL"
    ))
    # No backfill — existing shadow_chancellor devs were granted before the
    # celebration concept existed; we treat them as "already seen" so they
    # don't get retroactively prompted. Set their seen_at to NOW.
    bind.execute(text("""
        UPDATE developers
        SET flare_celebration_seen_at = NOW()
        WHERE flare_tier = 'shadow_chancellor'
          AND flare_celebration_seen_at IS NULL
    """))

    # 2. Per-agent variant column
    bind.execute(text(
        "ALTER TABLE agents "
        "ADD COLUMN IF NOT EXISTS flare_encirclement_variant VARCHAR(20) NULL"
    ))
    # Backfill: any existing shadow_chancellor agent gets the default 'sauron'.
    # Replay-safe — only updates rows where variant is still NULL.
    bind.execute(text("""
        UPDATE agents
        SET flare_encirclement_variant = 'sauron'
        WHERE flare_tier = 'shadow_chancellor'
          AND flare_encirclement_variant IS NULL
    """))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text(
        "ALTER TABLE agents DROP COLUMN IF EXISTS flare_encirclement_variant"
    ))
    bind.execute(text(
        "ALTER TABLE developers DROP COLUMN IF EXISTS flare_celebration_seen_at"
    ))
