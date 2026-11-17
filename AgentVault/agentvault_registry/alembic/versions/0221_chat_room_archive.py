"""V0663 (order gwo_daf7fc3c8b3174f6f73c0d8a): archive a room.

`conversations.archived_at` / `archived_by`: an archived room leaves the lists and no longer counts against its owner's cap of
20 rooms, its history stays and its members still read it; nobody posts in it until an operator unarchives it. NULL = an
ordinary room (every row that exists today).

Additive and nullable; rolling back drops the two columns (an archived room reads as an ordinary room again, and counts
against its owner's cap again). The two-step rule applies (downgrade first from an image that has it, then the older image).

Revision ID: 0221_chat_room_archive
Revises: 0220_agent_workflows
"""
from alembic import op
import sqlalchemy as sa

revision = "0221_chat_room_archive"
down_revision = "0220_agent_workflows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("conversations", sa.Column("archived_by", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("conversations", "archived_by")
    op.drop_column("conversations", "archived_at")
