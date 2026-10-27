"""§bc2 T2.3 — broadcast EventStore audit policies.

Revision ID: 0069_broadcast_event_emission_policies
Revises: 0068_agent_flags
Create Date: 2026-05-19

Three new event types for broadcast lifecycle audit. All three follow the
admin-broadcast-policy convention: emitted by registry (NOT TEG),
skip_in_projection because broadcasts don't move tokens — they're pure
audit trail consumed by reactor watchers + admin-event-ledger UI.

These complement the WS-side `broadcast.retracted` / `broadcast.updated`
events shipped in §bc1 T1.4. Those are user-facing live updates; THESE
are immutable audit rows so the security team can answer "which admin
sent broadcast X at time Y" months later when the WS push is long gone.

Idempotent via ON CONFLICT (event_type) DO NOTHING — re-running on a DB
that already has these rows is a no-op.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0069_bc2_audit_policies"
down_revision: Union[str, None] = "0068_agent_flags"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO event_emission_policies
            (event_type, emit_from_teg, emit_from_registry, skip_in_projection)
        VALUES
            ('AdminBroadcastSent',      false, true, true),
            ('AdminBroadcastEdited',    false, true, true),
            ('AdminBroadcastRetracted', false, true, true)
        ON CONFLICT (event_type) DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM event_emission_policies
        WHERE event_type IN (
            'AdminBroadcastSent',
            'AdminBroadcastEdited',
            'AdminBroadcastRetracted'
        );
    """)
