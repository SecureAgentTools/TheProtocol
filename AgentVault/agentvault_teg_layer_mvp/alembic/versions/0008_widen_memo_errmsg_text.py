"""§2026-06-25 widen TEG free-text columns varchar(500) → TEXT.

A descriptive memo / error_message is variable-length by nature; the varchar(500) cap was
overflowing on the FX/exchange escrow-move path (`POST /admin/fx/move`, `/admin/exchange/move`)
→ psycopg2.errors.StringDataRightTruncation → the move leg 5xx'd (Δ-safe: the INSERT rolls
back atomically, no fund movement — but the leg failed). Widening to TEXT removes the cap
without data loss (mirrors the V0112 `exchange_flags 255→TEXT` fix). Idempotent: only alters
a column still typed character varying.
"""
from alembic import op

revision = "0008_widen_memo_errmsg_text"
down_revision = "0007_balance_nonneg"
branch_labels = None
depends_on = None

DDL_UP = """
DO $do$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_name='cross_teg_transfers' AND column_name='memo'
               AND data_type='character varying') THEN
    ALTER TABLE cross_teg_transfers ALTER COLUMN memo TYPE TEXT;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_name='teg_transactions' AND column_name='error_message'
               AND data_type='character varying') THEN
    ALTER TABLE teg_transactions ALTER COLUMN error_message TYPE TEXT;
  END IF;
END $do$;
"""

# No-op downgrade: re-imposing varchar(500) could truncate rows written while TEXT was live
# (data loss) — intentionally not reverted. (Rollback the constraint/widen pass via image tag.)
DDL_DOWN = "-- intentionally no-op: re-narrowing TEXT→varchar(500) risks truncating live data"


def upgrade():
    op.execute(DDL_UP)


def downgrade():
    op.execute(DDL_DOWN)
