"""V0653 (w) (2026-11-02, agentvault2-14): each chat message records the credential it was sent with.

Order gwo_213e530b4ca2de3130c4a1d1 (session-lead, the sessions' room seq 880). From V0653 a developer key posts in the
chat (an MCP connector's, the personal bridge's), so a line from a developer no longer proves his own hand: a prompt
injected into what a connector reads could post a line that reads exactly like his typed word. The message now keeps
how it was sent, from the same facts the approval's `via` takes, and the read returns it (`sent_with`).

- `chat_messages.sent_with`: "session" (a signed-in developer), "api_key" (a developer key) or "agent" (an agent JWT);
  NULL for a message from before this revision, or one the registry wrote with no caller.

Additive; rolling back drops the column (the record of how each line was sent goes). The two-step rule applies as for
every additive revision (downgrade first from an image that has it, then the older image).

Revision ID: 0208_chat_message_sent_with
Revises: 0207_chat_room_board
"""
from alembic import op
import sqlalchemy as sa

revision = "0208_chat_message_sent_with"
down_revision = "0207_chat_room_board"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_messages", sa.Column("sent_with", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("chat_messages", "sent_with")
