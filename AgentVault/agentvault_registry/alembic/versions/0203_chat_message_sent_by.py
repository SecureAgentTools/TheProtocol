"""V0652 (aj) (2026-10-31, agentvault2-14): a message an agent's owner sent as the agent says so.

Order gwo_9fa441b938ff31f95662243f, item (4): "a message sent as an agent by its owner says so in the thread (sent by its
owner)". ONE nullable column on `chat_messages`, nothing else touched: `sent_by_developer_id`, the developer whose own
session minted the agent token the message was posted with (an owner session token, `via: "owner"`, which the registry
verified against the owner's live session before the message was written). A message an agent posts with its own
credential leaves it NULL: the registry cannot tell who typed it, so it claims nothing. No backfill: no message carried
the fact before this revision.

Rolling back drops the column (the marker then reads absent on every message); the two-step rule applies as for every
additive revision (downgrade first from an image that has it, then the older image).

Revision ID: 0203_chat_message_sent_by
Revises: 0202_chat_approval_consumed
"""
from alembic import op
import sqlalchemy as sa

revision = "0203_chat_message_sent_by"
down_revision = "0202_chat_approval_consumed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_messages", sa.Column("sent_by_developer_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("chat_messages", "sent_by_developer_id")
