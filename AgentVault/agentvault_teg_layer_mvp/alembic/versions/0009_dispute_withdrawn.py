"""V0658 (D6-825): add WITHDRAWN to the dispute status, the status of a dispute its claimant withdrew while it was OPEN.

A claimant withdraws its own OPEN dispute on POST /api/v1/disputes/{dispute_log_id}/withdraw: no ruling, no penalty, no
money; the row keeps who withdrew it and when (resolution_notes). The label goes to the enum type the column actually has,
read from the catalog: on every database the squash made that is dispute_status_enum (0001 also creates a disputestatus
type that no column uses, and SQLAlchemy's create_all would name the type disputestatus). Idempotent (IF NOT EXISTS), as
the per-boot replay of every migration after 0001 needs (migration_bridge.py).

Rollback: PostgreSQL cannot drop an enum label, and the unused label is harmless. A row that holds it is not: an older TEG
image cannot read WITHDRAWN (its DisputeStatus has no such member), so before rolling the TEG image back, return those rows
to OPEN, where every dispute stood before a claimant could withdraw one (their notes keep the withdrawal):
    UPDATE teg_dispute_logs SET status = 'OPEN' WHERE status = 'WITHDRAWN';
"""
import re

import sqlalchemy as sa
from alembic import op

revision = '0009_dispute_withdrawn'
down_revision = '0008_widen_memo_errmsg_text'
branch_labels = None
depends_on = None

COLUMN_ENUM = sa.text(
    "SELECT t.typname FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
    "JOIN pg_namespace n ON n.oid = c.relnamespace JOIN pg_type t ON t.oid = a.atttypid "
    "WHERE n.nspname = 'public' AND c.relname = 'teg_dispute_logs' AND a.attname = 'status' AND t.typtype = 'e'")


def upgrade():
    typ = op.get_bind().execute(COLUMN_ENUM).scalar()
    if typ is None:
        return   # no such table, or a status column that is no enum: nothing to label
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", typ):
        raise RuntimeError(f"teg_dispute_logs.status has an enum type named {typ!r}, which this migration will not quote")
    # ADD VALUE in an autocommit block, as 0003 does (the label is usable once that statement commits).
    with op.get_context().autocommit_block():
        op.execute(f"ALTER TYPE public.{typ} ADD VALUE IF NOT EXISTS 'WITHDRAWN'")


def downgrade():
    # PostgreSQL cannot drop an enum label; see the rollback note above for the rows that hold it.
    pass
