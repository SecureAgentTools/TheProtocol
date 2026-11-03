"""V0654 (aq) (2026-11-02, agentvault2-14): each member of a conversation keeps a wake mode.

Order gwo_238870d0f3c281c7d870554d (his word in the sessions' room, seq 1091: "I approve ... the planned and approved
modes for chat"; the design: sessionlogs2026/DESIGN_2026-11-02_SESSION_WAKE_MODES.md, step 2). A session wakes in a room
only when it is needed:

- `conversation_participants.wake_mode`: "listen" (every line meant for the member, as before), "on-call" (only a line
  that @-names it, a direct message, a decision on its own approval card, or the room owner's @all) or "off" (nothing).
  The sync feed's for=me and the live delivery read it. Every row starts "listen", so nothing changes until a mode is set.

Additive; rolling back drops the column (every member listens again). The two-step rule applies as for every additive
revision (downgrade first from an image that has it, then the older image).

Revision ID: 0209_chat_participant_wake_mode
Revises: 0208_chat_message_sent_with
"""
from alembic import op
import sqlalchemy as sa

revision = "0209_chat_participant_wake_mode"
down_revision = "0208_chat_message_sent_with"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversation_participants",
                  sa.Column("wake_mode", sa.String(8), nullable=False, server_default="listen"))


def downgrade() -> None:
    op.drop_column("conversation_participants", "wake_mode")
