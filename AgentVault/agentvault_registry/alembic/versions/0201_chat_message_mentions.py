"""V0650 (h) (2026-10-31) — a chat message stores the principals it @mentions.

Order gwo_2c71fdfcbc1b74d55549ed8d. ONE nullable column and ONE partial index on `chat_messages`, nothing else touched:
`mentions` (JSONB), the list services/chat_mentions.py resolves at insert ([{key, ptype, developer_id, agent_did,
token}], NULL when the body names nobody), and `ix_chat_msg_mentioned` on (conversation_id, seq) WHERE mentions IS NOT
NULL, which serves GET /api/v1/chat/conversations/{id}/messages?mentions=me (one thread, newest first, only the rows
that name someone). No backfill: a message posted before this migration names nobody.

The index is built in the migration's transaction (chat_messages is small on every node today; the build holds a SHARE
lock, so sends wait for it). Rolling back past this is the two-step rule (downgrade first from an image that has it,
then the older image); dropping the column drops the stored mentions.

Revision ID: 0201_chat_message_mentions
Revises: 0200_guild_intended_worker
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0201_chat_message_mentions"
down_revision = "0200_guild_intended_worker"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_messages", sa.Column("mentions", postgresql.JSONB(), nullable=True))
    op.create_index("ix_chat_msg_mentioned", "chat_messages", ["conversation_id", "seq"],
                    postgresql_where=sa.text("mentions IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("ix_chat_msg_mentioned", table_name="chat_messages")
    op.drop_column("chat_messages", "mentions")
