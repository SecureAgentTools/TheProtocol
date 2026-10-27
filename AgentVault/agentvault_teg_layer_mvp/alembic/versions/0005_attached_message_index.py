"""General index on teg_transactions.attached_message (perf — exref replay lookup).

ROOT CAUSE (frame-b AGORA throughput collapse, 2026-06-13): the exchange-mover
replay lookup `WHERE attached_message = :ref` (and every other attached_message
equality lookup) had no usable index on frame-b — only the PARTIAL exref index
(0004), which the planner can't use for a plain equality (its WHERE has a status
+ time-cutoff the query doesn't carry). So the lookup fell back to a backward
scan of the timestamp index over 13.3M rows / 9 GB ≈ ~1s PER MOVE → settlement
couldn't keep pace → escrow-row convoy under load.

frame-a and frame-c already had this exact index (`idx_teg_tx_attached_message`)
but it was created MANUALLY and never captured in a migration — so frame-b (and
any fresh frame) silently lacked it. This migration makes it permanent + fleet-
uniform. IF NOT EXISTS → no-op where it already exists (A/C, and frame-b after
the 2026-06-13 manual CONCURRENT build). On a fresh frame teg_transactions is
tiny, so the non-concurrent build here is instant; large existing frames already
have it and skip.
"""

revision = '0005_attached_message_index'
down_revision = '0004_exref_unique'

from alembic import op


def upgrade():
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_teg_tx_attached_message "
        "ON teg_transactions (attached_message)"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_teg_tx_attached_message")
