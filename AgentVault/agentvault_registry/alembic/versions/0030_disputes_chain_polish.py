"""Disputes/Settlements chain polish — X1 + S1 + S2 (2026-05-06)

Revision ID: 0030_disputes_chain_polish
Revises: 0029_canary_system_tables

Three column-level changes in one migration:

  X1 (chain): ADD COLUMN disputes.contract_id INTEGER NULL
      Allows /api/v1/contracts/{id}/malpractice to thread the source
      contract id into the new dispute row, so Disputes.vue can render
      a "View source contract →" link in the dispute drawer (DF1, frontend
      already wired).

      Soft int reference (NOT a foreign key). Matches the existing convention
      where `cross_registry_settlements.dispute_id` carries no FK because the
      referenced row may live on a remote registry.

  S1 (saga): ALTER COLUMN cross_registry_settlements.saga_state
              SET DEFAULT 'INITIATED'  (was 'LEGACY')
      The DB DEFAULT was vestigial — every code path explicitly sets the
      saga_state on row creation. The 'LEGACY' default existed only for
      pre-saga rows during the saga-tracking rollout. New rows should land
      as INITIATED to match the saga state machine's start state.

  S2 (cleanup): DROP COLUMN cross_registry_settlements.evidence_hash
      Confirmed unused — only ever set to "" in 2 code paths
      (federation_disputes.py:264, crud_disputes.py:586). Never read. Drop
      to remove the column from the public schema surface.

All ops are idempotent (`IF EXISTS` / `IF NOT EXISTS`) so this can re-run
without error if migration_bridge replays it.

Note on cluster rollout (per memory `feedback_cloud_op_image_alembic_stamp_only`):
cloud-op image startup uses Base.metadata.create_all + alembic stamp heads,
NOT alembic upgrade. Cloud-op DBs created BEFORE this migration ships will
need a manual `alembic upgrade head` to pick up these column changes. Frame
A registry-a is the first target; sandbox A/B + Frame B + cloud ops follow
in the evening cluster rollout.
"""

from alembic import op
from sqlalchemy import text


revision = "0030_disputes_chain_polish"
down_revision = "0029_canary_system_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # X1: disputes.contract_id (nullable int, no FK — soft reference)
    bind.execute(text(
        "ALTER TABLE disputes "
        "ADD COLUMN IF NOT EXISTS contract_id INTEGER"
    ))
    # Index helps when Disputes.vue filters disputes by source contract.
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_disputes_contract_id "
        "ON disputes (contract_id) WHERE contract_id IS NOT NULL"
    ))

    # S1: saga_state DEFAULT → 'INITIATED'
    # Existing rows keep their stored value; only new rows pick up the new default.
    bind.execute(text(
        "ALTER TABLE cross_registry_settlements "
        "ALTER COLUMN saga_state SET DEFAULT 'INITIATED'"
    ))

    # S2: drop dead evidence_hash column
    bind.execute(text(
        "ALTER TABLE cross_registry_settlements "
        "DROP COLUMN IF EXISTS evidence_hash"
    ))


def downgrade() -> None:
    bind = op.get_bind()

    # S2 reverse: re-add evidence_hash as nullable VARCHAR(255)
    bind.execute(text(
        "ALTER TABLE cross_registry_settlements "
        "ADD COLUMN IF NOT EXISTS evidence_hash VARCHAR(255)"
    ))

    # S1 reverse: saga_state DEFAULT → 'LEGACY'
    bind.execute(text(
        "ALTER TABLE cross_registry_settlements "
        "ALTER COLUMN saga_state SET DEFAULT 'LEGACY'"
    ))

    # X1 reverse: drop the index, then the column
    bind.execute(text("DROP INDEX IF EXISTS ix_disputes_contract_id"))
    bind.execute(text("ALTER TABLE disputes DROP COLUMN IF EXISTS contract_id"))
