"""V0659 (f), session-tester 2026-11-08: the chat tables' CHECKs learn the room's words.

Found by (f)'s own federation legs on the sandbox (V0659, sbx-alpha): opening a room answered 409, "new row for relation
conversations violates check constraint ck_conversations_kind". 0155 created the chat CHECKs and 0164 widened the kinds
for support; 0213 added the room's column and its bans table but no word to either list, and the SQLite tests, which
build the tables from the models, never meet these Postgres-only constraints.

- ck_conversations_kind: + 'room' (a cross-frame room, services/chat_rooms.py).
- ck_conv_part_role: + 'moderator' (a room's operator below its owner, chat_rooms.OPERATOR_ROLES).

Downgrade: the narrower lists cannot hold a room or a moderator, so moderators become members and every room is deleted
with its messages, participants and bans (rooms exist only from V0659 on; take a backup first if any matter).

Revision ID: 0214_chat_room_vocab
Revises: 0213_chat_rooms
"""
from alembic import op

revision = "0214_chat_room_vocab"
down_revision = "0213_chat_rooms"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_conversations_kind", "conversations", type_="check")
    op.create_check_constraint(
        "ck_conversations_kind", "conversations",
        "kind IN ('dm','agent_service','org','system','group','support','room')")
    op.drop_constraint("ck_conv_part_role", "conversation_participants", type_="check")
    op.create_check_constraint(
        "ck_conv_part_role", "conversation_participants",
        "role IN ('owner','member','moderator')")


def downgrade() -> None:
    op.execute("UPDATE conversation_participants SET role = 'member' WHERE role = 'moderator'")
    op.execute("DELETE FROM chat_messages WHERE conversation_id IN (SELECT id FROM conversations WHERE kind = 'room')")
    op.execute("DELETE FROM conversations WHERE kind = 'room'")   # participants and bans go by ON DELETE CASCADE
    op.drop_constraint("ck_conv_part_role", "conversation_participants", type_="check")
    op.create_check_constraint("ck_conv_part_role", "conversation_participants", "role IN ('owner','member')")
    op.drop_constraint("ck_conversations_kind", "conversations", type_="check")
    op.create_check_constraint("ck_conversations_kind", "conversations", "kind IN ('dm','agent_service','org','system','group','support')")
