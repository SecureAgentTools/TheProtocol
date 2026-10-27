"""§2026-06-25 per-user hardening (A): enforce non-negative TEG balances at the DB level.

The TEG transfer/escrow/stake services already check sufficiency before debiting, so a
negative agent balance is structurally unreachable in practice (the fleet-wide audit found
0/0 on all 16 TEGs). This adds a belt-and-suspenders CHECK so a future regression CANNOT
persist a negative token_balance or locked_balance — the "can't go negative at all"
guarantee. Idempotent + guarded; a table with a pre-existing negative would fail the ADD
(a finding to investigate, never to mask). Pairs with the auditor I3 transit-aware
per-user classification (orphan/escrow projection residue excluded from the breach).
"""
from alembic import op

# revision identifiers
revision = "0007_balance_nonneg"
down_revision = "0006_fxref_unique"
branch_labels = None
depends_on = None

DDL_UP = """
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='chk_teg_token_balance_nonneg'
                 AND conrelid='agent_teg_profiles'::regclass) THEN
    ALTER TABLE agent_teg_profiles ADD CONSTRAINT chk_teg_token_balance_nonneg
      CHECK (token_balance >= 0);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='chk_teg_locked_balance_nonneg'
                 AND conrelid='agent_teg_profiles'::regclass) THEN
    ALTER TABLE agent_teg_profiles ADD CONSTRAINT chk_teg_locked_balance_nonneg
      CHECK (locked_balance >= 0);
  END IF;
END $$;
"""

DDL_DOWN = """
ALTER TABLE agent_teg_profiles DROP CONSTRAINT IF EXISTS chk_teg_token_balance_nonneg;
ALTER TABLE agent_teg_profiles DROP CONSTRAINT IF EXISTS chk_teg_locked_balance_nonneg;
"""


def upgrade():
    op.execute(DDL_UP)


def downgrade():
    op.execute(DDL_DOWN)
