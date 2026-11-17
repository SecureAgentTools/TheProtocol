"""V0662 (OurChat lane): a guest seat in an organization's room.

`conversation_participants.guest_seat` (false unless an owner or admin of the organization seated a named principal as a guest
of that one room; services/chat_guests.py), with who seated them and when. A flag beside the role, not a new role: the live
organization table still decides a member's role on every touch (§ORGLEAK), and the flag only decides whether a seat remains
when there is no membership. No CHECK to widen (the role column keeps its values), no backfill (every existing row is false).

Additive; rolling back drops the three columns (a guest then has no seat: the room refuses them as any non-member). The
two-step rule applies as for every additive revision (downgrade first from an image that has it, then the older image).

Revision ID: 0218_chat_guest_seat
Revises: 0217_chat_pins
"""
from alembic import op
import sqlalchemy as sa

revision = "0218_chat_guest_seat"
down_revision = "0217_chat_pins"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversation_participants", sa.Column("guest_seat", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("conversation_participants", sa.Column("guest_invited_by", sa.String(255), nullable=True))
    op.add_column("conversation_participants", sa.Column("guest_invited_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("conversation_participants", "guest_invited_at")
    op.drop_column("conversation_participants", "guest_invited_by")
    op.drop_column("conversation_participants", "guest_seat")
