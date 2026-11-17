"""V0662 (OurChat lane): pinned messages.

`chat_pins`: one row per (thread, message) the thread's operators or members pinned (who may: services/chat_pins.py), with
who pinned it and when. It goes with its message and its thread (ON DELETE CASCADE); a message taken back loses its pin in
the service.

Additive; rolling back drops the table (the messages stay, the pins go). The two-step rule applies as for every additive
revision (downgrade first from an image that has it, then the older image).

Revision ID: 0217_chat_pins
Revises: 0216_chat_reactions
"""
from alembic import op
import sqlalchemy as sa

revision = "0217_chat_pins"
down_revision = "0216_chat_reactions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_pins",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("message_id", sa.String(36), sa.ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pinned_by_ptype", sa.String(12), nullable=False),
        sa.Column("pinned_by_id", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("conversation_id", "message_id", name="uq_chat_pin"),
    )
    op.create_index("ix_chat_pins_conversation", "chat_pins", ["conversation_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_chat_pins_conversation", table_name="chat_pins")
    op.drop_table("chat_pins")
