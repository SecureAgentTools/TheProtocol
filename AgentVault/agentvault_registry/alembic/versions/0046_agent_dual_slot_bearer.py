"""Agent dual-slot bearer columns (PB-1 §23, 2026-05-14).

Revision ID: 0046_agent_dual_slot_bearer
Revises: 0045_flare_corner_variant

§23 makes the flare-bearer model dual-slot. Previously `Agent.flare_tier`
was a single rolled-up column — when a dev moved their flare to an agent,
that agent inherited the rolled-up tier and the renderer fell back to a
canonical-default corner (e.g. shadow_chancellor → founder corner). This
silently dropped Commander's selected corner badge ("commander") because
agents had no way to mirror the dev's TWO independent slot selections.

Solution: add two boolean bearer flags on Agent (per-slot single-bearer
per developer) + an optional per-agent admin corner-badge variant. Each
slot is now independently equip-able to any of the dev's agents. Same
agent can bear both. The frontend renderer reads agent.bears_*_flare,
attaches the dev's current selected_*_flare to the agent payload, and
renders both slots via the existing UserAvatar typeof-aware fallback.

New columns on `agents`:
  - bears_corner_flare       BOOLEAN NOT NULL DEFAULT FALSE
  - bears_encirclement_flare BOOLEAN NOT NULL DEFAULT FALSE
  - flare_corner_variant     VARCHAR(20) NULL  (admin-only per-agent override)

Backfill: every agent that currently has `flare_tier IS NOT NULL` (i.e.
is the legacy single-bearer) gets BOTH bears_* flags set to TRUE. This
preserves the existing single-bearer semantics under the new model: the
one bearer agent now bears both slots, matching what the renderer was
implicitly doing via the founder-corner fallback.

Migration uses raw SQL with IF NOT EXISTS so it's idempotent on every
sandbox boot (migration_bridge resets to 0001_squash and replays the chain).
"""
from typing import Sequence, Union
from alembic import op
from sqlalchemy import text


revision: str = '0046_agent_dual_slot_bearer'
down_revision: Union[str, None] = '0045_flare_corner_variant'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    # 1. Add new columns (idempotent)
    bind.execute(text("""
        ALTER TABLE agents
        ADD COLUMN IF NOT EXISTS bears_corner_flare BOOLEAN NOT NULL DEFAULT FALSE
    """))
    bind.execute(text("""
        ALTER TABLE agents
        ADD COLUMN IF NOT EXISTS bears_encirclement_flare BOOLEAN NOT NULL DEFAULT FALSE
    """))
    bind.execute(text("""
        ALTER TABLE agents
        ADD COLUMN IF NOT EXISTS flare_corner_variant VARCHAR(20) NULL
    """))
    # 2. Backfill — every agent that currently wears the single-bearer flare
    #    becomes the dual-bearer (both slots). Idempotent: only flips FALSE
    #    rows that have flare_tier set, never overwrites explicit TRUE.
    bind.execute(text("""
        UPDATE agents
           SET bears_corner_flare       = TRUE,
               bears_encirclement_flare = TRUE
         WHERE flare_tier IS NOT NULL
           AND bears_corner_flare = FALSE
           AND bears_encirclement_flare = FALSE
    """))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("""
        ALTER TABLE agents DROP COLUMN IF EXISTS flare_corner_variant
    """))
    bind.execute(text("""
        ALTER TABLE agents DROP COLUMN IF EXISTS bears_encirclement_flare
    """))
    bind.execute(text("""
        ALTER TABLE agents DROP COLUMN IF EXISTS bears_corner_flare
    """))
