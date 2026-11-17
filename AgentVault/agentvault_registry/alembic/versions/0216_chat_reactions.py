"""V0662 (OurChat lane): reactions to a message.

`chat_reactions`: one row per (message, principal, word), the word one of a closed list the code holds
(services/chat_reactions.py::VOCAB). No CHECK on the word: the list is the code's, and a new word must not need a
migration (the SQLite tests never meet a Postgres-only CHECK, V0659). It goes with its message (ON DELETE CASCADE).

Additive; rolling back drops the table (the messages stay, the ticks go). The two-step rule applies as for every additive
revision (downgrade first from an image that has it, then the older image).

Revision ID: 0216_chat_reactions
Revises: 0215_chat_message_edits
"""
from alembic import op
import sqlalchemy as sa

revision = "0216_chat_reactions"
down_revision = "0215_chat_message_edits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_reactions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("message_id", sa.String(36), sa.ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("word", sa.String(16), nullable=False),
        sa.Column("actor_ptype", sa.String(12), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("message_id", "actor_ptype", "actor_id", "word", name="uq_chat_reaction"),
    )
    op.create_index("ix_chat_reactions_conv_message", "chat_reactions", ["conversation_id", "message_id"])


def downgrade() -> None:
    op.drop_index("ix_chat_reactions_conv_message", table_name="chat_reactions")
    op.drop_table("chat_reactions")
