"""V0662 (OurChat lane): agent status in a room (the session board).

`chat_agent_status`: one row per (organization's room, member) that the room's desk last reported: state (active, paused,
unreachable), wake mode, last wake and wakes in the last 24 hours, and when it was reported. The registry never guesses: a row
older than five minutes reads "unknown" (services/chat_agent_status.py). Written by the organization's owner or admin, or an
agent of such an owner (the desk reports every 60 s); read by the same people only. It goes with its room (ON DELETE CASCADE).

Additive; rolling back drops the table (the board reads empty). The two-step rule applies as for every additive revision
(downgrade first from an image that has it, then the older image).

Revision ID: 0219_chat_agent_status
Revises: 0218_chat_guest_seat
"""
from alembic import op
import sqlalchemy as sa

revision = "0219_chat_agent_status"
down_revision = "0218_chat_guest_seat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_agent_status",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("member_key", sa.String(320), nullable=False),
        sa.Column("name", sa.String(120), nullable=True),
        sa.Column("state", sa.String(12), nullable=False),
        sa.Column("wake_mode", sa.String(8), nullable=True),
        sa.Column("last_wake_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("wakes_24h", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reported_by", sa.String(255), nullable=True),
        sa.UniqueConstraint("conversation_id", "member_key", name="uq_chat_agent_status"),
    )


def downgrade() -> None:
    op.drop_table("chat_agent_status")
