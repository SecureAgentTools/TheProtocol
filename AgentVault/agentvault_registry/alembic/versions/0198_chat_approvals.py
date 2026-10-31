"""V0650 (l) (2026-10-31, agentvault2-14): approvals in the chat.

An agent asks in its organization's room for a human decision ("approve this before I act"), and the org's owner or a
named approver answers with one click, one by one or all at once. The record of each request and its decision lives in
its own table, `chat_approvals`, and not in the chat log: a room's disappearing timer hard-deletes messages, and the
decision with its proof (who decided, when, how, the registry's signed statement) must outlive the cards that show it.
`organization_members.can_approve` names the approvers; the column goes with the member row, so authority to approve
ends with the membership. Nothing here moves money or writes the ledger.

Downgrade drops the table and the column, and with them every approval record: dump `chat_approvals` first.

Revision ID: 0198_chat_approvals
Revises: 0197_moira_template_words
Create Date: 2026-10-31
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0198_chat_approvals"
down_revision: Union[str, None] = "0197_moira_template_words"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_approvals",
        sa.Column("id", sa.String(44), primary_key=True),
        sa.Column("conversation_id", sa.String(36),
                  sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("org_id", sa.String(), nullable=True),
        sa.Column("requester_agent_did", sa.String(255), nullable=False),
        sa.Column("client_ref", sa.String(64), nullable=False),
        sa.Column("request_message_id", sa.String(36), nullable=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("unlocks", sa.String(500), nullable=True),
        sa.Column("artifact_sha256", sa.String(64), nullable=True),
        sa.Column("artifact_label", sa.String(200), nullable=True),
        sa.Column("production_impact", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("facts", JSONB(), nullable=False),
        sa.Column("facts_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by_developer_id", sa.Integer(),
                  sa.ForeignKey("developers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decided_by_role", sa.String(16), nullable=True),
        sa.Column("decision_note", sa.String(500), nullable=True),
        sa.Column("decision_via", JSONB(), nullable=True),
        sa.Column("presence_method", sa.String(16), nullable=True),
        sa.Column("presence_challenge_id", sa.String(44), nullable=True),
        sa.Column("decision_statement", JSONB(), nullable=True),
        sa.UniqueConstraint("requester_agent_did", "client_ref", name="uq_chat_approval_client_ref"),
    )
    op.create_index("ix_chat_approvals_conversation_id", "chat_approvals", ["conversation_id"])
    op.create_index("ix_chat_approvals_pending", "chat_approvals", ["conversation_id", "created_at"],
                    postgresql_where=sa.text("status = 'pending'"))
    op.add_column("organization_members",
                  sa.Column("can_approve", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("organization_members", "can_approve")
    op.drop_index("ix_chat_approvals_pending", table_name="chat_approvals")
    op.drop_index("ix_chat_approvals_conversation_id", table_name="chat_approvals")
    op.drop_table("chat_approvals")
