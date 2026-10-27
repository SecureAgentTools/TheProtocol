"""Add is_canary boolean column to agents (2026-05-04).

Revision ID: 0028_agents_is_canary
Revises: 0027_cross_frame_transfers_async

Phase 1 of the canary transfer system. Marks the 10 system agents that fire
continuous synthetic-transaction monitoring transfers cluster-wide. Used
later to filter canaries out of regular agent listings, leaderboards, and
rate limiting.

Idempotent (IF NOT EXISTS) so migration_bridge.py replays on every container
boot remain safe.
"""
from alembic import op


revision = "0028_agents_is_canary"
down_revision = "0027_cross_frame_transfers_async"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        ALTER TABLE agents
        ADD COLUMN IF NOT EXISTS is_canary BOOLEAN NOT NULL DEFAULT false;
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_agents_is_canary
        ON agents(is_canary) WHERE is_canary = true;
        """
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS idx_agents_is_canary;")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS is_canary;")
