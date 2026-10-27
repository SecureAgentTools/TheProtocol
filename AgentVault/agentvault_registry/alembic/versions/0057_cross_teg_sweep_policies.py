"""Add event_emission_policies rows for the cross-TEG 2PC sweeper.

Revision ID: 0057_cross_teg_sweep
Revises: 0056_flare_variant_orphan_scrub
Create Date: 2026-05-17

§pass26 — Durable 2PC coordination sweeper.

Adds explicit emission policies for three new event types emitted by the
TEG-side sweeper that closes the stuck-2PC class of bugs documented in
`memory/project_lock_leak_teg_metadata_class.md`.

Event types (all TEG-emitted, audit-only):

  - CrossTEGCoordinationAbortedByExpiry   emit_from_teg=true   skip_in_projection=true
  - CrossTEGCoordinationCommitResumed     emit_from_teg=true   skip_in_projection=true
  - CrossTEGSweepErrored                  emit_from_teg=true   skip_in_projection=true

skip_in_projection=true because:
  - AbortedByExpiry: the balance restoration is via `_compensate_transfer`
    which decrements `locked_balance` only (token_balance was never debited
    on the INITIATED happy-path-prefix). No supply-counted event.
  - CommitResumed: audit trail only — no actual token motion (operator
    review required for partial-commit cases).
  - SweepErrored: pure observability/error signal.

TEG fails closed on unknown event types (`event_emitter.py:_teg_should_emit`),
so these rows MUST exist before the sweeper container goes live.

Idempotent via ON CONFLICT DO NOTHING. Downgrade removes the rows.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "0057_cross_teg_sweep"
down_revision: Union[str, None] = "0056_flare_variant_orphan_scrub"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_TYPES = (
    "CrossTEGCoordinationAbortedByExpiry",
    "CrossTEGCoordinationCommitResumed",
    "CrossTEGSweepErrored",
)


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
        WHERE event_type IN (
            'CrossTEGCoordinationAbortedByExpiry',
            'CrossTEGCoordinationCommitResumed',
            'CrossTEGSweepErrored'
        );
    """))
