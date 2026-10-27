"""Scrub orphan per-agent flare variant columns (§pass22, 2026-05-16).

Revision ID: 0056_flare_variant_orphan_scrub
Revises: 0055_agent_health_column

Commander reported a recurring complaint: "my flare for an agent was changed
back to Boris instead of keeping it at Sybil". Playwright investigation
confirmed the visible bug — on /my-agents the variant picker shows
"CROWN → Backstabbing Boris" and "SAURON → Crucible" even though neither
agent currently bears the relevant slot. Sybil and Crucible bear correctly,
Boris bears nothing — but Boris keeps `flare_corner_variant='crown'` from
when he was the previous corner-bearer, and Crucible keeps
`flare_encirclement_variant='sauron'` from when it was the previous
encirclement-bearer.

§pass15 (migration 0055) already scrubbed `flare_tier`/`flare_granted_at`/
`flare_source_purchase_id` on agents with bears_*_flare=FALSE, but missed
the per-agent variant columns. This migration completes the cleanup.

The code-side fix is in routers/fiat_onramp.py:equip_flare_slot — when
un-bearing a sibling for a slot, the corresponding variant column is now
also cleared (mirroring what unequip_flare_slot already does for the
target since §24).
"""
from typing import Sequence, Union
from alembic import op
from sqlalchemy import text


revision: str = '0056_flare_variant_orphan_scrub'
down_revision: Union[str, None] = '0055_agent_health_column'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # §pass42 (2026-05-18) — Sovereign-immune cleanup. Per §pass39 the
    # sovereign tier is DID-locked and its variant is intrinsic identity,
    # not slot-occupancy state. Excluding sovereign rows also makes this
    # migration idempotent under the prior migration_bridge bug where the
    # bridge re-stamped post-squash DBs back to 0001_squash and forced
    # this migration to run on every container boot — wiping sovereign
    # signature variants each restart.

    # Clear flare_corner_variant on agents that don't bear the corner slot.
    bind.execute(text("""
        UPDATE agents
           SET flare_corner_variant = NULL
         WHERE bears_corner_flare = FALSE
           AND flare_corner_variant IS NOT NULL
           AND flare_tier IS DISTINCT FROM 'sovereign'
    """))

    # Clear flare_encirclement_variant on agents that don't bear the encirclement slot.
    bind.execute(text("""
        UPDATE agents
           SET flare_encirclement_variant = NULL
         WHERE bears_encirclement_flare = FALSE
           AND flare_encirclement_variant IS NOT NULL
           AND flare_tier IS DISTINCT FROM 'sovereign'
    """))

    # Clear flare_encirclement_overlay on agents that don't bear the encirclement
    # slot. The overlay is a second axis on the same slot — same orphan rule.
    bind.execute(text("""
        UPDATE agents
           SET flare_encirclement_overlay = NULL
         WHERE bears_encirclement_flare = FALSE
           AND flare_encirclement_overlay IS NOT NULL
           AND flare_tier IS DISTINCT FROM 'sovereign'
    """))


def downgrade() -> None:
    # No downgrade — this is a defensive cleanup. Restoring the orphan
    # variant data would only re-confuse the variant picker.
    pass
