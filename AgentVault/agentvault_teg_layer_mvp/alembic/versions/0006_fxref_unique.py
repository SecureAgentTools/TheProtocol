"""0006_fxref_unique — partial UNIQUE index on the fx/move fxref: replay key.

The /admin/fx/move replay guard (endpoints_treasury.py) is a lookup, same as the
exchange mover's exref: was before 0004. A lookup protects SEQUENTIAL retries but
not CONCURRENT/queued ones: under a TEG pool/lock convoy a timed-out attempt can
still commit later while the caller's connection-drop retry (_teg_post_with_retry)
lookup-misses and fires again — double-executing one FX leg against the fx_reserve.
This is the identical class that drained ~3.6k AVT from exchange_escrow before 0004;
fx uses fxref: and was never covered by 0004's exref-only index.

This partial UNIQUE index turns every such collision into an IntegrityError at
create_transfer (the PENDING row commits BEFORE the balance transaction): the loser
moves no money, and the endpoint's IntegrityError handler converges the caller on
exactly one execution.

Predicate notes (mirrors 0004):
  • status IN (pending, completed): PENDING blocks in-flight duplicates; FAILED
    moved no money and must FREE the key so a genuine retry can re-execute.
  • time cutoff: there are zero live duplicate fxref keys today (verified read-only
    on teg-a/frame-c: 132k legs/3d, 0 dups), but a cutoff keeps the index build safe
    against any immutable historical duplicate and is the established pattern.
  • The fxref: namespace is exclusively fx/move's (the exchange mover uses exref:).

Built LIVE via CREATE UNIQUE INDEX CONCURRENTLY (statement_timeout=0) on the FX TEGs
because the table is large and CONCURRENTLY cannot run inside alembic's transaction;
this migration is IF NOT EXISTS so the container-start upgrade is a no-op when the
index already exists.
"""
from alembic import op

revision = '0006_fxref_unique'
down_revision = '0005_attached_message_index'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_teg_tx_fxref_live "
        "ON teg_transactions (attached_message) "
        "WHERE attached_message LIKE 'fxref:%' "
        "AND status IN ('pending', 'completed') "
        "AND timestamp > '2026-06-13T00:00:00+00:00'"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS uq_teg_tx_fxref_live")
