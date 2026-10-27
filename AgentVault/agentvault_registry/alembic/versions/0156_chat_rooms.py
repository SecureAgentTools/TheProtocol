"""CHAT ROOMS (2026-08-24, §OURSTATE-2) — org rooms, operators, and the Genesis.

The chat becomes the org's admin panel (strategy §7): ops commands map onto
the EXISTING org rails, and the only NEW state is room-scoped and money-free:

  * conversations.mode      — 'open' | 'announce' (announce = only org
                              owner/admin post; the org broadcast channel done
                              right). Plain varchar + CHECK, never a PG enum.
  * conversations.topic     — the /topic line.
  * conversations.genesis   — the Room Genesis/MOTD: a pinned, UN-BURNABLE
                              card (it is conversation state, not a message,
                              so burn-for-me structurally cannot hide it).
                              JSONB {stated, updated_by, updated_at, history[]}
                              — edits keep history (law 5: the reader can see
                              what the wall said before).
  * conversation_participants.can_post — the /mute flag. Room-scoped ONLY:
                              org membership truth stays in organization_members,
                              and org removal is the FE calling the REAL org
                              rail with an explicit named toggle — this schema
                              cannot express an org mutation by construction.

Δ-irrelevant: nothing here is money. Additive only.

Revision ID: 0156_chat_rooms
Revises: 0155_chat_core
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0156_chat_rooms"
down_revision = "0155_chat_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column(
        "mode", sa.String(12), nullable=False, server_default="open"))
    op.create_check_constraint(
        "ck_conversations_mode", "conversations", "mode IN ('open','announce')")
    op.add_column("conversations", sa.Column("topic", sa.String(200), nullable=True))
    op.add_column("conversations", sa.Column("genesis", JSONB, nullable=True))
    op.add_column("conversation_participants", sa.Column(
        "can_post", sa.Boolean, nullable=False, server_default=sa.true()))


def downgrade() -> None:
    op.drop_column("conversation_participants", "can_post")
    op.drop_column("conversations", "genesis")
    op.drop_column("conversations", "topic")
    op.drop_constraint("ck_conversations_mode", "conversations", type_="check")
    op.drop_column("conversations", "mode")
