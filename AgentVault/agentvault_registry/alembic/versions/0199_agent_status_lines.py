"""V0650 (a) (2026-10-31, agentvault2-14): an agent's status line.

An agent says what it is doing in one line that expires on its own (PUT /api/v1/agents/me/status), and an
organization's members and agents read the organization's presence (GET /api/v1/organizations/{org_id}/presence). One
row per agent; the row goes with the agent (ON DELETE CASCADE). Nothing else reads the table, and the downgrade drops it
with every status line in it.

V0650's migrations form one chain at the cut: 0198_chat_approvals, 0199_agent_status_lines, 0200, 0201. On this branch
the revision follows 0197; the cut re-points its down_revision to 0198_chat_approvals inside the merge commit.

Revision ID: 0199_agent_status_lines
Revises: 0198_chat_approvals
Create Date: 2026-10-31
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0199_agent_status_lines"
down_revision: Union[str, None] = "0198_chat_approvals"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_status_lines",
        sa.Column("agent_did", sa.String(), sa.ForeignKey("agents.did", ondelete="CASCADE"), primary_key=True),
        sa.Column("status_text", sa.String(140), nullable=False),
        sa.Column("set_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("agent_status_lines")
