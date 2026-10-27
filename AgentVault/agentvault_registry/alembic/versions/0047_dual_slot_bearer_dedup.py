"""Dual-slot bearer dedup + per-variant uniqueness backfill (§24, 2026-05-14).

Revision ID: 0047_dual_slot_bearer_dedup
Revises: 0046_agent_dual_slot_bearer

§24 follow-up: migration 0046 backfilled `bears_corner_flare` +
`bears_encirclement_flare` to TRUE for EVERY agent with `flare_tier IS NOT NULL`.
That was correct under the single-bearer-snapshot model but left duplicate
bearers for devs whose agents had `flare_tier` set from multiple sources
(admin grants + fiat-purchase moves + legacy migrations). On Commander's
fleet: MOIRA (dev moved flare here) + SYBIL (legacy admin grant) both
ended up bears_corner_flare=TRUE → renderer showed the commander badge on
BOTH agents simultaneously.

§24 also introduces per-variant single-occupancy (one variant per agent
across the dev's fleet). Same duplicate problem on the variant axis —
auto-inherited variants from /flare/equip can collide on legacy state.

This migration normalizes both:

1. **Slot bearer dedup**: For each (developer, slot), keep at most one
   bearer — the agent with the most-recent `flare_granted_at` (NULLs
   sorted last). Clear bears_<slot>_flare on all other agents of that dev.

2. **Variant dedup**: For each (developer, variant), keep the variant
   only on the agent with the most-recent `flare_granted_at`. Clear it
   on all other agents.

Both passes use PostgreSQL window functions (ROW_NUMBER OVER PARTITION BY)
so they run in a single query per axis. Idempotent — re-running yields the
same result.
"""
from typing import Sequence, Union
from alembic import op
from sqlalchemy import text


revision: str = '0047_dual_slot_bearer_dedup'
down_revision: Union[str, None] = '0046_agent_dual_slot_bearer'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Dedup corner-slot bearer: keep only the most-recently flare-granted
    #    agent per developer as bears_corner_flare=TRUE.
    bind.execute(text("""
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY creator_developer_id
                       ORDER BY flare_granted_at DESC NULLS LAST, id DESC
                   ) AS rn
              FROM agents
             WHERE bears_corner_flare = TRUE
        )
        UPDATE agents
           SET bears_corner_flare = FALSE
          FROM ranked
         WHERE agents.id = ranked.id
           AND ranked.rn > 1
    """))

    # 2. Dedup encirclement-slot bearer (same pattern)
    bind.execute(text("""
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY creator_developer_id
                       ORDER BY flare_granted_at DESC NULLS LAST, id DESC
                   ) AS rn
              FROM agents
             WHERE bears_encirclement_flare = TRUE
        )
        UPDATE agents
           SET bears_encirclement_flare = FALSE
          FROM ranked
         WHERE agents.id = ranked.id
           AND ranked.rn > 1
    """))

    # 3. Dedup encirclement variant (each variant value at most once per dev)
    bind.execute(text("""
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY creator_developer_id, flare_encirclement_variant
                       ORDER BY flare_granted_at DESC NULLS LAST, id DESC
                   ) AS rn
              FROM agents
             WHERE flare_encirclement_variant IS NOT NULL
        )
        UPDATE agents
           SET flare_encirclement_variant = NULL
          FROM ranked
         WHERE agents.id = ranked.id
           AND ranked.rn > 1
    """))

    # 4. Dedup corner variant (admin-axis; same pattern)
    bind.execute(text("""
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY creator_developer_id, flare_corner_variant
                       ORDER BY flare_granted_at DESC NULLS LAST, id DESC
                   ) AS rn
              FROM agents
             WHERE flare_corner_variant IS NOT NULL
        )
        UPDATE agents
           SET flare_corner_variant = NULL
          FROM ranked
         WHERE agents.id = ranked.id
           AND ranked.rn > 1
    """))


def downgrade() -> None:
    # Dedup is a data fix — there's nothing to "un-dedup."
    # Restoring the duplicates would require re-running 0046's backfill
    # which is also conceptually a no-op (TRUE flags don't un-toggle).
    pass
