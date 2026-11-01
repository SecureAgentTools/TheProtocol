"""V0652 (aa) (2026-11-01, agentvault2-14): cards that live.

Order gwo_840aa2b590306f7eba147758. A card its author (or the rail that posted it) updates in place, with every update
recorded. Three things:

- `chat_messages.card_rev` (0 until the first update) and `chat_messages.card_updated_at` (NULL until then): the card
  a message carries is its latest state; the sync feed returns the messages whose card moved since a cursor, read by
  `ix_chat_msg_card_updated`.
- `chat_card_updates`: one row per update (who, when, the card after it, what changed), the history a member reads.
  It goes with its message (ON DELETE CASCADE), so a thread's timer erases a card's history with the card.
- `guild_work_orders.announce_conversation_id` / `announce_message_id`: the room an order's poster named, and the
  card the Guild rail posted there and keeps current. The room may go (SET NULL); the card's message has no foreign
  key, so a timer that erased the card only ends the updates.

Additive; rolling back drops them (cards then stay as they last read; the history goes). The two-step rule applies as
for every additive revision (downgrade first from an image that has it, then the older image).

Revision ID: 0206_chat_live_cards
Revises: 0205_chat_mute_until
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0206_chat_live_cards"
down_revision = "0205_chat_mute_until"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_messages", sa.Column("card_rev", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("chat_messages", sa.Column("card_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_chat_msg_card_updated", "chat_messages", ["conversation_id", "card_updated_at"],
                    postgresql_where=sa.text("card_updated_at IS NOT NULL"))
    op.create_table(
        "chat_card_updates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("message_id", sa.String(36), sa.ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("rev", sa.Integer(), nullable=False),
        sa.Column("actor_ptype", sa.String(12), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("card", postgresql.JSONB(), nullable=False),
        sa.Column("changes", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("message_id", "rev", name="uq_chat_card_update_rev"),
    )
    op.add_column("guild_work_orders", sa.Column(
        "announce_conversation_id", sa.String(36), sa.ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True))
    op.add_column("guild_work_orders", sa.Column("announce_message_id", sa.String(36), nullable=True))


def downgrade() -> None:
    op.drop_column("guild_work_orders", "announce_message_id")
    op.drop_column("guild_work_orders", "announce_conversation_id")
    op.drop_table("chat_card_updates")
    op.drop_index("ix_chat_msg_card_updated", table_name="chat_messages")
    op.drop_column("chat_messages", "card_updated_at")
    op.drop_column("chat_messages", "card_rev")
