"""§BATCH7 (2026-09-05) — three TEG audit events that were structurally DENIED gain their policy rows.

The TEG emitter is fail-closed: a type with no `emit_from_teg=true` row is dropped, and `emit()` returns
without raising. Three sweeper/reconciler audit events had NO row while a sibling in the same file had one
(agentvault2-eb's AST census, sessionlogs2026/EVENT_TYPE_MAP_2026-09-05.md):
  - CrossTEGStaleOutflowSwept   (sweeper.py; sibling CrossTEGStaleSwept is allowed since mig 0057)
  - ExchangeOrphanExrefLegSwept (sweeper.py)
  - OrphanedEscrowLockReleased  (escrow_lock_reconciler.py; sibling NegativeEscrowLockClamped is allowed)
They fire RARELY, which is why the gap never showed as a counter. Same shape as mig 0057: emit_from_teg=true,
emit_from_registry=false, skip_in_projection=true — audit only, the balance legs are LedgerBalanceChanged.

Revision ID: 0175_teg_audit_policy_rows
Revises: 0174_json_columns_to_jsonb
"""
from alembic import op
from sqlalchemy import text

revision = "0175_teg_audit_policy_rows"
down_revision = "0174_json_columns_to_jsonb"
branch_labels = None
depends_on = None

_NEW_TYPES = ("CrossTEGStaleOutflowSwept", "ExchangeOrphanExrefLegSwept", "OrphanedEscrowLockReleased")


def upgrade() -> None:
    bind = op.get_bind()
    for evt in _NEW_TYPES:
        bind.execute(text("""
            INSERT INTO event_emission_policies
                (event_type, emit_from_teg, emit_from_registry, skip_in_projection)
            VALUES (:evt, true, false, true)
            ON CONFLICT (event_type) DO NOTHING;
        """), {"evt": evt})


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("""
        DELETE FROM event_emission_policies
        WHERE event_type IN ('CrossTEGStaleOutflowSwept', 'ExchangeOrphanExrefLegSwept', 'OrphanedEscrowLockReleased');
    """))
