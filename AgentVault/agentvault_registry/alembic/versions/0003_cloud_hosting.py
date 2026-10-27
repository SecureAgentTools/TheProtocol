"""f051: Add cloud hosting fields to operator_applications

Supports cloud-hosted operator registries (beta). Adds fields for tracking
cloud deployment status, URL, port allocation, and stack directory.

Revision ID: 0003_cloud_hosting
Revises: 0002_fix_financial_types
Create Date: 2026-03-31
"""
from alembic import op
from sqlalchemy import text

revision = '0003_cloud_hosting'
down_revision = '0002_fix_financial_types'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(text(
        "ALTER TABLE operator_applications "
        "ADD COLUMN IF NOT EXISTS cloud_hosted BOOLEAN NOT NULL DEFAULT FALSE"
    ))
    conn.execute(text(
        "ALTER TABLE operator_applications "
        "ADD COLUMN IF NOT EXISTS cloud_url VARCHAR(255)"
    ))
    conn.execute(text(
        "ALTER TABLE operator_applications "
        "ADD COLUMN IF NOT EXISTS cloud_port_base INTEGER"
    ))
    conn.execute(text(
        "ALTER TABLE operator_applications "
        "ADD COLUMN IF NOT EXISTS cloud_provisioned_at TIMESTAMPTZ"
    ))
    conn.execute(text(
        "ALTER TABLE operator_applications "
        "ADD COLUMN IF NOT EXISTS cloud_torn_down_at TIMESTAMPTZ"
    ))
    conn.execute(text(
        "ALTER TABLE operator_applications "
        "ADD COLUMN IF NOT EXISTS cloud_stack_dir VARCHAR(500)"
    ))


def downgrade() -> None:
    pass  # Cloud hosting fields are additive; no downgrade needed
