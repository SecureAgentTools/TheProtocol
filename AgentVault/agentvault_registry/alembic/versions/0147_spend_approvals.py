"""B3 (RBAC plan) — agent spend approvals: the step-up queue behind require_approval_above.

Turns the hard deny at agent_authz.check_spend_policy's approval threshold into
park-and-resume: the denied spend creates a PENDING row here (+ a push to the owning
human), the human approves or denies it from the Approvals panel / Pocket, and the
agent's RETRY of the same spend consumes an APPROVED row exactly once.

Additive only — new table + indexes, nothing altered. Frames that run older code
simply never touch it (the §V0178 split-fleet pattern).

Revision ID: 0147_spend_approvals
Revises: 0146_org_treasury
"""
from alembic import op
import sqlalchemy as sa

revision = "0147_spend_approvals"
down_revision = "0146_org_treasury"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_spend_approvals",
        sa.Column("id", sa.String(44), primary_key=True),  # spa_<hex>
        sa.Column("agent_did", sa.String(120), nullable=False),
        sa.Column("developer_id", sa.Integer,
                  sa.ForeignKey("developers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action", sa.String(48), nullable=True),
        sa.Column("amount", sa.Numeric(30, 18), nullable=False),
        sa.Column("currency", sa.String(16), nullable=True),
        sa.Column("counterparty_did", sa.String(120), nullable=True),
        # pending | approved | denied | expired | consumed
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("reason", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_developer_id", sa.Integer, nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_spend_approvals_agent_status", "agent_spend_approvals",
                    ["agent_did", "status"])
    op.create_index("ix_spend_approvals_dev", "agent_spend_approvals", ["developer_id"])


def downgrade() -> None:
    op.drop_index("ix_spend_approvals_dev", table_name="agent_spend_approvals")
    op.drop_index("ix_spend_approvals_agent_status", table_name="agent_spend_approvals")
    op.drop_table("agent_spend_approvals")
