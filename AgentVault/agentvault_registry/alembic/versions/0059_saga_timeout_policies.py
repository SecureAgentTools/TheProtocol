"""Add event_emission_policies row for saga_timeout_checker (§pass27 Phase 3).

Revision ID: 0059_saga_timeout_policies
Revises: 0058_canary_rebalancer_policies
Create Date: 2026-05-17

§pass27 Phase 3 — Saga timeout checker Tier-3 modal.

Adds explicit emission policy for the new audit-only event emitted by the
registry-side `saga_timeout_checker` worker when a settlement saga
exceeds the 72h deadline.

Event types (registry-emitted, audit-only):

  - SettlementSagaTimedOut   emit_from_registry=true   skip_in_projection=true

skip_in_projection=true because:
  - Settlement saga timeouts are recorded by the saga state machine
    (status='timed_out'); this is an audit observability event with no
    additional token motion. Cross-frame compensation refunds already
    emit `CrossFrameTransferRefunded` + reverse `TokensTransferred`.

Idempotent via ON CONFLICT DO NOTHING. Downgrade removes the row.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "0059_saga_timeout_policies"
down_revision: Union[str, None] = "0058_canary_rebalancer_policies"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("""
        INSERT INTO event_emission_policies
            (event_type, emit_from_teg, emit_from_registry, skip_in_projection)
        VALUES ('SettlementSagaTimedOut', false, true, true)
        ON CONFLICT (event_type) DO NOTHING;
    """))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("""
        DELETE FROM event_emission_policies
        WHERE event_type = 'SettlementSagaTimedOut';
    """))
