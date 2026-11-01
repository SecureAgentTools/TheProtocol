"""V0651 (o) (2026-10-31, agentvault2-14): one approval opens one act.

Order gwo_b81bd6234ac6d6b30b1f9759. FOUR nullable columns on `chat_approvals`, nothing else touched: `consumed_at`,
`consumed_by_agent_did`, `consumed_act` (the act's label) and `consumed_act_sha256` (the sha256 the act named, which must
equal the approval's artifact_sha256). POST /api/v1/chat/approvals/{id}/consume writes them once, in one UPDATE that
also requires consumed_at IS NULL, so a second use (or a race between two) is refused. No backfill: no approval was used
before this revision.

Rolling back drops the use records (an approval then reads as never used); the two-step rule applies as for every
additive revision (downgrade first from an image that has it, then the older image).

Revision ID: 0202_chat_approval_consumed
Revises: 0201_chat_message_mentions
"""
from alembic import op
import sqlalchemy as sa

revision = "0202_chat_approval_consumed"
down_revision = "0201_chat_message_mentions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_approvals", sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("chat_approvals", sa.Column("consumed_by_agent_did", sa.String(255), nullable=True))
    op.add_column("chat_approvals", sa.Column("consumed_act", sa.String(200), nullable=True))
    op.add_column("chat_approvals", sa.Column("consumed_act_sha256", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("chat_approvals", "consumed_act_sha256")
    op.drop_column("chat_approvals", "consumed_act")
    op.drop_column("chat_approvals", "consumed_by_agent_did")
    op.drop_column("chat_approvals", "consumed_at")
