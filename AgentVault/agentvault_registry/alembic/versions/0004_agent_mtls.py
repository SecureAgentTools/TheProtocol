"""f052: Add agent mTLS identity fields (IRONHAND)

Adds SPIFFE identity columns to agents table for opt-in mTLS enrollment.
Agents can request a SPIRE SVID via POST /api/v1/agent/enable-mtls.

Revision ID: 0004_agent_mtls
Revises: 0003_cloud_hosting
Create Date: 2026-04-01
"""
from alembic import op
from sqlalchemy import text

revision = '0004_agent_mtls'
down_revision = '0003_cloud_hosting'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(text(
        "ALTER TABLE agents "
        "ADD COLUMN IF NOT EXISTS spiffe_id VARCHAR(255)"
    ))
    conn.execute(text(
        "ALTER TABLE agents "
        "ADD COLUMN IF NOT EXISTS mtls_enabled BOOLEAN NOT NULL DEFAULT FALSE"
    ))
    conn.execute(text(
        "ALTER TABLE agents "
        "ADD COLUMN IF NOT EXISTS mtls_enrolled_at TIMESTAMPTZ"
    ))


def downgrade() -> None:
    pass  # mTLS fields are additive; no downgrade needed
