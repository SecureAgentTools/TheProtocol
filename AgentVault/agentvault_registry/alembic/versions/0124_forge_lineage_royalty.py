"""0124 — GÖDEL FORGE: bundle fork-lineage + royalty, eval code_patch/holdout (2026-07-19).

Additive-only, idempotent (ADD COLUMN IF NOT EXISTS), chains 0123. Byte-inert until
FORGE_ENABLED. Supports the Darwin-Gödel self-improving-harness feature:
  • agent_bundles.forked_from_bundle_id — queryable fork lineage (today only in the
    ES BundleCreated event data); nearest-ancestor chain for royalty carve.
  • agent_bundles.royalty_bps — creator-set fork royalty (0..500), carved Δ-neutrally
    up to 3 fork-ancestors at eval-pay / guild-settle (legs sum to original by construction).
  • eval_tasks.holdout — hidden-test flag: the expected output is never shown to the
    target agent (anti eval-hacking; Sakana observed agents faking test logs).
  • eval_tasks.grader_config — per-task grader params (e.g. code_patch repo ref, test cmd).
task_type / scorer are free String(24) → 'code_patch' needs no constraint change.
Δ-irrelevant (schema only). Rollback tolerant: older image ignores the extra columns.
"""
from alembic import op
from sqlalchemy import text

# revision id MUST be ≤32 chars (alembic_version.version_num is varchar(32)).
revision: str = "0124_forge_lineage"
down_revision: str = "0123_agent_deleg_creds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text(
        "ALTER TABLE agent_bundles ADD COLUMN IF NOT EXISTS forked_from_bundle_id UUID "
        "REFERENCES agent_bundles(id) ON DELETE SET NULL"))
    bind.execute(text(
        "ALTER TABLE agent_bundles ADD COLUMN IF NOT EXISTS royalty_bps INTEGER NOT NULL DEFAULT 0"))
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_agent_bundles_forked_from "
        "ON agent_bundles (forked_from_bundle_id)"))
    bind.execute(text(
        "ALTER TABLE eval_tasks ADD COLUMN IF NOT EXISTS holdout BOOLEAN NOT NULL DEFAULT FALSE"))
    bind.execute(text(
        "ALTER TABLE eval_tasks ADD COLUMN IF NOT EXISTS grader_config JSONB"))


def downgrade() -> None:
    # Additive-only; never dropped on rollback (an older image tolerates the extra columns).
    pass
