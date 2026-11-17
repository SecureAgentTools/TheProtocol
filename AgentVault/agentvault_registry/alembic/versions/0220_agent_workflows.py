"""V0663 (agent workflows): a workflow is a parent record over Guild orders.

`agent_workflows`: the owner (an agent DID), a title, one ruleset (JSON, hashed), a total budget in one currency and a
status (draft, running, done, cancelled). `agent_workflow_steps`: the steps in order, each a role with its spec, its
acceptance test (text), its budget, its own ruleset, the step whose output it takes as input, and, once the workflow
runs, the Guild order that carries it and the hash of its output and its receipt.

No new money path: every step is an ordinary Guild order posted by the workflow's owner, escrowed by the Guild rail when
it posts. The only change to an existing rail is a deny-only check at bid and award for an order that belongs to a step.
Additive; the two-step rule applies (downgrade first from an image that has it, then the older image). The tables are
named agent_workflows so they never meet agent_cicd's deploy "pipelines".

Revision ID: 0220_agent_workflows
Revises: 0219_chat_agent_status
"""
from alembic import op
import sqlalchemy as sa

revision = "0220_agent_workflows"
down_revision = "0219_chat_agent_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_workflows",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("owner_did", sa.String(120), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("ruleset", sa.JSON(), nullable=False),
        sa.Column("ruleset_hash", sa.String(64), nullable=False),
        sa.Column("total_budget", sa.Numeric(38, 18), nullable=False),
        sa.Column("currency", sa.String(12), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_agent_workflows_owner", "agent_workflows", ["owner_did", "created_at"])
    op.create_table(
        "agent_workflow_steps",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workflow_id", sa.String(40), sa.ForeignKey("agent_workflows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("step_key", sa.String(40), nullable=False),
        sa.Column("role", sa.String(80), nullable=False),
        sa.Column("spec", sa.Text(), nullable=True),
        sa.Column("acceptance", sa.Text(), nullable=True),
        sa.Column("budget", sa.Numeric(38, 18), nullable=False),
        sa.Column("deadline_seconds", sa.Integer(), nullable=True),
        sa.Column("ruleset", sa.JSON(), nullable=False),
        sa.Column("input_from", sa.String(40), nullable=True),
        sa.Column("order_id", sa.String(40), nullable=True),
        sa.Column("output_hash", sa.String(64), nullable=True),
        sa.Column("receipt", sa.String(64), nullable=True),
        sa.UniqueConstraint("workflow_id", "step_key", name="uq_agent_workflow_step_key"),
        sa.UniqueConstraint("workflow_id", "position", name="uq_agent_workflow_step_pos"),
    )
    op.create_index("ix_agent_workflow_steps_order", "agent_workflow_steps", ["order_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_workflow_steps_order", table_name="agent_workflow_steps")
    op.drop_table("agent_workflow_steps")
    op.drop_index("ix_agent_workflows_owner", table_name="agent_workflows")
    op.drop_table("agent_workflows")
