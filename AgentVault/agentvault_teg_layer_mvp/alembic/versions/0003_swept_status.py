"""V0050: add SWEPT label to crosstegtransferstatus

Terminal write-down status for stale async-leg bookkeeping rows
(cross_teg_transfers stuck in FUNDS_LOCKED whose value already settled or
refunded via the escrow ledger). Applied by coordinator.sweep_stale_bookkeeping.
Kept distinct from FAILED/COMPENSATED so failure analytics stay truthful.
"""

revision = '0003_swept_status'
down_revision = '0002_wrapped_balance'

from alembic import op


def upgrade():
    # ADD VALUE can run inside a transaction on PG>=12 but the new label can't
    # be USED in the same transaction; an autocommit block sidesteps both that
    # and the older-PG hard prohibition. IF NOT EXISTS keeps it idempotent
    # across the fleet's per-boot `alembic upgrade head`.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE crosstegtransferstatus ADD VALUE IF NOT EXISTS 'SWEPT'")


def downgrade():
    # PostgreSQL cannot drop an enum label; the unused label is harmless.
    pass
