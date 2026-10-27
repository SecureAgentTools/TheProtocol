"""Add event_emission_policies rows for the canary_rebalancer (§pass27 Phase 2).

Revision ID: 0058_canary_rebalancer_policies
Revises: 0057_cross_teg_sweep
Create Date: 2026-05-17

§pass27 Phase 2 — Canary rebalancer Tier-3 modal.

Adds explicit emission policies for two new event types emitted by the
registry-side `canary_rebalancer` worker when it refunds (or fails to
refund) a starved canary agent.

Event types (registry-emitted, audit-only):

  - CanaryRebalancerFunded   emit_from_registry=true   skip_in_projection=true
  - CanaryRebalancerErrored  emit_from_registry=true   skip_in_projection=true

skip_in_projection=true because:
  - Funded: the actual AVT motion is already counted via the
    TokensTransferred event emitted by `_fund_agent_from_treasury_internal`
    (or the cross-frame /teg/treasury/fund-agent HTTP fan-out).
    This audit row only records "rebalancer decided to refund".
  - Errored: pure observability — no token motion.

Registry emitter fail-closes on unknown event types (see
`event_emitter.py:_should_emit`), so these rows MUST exist before the
worker emits.

Idempotent via ON CONFLICT DO NOTHING. Downgrade removes the rows.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "0058_canary_rebalancer_policies"
down_revision: Union[str, None] = "0057_cross_teg_sweep"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_TYPES = (
    "CanaryRebalancerFunded",
    "CanaryRebalancerErrored",
)


def upgrade() -> None:
    bind = op.get_bind()
    for evt in _NEW_TYPES:
        bind.execute(text("""
            INSERT INTO event_emission_policies
                (event_type, emit_from_teg, emit_from_registry, skip_in_projection)
            VALUES (:evt, false, true, true)
            ON CONFLICT (event_type) DO NOTHING;
        """), {"evt": evt})


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("""
        DELETE FROM event_emission_policies
        WHERE event_type IN (
            'CanaryRebalancerFunded',
            'CanaryRebalancerErrored'
        );
    """))
