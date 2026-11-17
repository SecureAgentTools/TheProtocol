"""V0663 (order gwo_9dce94d939aff2fa8ea4f91c): events across frames.

`chat_federation_outbox.event_id`: an outbox row either carries a MESSAGE (event_id NULL, one per conversation, seq and peer, as
before) or an EVENT about a message (an edit, a take-back, a reaction, a pin, an archive or close of a room): event_id set, its seq
the host's last seq when it was made, one per event and peer. The one unique key (conversation, seq, peer) would refuse a second
event of the same moment, so it becomes two partial unique indexes: the same key for message rows, and (event_id, peer) for events.

Additive; rolling back drops the column and puts the one constraint back (event rows are deleted first: they could not live under it).
The two-step rule applies (downgrade first from an image that has it, then the older image).

Revision ID: 0222_chat_fed_events
Revises: 0221_chat_room_archive
"""
from alembic import op
import sqlalchemy as sa

revision = "0222_chat_fed_events"
down_revision = "0221_chat_room_archive"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_federation_outbox", sa.Column("event_id", sa.String(36), nullable=True))
    op.drop_constraint("uq_chat_fed_outbox_target", "chat_federation_outbox", type_="unique")
    op.create_index("uq_chat_fed_outbox_message", "chat_federation_outbox", ["conversation_id", "seq", "peer_base_url"],
                    unique=True, postgresql_where=sa.text("event_id IS NULL"))
    op.create_index("uq_chat_fed_outbox_event", "chat_federation_outbox", ["event_id", "peer_base_url"],
                    unique=True, postgresql_where=sa.text("event_id IS NOT NULL"))


def downgrade() -> None:
    op.execute("DELETE FROM chat_federation_outbox WHERE event_id IS NOT NULL")
    op.drop_index("uq_chat_fed_outbox_event", table_name="chat_federation_outbox")
    op.drop_index("uq_chat_fed_outbox_message", table_name="chat_federation_outbox")
    op.create_unique_constraint("uq_chat_fed_outbox_target", "chat_federation_outbox",
                                ["conversation_id", "seq", "peer_base_url"])
    op.drop_column("chat_federation_outbox", "event_id")
