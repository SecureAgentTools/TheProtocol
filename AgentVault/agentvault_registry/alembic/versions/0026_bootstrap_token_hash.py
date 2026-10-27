"""Add token_value_hash to bootstrap_tokens (Issue 1, P23-001 — 2026-04-30).

Revision ID: 0026_bootstrap_token_hash
Revises: 0025_revoked_event_policies

Two-column transition: keep `token_value` (plaintext) for one prod cycle so any
already-issued tokens (5-min TTL) still validate via the legacy fallback path
in CRUD. New issuances populate BOTH columns. Validation path looks up by
hash first, falls back to plaintext column if hash is NULL.

Future migration (0027 or later) can drop `token_value` once the rollout has
soaked.

Idempotent (`IF NOT EXISTS` on column + index) so `migration_bridge.py` replays
on every container boot remain safe.
"""

from alembic import op
from sqlalchemy import text


revision = "0026_bootstrap_token_hash"
down_revision = "0025_revoked_event_policies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("""
        ALTER TABLE bootstrap_tokens
        ADD COLUMN IF NOT EXISTS token_value_hash VARCHAR(64) NULL
    """))
    bind.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_bootstrap_tokens_token_value_hash
        ON bootstrap_tokens (token_value_hash)
    """))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("""
        DROP INDEX IF EXISTS ix_bootstrap_tokens_token_value_hash
    """))
    bind.execute(text("""
        ALTER TABLE bootstrap_tokens
        DROP COLUMN IF EXISTS token_value_hash
    """))
