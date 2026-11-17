"""V0664 consoles (C2, order gwo_ebaafc5c4af1fa3a6858e55d): a proxy's last status report, one row per agent.

  agent_proxy_status   agent_did (the key), reported_at, report (the JSON text of the report: names and counts, 16 KiB at most,
                       checked by services/proxy_status before it is written)

Additive; rolling back drops the table (the reports are re-posted by the proxies within their report interval). The two-step rule
applies (downgrade first from an image that has it, then the older image). No event is emitted per report.

Revision ID: 0229_proxy_status
Revises: 0228_workflow_templates
"""
from alembic import op
import sqlalchemy as sa

revision = "0229_proxy_status"
down_revision = "0228_workflow_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_proxy_status",
        sa.Column("agent_did", sa.String(120), primary_key=True),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("report", sa.Text(), nullable=False),
    )
    op.create_index("ix_agent_proxy_status_reported_at", "agent_proxy_status", ["reported_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_proxy_status_reported_at", table_name="agent_proxy_status")
    op.drop_table("agent_proxy_status")
