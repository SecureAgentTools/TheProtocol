"""V0652 (ak) (2026-11-01, agentvault2-14): a mute that ends by itself.

Order gwo_8c69cc0fd1f3033a35f47969 (the chat's settings, session-lead's review seq 397, defect 12 of the inventory: mute
had no duration). ONE nullable column on `conversation_participants`: `muted_until`, when a mute set for a while ends
(an hour, 8 hours, a day). NULL keeps today's meaning: a mute holds until it is lifted. A mute whose time has passed
reads as no mute for the unread count and for the notices; nothing rewrites the row. No backfill: every existing mute
stays a mute until lifted.

Rolling back drops it (a timed mute then holds until lifted); the two-step rule applies as for every additive revision
(downgrade first from an image that has it, then the older image).

Revision ID: 0205_chat_mute_until
Revises: 0204_chat_approval_choices
"""
from alembic import op
import sqlalchemy as sa

revision = "0205_chat_mute_until"
down_revision = "0204_chat_approval_choices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversation_participants",
                  sa.Column("muted_until", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("conversation_participants", "muted_until")
