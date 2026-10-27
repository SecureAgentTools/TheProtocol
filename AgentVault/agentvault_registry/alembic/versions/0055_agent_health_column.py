"""Add agents.last_health column + Boris-orphan flare_tier cleanup (Tier C, 2026-05-15).

Revision ID: 0055_agent_health_column
Revises: 0054_flare_encirclement_overlay

Two unrelated cleanups bundled — both are sandbox-first, both backfill
existing rows defensively, both raw-SQL with IF NOT EXISTS guards per
feedback_migration_use_raw_sql_if_not_exists.md.

──────────────────────────────────────────────────────────────────────────
Tier C-1 — Health-flap fix
──────────────────────────────────────────────────────────────────────────
`agent_health_checker.py` was comparing the probe result (`healthy` /
`unhealthy` / `unreachable`) against the agent's `status` column, which
holds a mix of governance state (`active`, `suspended`, `revoked`) and
historical health state. Most active agents have `status='active'`, the
probe always returns `'healthy'`, so the inequality always tripped — every
single agent reported a "status change" every 5-min cycle.

Symptom: registry-a logged
  "[AgentHealth] Checked 100 agents, 100 status changes"
every cycle, fanning 1,200 false webhook deliveries per hour per registry.

Fix: separate the health probe state from governance state. New column
`agents.last_health VARCHAR(20) NULL` tracks the LAST probe result. The
checker compares the new probe to `last_health` (not `status`). Governance
state stays untouched. NULL → first observation, write but don't fire.

──────────────────────────────────────────────────────────────────────────
Tier C-2 — Boris-orphan cleanup
──────────────────────────────────────────────────────────────────────────
Historical /flare/equip handler cleared `bears_*_flare` flags on a losing
sibling but never cleared its legacy `flare_tier`. Over time some agents
accumulated `flare_tier='shadow_chancellor'` while bearing neither slot —
e.g., Backstabbing Boris on Commander's account. Legacy renderers seeing
just `flare_tier` would show a faux "bearer" indication.

This migration clears the orphan legacy fields. The /flare/equip endpoint
also gets a code-side fix in this same session to prevent regression.
"""
from typing import Sequence, Union
from alembic import op
from sqlalchemy import text


revision: str = '0055_agent_health_column'
down_revision: Union[str, None] = '0054_flare_encirclement_overlay'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # ─── Tier C-1: Add agents.last_health column ──────────────────────────
    bind.execute(text("""
        ALTER TABLE agents
        ADD COLUMN IF NOT EXISTS last_health VARCHAR(20) NULL
    """))

    # Seed last_health from existing status WHEN it already happens to be a
    # health value. Otherwise leave NULL — the checker will populate on its
    # next probe and skip the webhook (first-observation rule).
    bind.execute(text("""
        UPDATE agents
           SET last_health = status
         WHERE last_health IS NULL
           AND status IN ('healthy', 'unhealthy', 'unreachable')
    """))

    # ─── Tier C-2: Clear orphan flare_tier on non-bearer agents ───────────
    # An agent that no longer bears either flare slot should not carry a
    # legacy flare_tier. Without this cleanup, legacy renderers reading
    # `flare_tier` independently of `bears_*_flare` show faux-bearer state.
    #
    # §pass42 (2026-05-18) — Sovereign-immune cleanup. Per §pass39, the
    # sovereign tier is categorically DID-locked and intrinsic to the
    # agent's identity (NOT a backer's slot-occupancy state). Excluding
    # 'sovereign' here also makes this migration idempotent if it gets
    # re-applied (it shouldn't, but the migration_bridge used to re-stamp
    # post-squash DBs back to 0001_squash and force the migration to re-run
    # every container boot — destroying the sovereign data each time).
    bind.execute(text("""
        UPDATE agents
           SET flare_tier              = NULL,
               flare_granted_at        = NULL,
               flare_source_purchase_id = NULL
         WHERE bears_corner_flare       = FALSE
           AND bears_encirclement_flare = FALSE
           AND flare_tier              IS NOT NULL
           AND flare_tier              IS DISTINCT FROM 'sovereign'
    """))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("""
        ALTER TABLE agents DROP COLUMN IF EXISTS last_health
    """))
    # No downgrade for the flare_tier cleanup — it was a defensive scrub
    # and re-introducing the orphan rows would only mislead renderers.
