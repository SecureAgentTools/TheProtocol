"""V0659 (f), session-tester 2026-11-07: cross-frame rooms (order gwo_a3d6a30d88482250e274765a; the design:
sessionlogs2026/DESIGN_2026-11-07_XFRAME_ROOMS.md, approved at room seq 2201).

`conversations.join_rule`: a room's (kind 'room') join rule, set by its owner: 'invited' (only an invite seats
someone), 'request' (anyone may ask, the owner or a moderator accepts) or 'anyone' (asking is joining). NULL on every
other kind.

`chat_room_bans`: who a room's host refuses for good (a removed outsider cannot rejoin under 'anyone'). Keyed by the
participant key the host knows a member by: a local principal's ("developer:<id>", "agent:<did>") or a remote one's
address (id@https://their.registry). Kept by the host only; a resident never moderates.

Additive; rolling back drops the table and the column (downgrade first from an image that has them, then the older
image).

Revision ID: 0213_chat_rooms
Revises: 0212_slash_moved_policy
"""
from alembic import op
import sqlalchemy as sa

revision = "0213_chat_rooms"
down_revision = "0212_slash_moved_policy"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("conversations", sa.Column("join_rule", sa.String(12), nullable=True))
    op.create_table(
        "chat_room_bans",
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("participant_key", sa.String(320), primary_key=True),
        sa.Column("banned_by", sa.String(320), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade():
    op.drop_table("chat_room_bans")
    op.drop_column("conversations", "join_rule")
