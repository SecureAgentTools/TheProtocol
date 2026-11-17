"""V0662 (OurChat lane): editing and deleting a message within a window.

chat_messages already carries edited_at and deleted_at; no route wrote them. This adds the record the change leaves:
`chat_message_edits`, one row per change (an edit or a take-back) with the body as it stood BEFORE it, so the original is
kept for the record and the thread's members can read it. It goes with its message (ON DELETE CASCADE: a thread's timer
erases it with the message). Two partial indexes (ix_chat_msg_edited, ix_chat_msg_deleted) serve the sync feed's changes
lane, as ix_chat_msg_card_updated (0206) serves the card updates.

Additive; rolling back drops the table and the two indexes (a message then keeps its last text; the earlier bodies go).
The two-step rule applies as for every additive revision (downgrade first from an image that has it, then the older image).

Revision ID: 0215_chat_message_edits
Revises: 0214_chat_room_vocab
"""
from alembic import op
import sqlalchemy as sa

revision = "0215_chat_message_edits"
down_revision = "0214_chat_room_vocab"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_message_edits",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("message_id", sa.String(36), sa.ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("rev", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("body_before", sa.Text(), nullable=True),
        sa.Column("actor_ptype", sa.String(12), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("message_id", "rev", name="uq_chat_message_edit_rev"),
        sa.CheckConstraint("kind IN ('edit','delete')", name="ck_chat_message_edit_kind"),
    )
    op.create_index("ix_chat_message_edits_message", "chat_message_edits", ["message_id", "rev"])
    # the sync feed reads the messages edited or taken back since a cursor, as it reads the cards updated (0206)
    op.create_index("ix_chat_msg_edited", "chat_messages", ["conversation_id", "edited_at"],
                    postgresql_where=sa.text("edited_at IS NOT NULL"))
    op.create_index("ix_chat_msg_deleted", "chat_messages", ["conversation_id", "deleted_at"],
                    postgresql_where=sa.text("deleted_at IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("ix_chat_msg_deleted", table_name="chat_messages")
    op.drop_index("ix_chat_msg_edited", table_name="chat_messages")
    op.drop_index("ix_chat_message_edits_message", table_name="chat_message_edits")
    op.drop_table("chat_message_edits")
