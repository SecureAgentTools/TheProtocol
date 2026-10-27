"""AGORA incident 2026-06-13: hard uniqueness for exchange-mover exref legs.

The /admin/exchange/move replay guard is a lookup — it protects sequential
retries but not CONCURRENT ones. Under the frame-b TEG pool/lock convoy a
timed-out attempt was still queued when the caller retried; both committed and
the leg executed twice (1,850 duplicate legs, ~3.6k AVT drained from
exchange_escrow against its books). This partial UNIQUE index turns every such
collision into an IntegrityError at create_transfer (the PENDING row commits
BEFORE the balance transaction): the loser moves no money and the caller's
replay lookup converges on exactly one execution.

Predicate notes:
  • status IN (PENDING, COMPLETED): PENDING rows are in-flight and must block
    duplicates; FAILED rows moved no money and must FREE the key so the worker
    retry can re-execute the leg (status filter added to the endpoint's replay
    lookup in the same change).
  • time cutoff: the duplicate HISTORY from the incident is immutable ledger
    and must not block index creation; uniqueness is enforced for all rows
    written after the incident window closed.
The exref: namespace is exclusively the exchange mover's (fx uses fxref:),
and every leg key is distinct by design.
"""

revision = '0004_exref_unique'
down_revision = '0003_swept_status'

from alembic import op


def upgrade():
    # IF NOT EXISTS keeps the per-boot `alembic upgrade head` replay idempotent
    # (migration_bridge re-stamps on every boot, fleet doctrine).
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_teg_tx_exref_live "
        "ON teg_transactions (attached_message) "
        "WHERE attached_message LIKE 'exref:%' "
        "AND status IN ('pending', 'completed') "
        "AND timestamp > '2026-06-13T01:45:00+00:00'"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS uq_teg_tx_exref_live")
