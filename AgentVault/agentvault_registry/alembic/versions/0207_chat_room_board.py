"""V0652 (ac) (2026-11-01, agentvault2-14): a pinned status board per room.

Order gwo_2ae43c7789db1e808ea1417f. One board per organization's room, kept fresh by the room's owner or the members the
owner names (the current release, the open orders, what waits on the owner), pinned above the history beside the
approvals, its every edit kept. Conversation state, like the room's rules (its genesis): a thread's timer and a burn do
not touch it.

- `conversations.board`: {text, rev, updated_at, updated_by: {ptype, id}}, NULL until the first edit.
- `conversations.board_editors`: the principal keys the owner named (dev:<id>, agt:<did>), NULL for none.
- `chat_board_revisions`: one row per edit (who, when, the text after it), the board's history; it goes with its room.

Additive; rolling back drops them (the board's text and history go). The two-step rule applies as for every additive
revision (downgrade first from an image that has it, then the older image).

Revision ID: 0207_chat_room_board
Revises: 0206_chat_live_cards
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0207_chat_room_board"
down_revision = "0206_chat_live_cards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("board", postgresql.JSONB(), nullable=True))
    op.add_column("conversations", sa.Column("board_editors", postgresql.JSONB(), nullable=True))
    op.create_table(
        "chat_board_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("rev", sa.Integer(), nullable=False),
        sa.Column("actor_ptype", sa.String(12), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("conversation_id", "rev", name="uq_chat_board_rev"),
    )


def downgrade() -> None:
    op.drop_table("chat_board_revisions")
    op.drop_column("conversations", "board_editors")
    op.drop_column("conversations", "board")
