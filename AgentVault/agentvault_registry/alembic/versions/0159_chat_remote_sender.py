"""CHAT REMOTE SENDER (2026-08-24, §OURSTATE-3b) — widen the message CHECK.

0158 widened `conversation_participants.ptype` to include 'remote' and MISSED
its sibling: `chat_messages.sender_ptype` still named only developer/agent/
system. The battery found it the way this class is always found — the mirror
was created, every delivery answered 200, and not one message could be stored,
because the insert violated a constraint on a different table.

It gets its own revision rather than an edit to 0158 because 0158 is already
applied on the canary: an applied migration is history, and history that
changes under a running database is how a fleet ends up with two different
schemas both claiming the same version.

Δ-irrelevant. Additive in effect: the constraint only widens.

Revision ID: 0159_chat_remote_sender
Revises: 0158_chat_federation
"""
from alembic import op

revision = "0159_chat_remote_sender"
down_revision = "0158_chat_federation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_chat_msg_sender_ptype", "chat_messages", type_="check")
    op.create_check_constraint(
        "ck_chat_msg_sender_ptype", "chat_messages",
        "sender_ptype IN ('developer','agent','system','remote')")


def downgrade() -> None:
    op.drop_constraint("ck_chat_msg_sender_ptype", "chat_messages", type_="check")
    op.create_check_constraint(
        "ck_chat_msg_sender_ptype", "chat_messages",
        "sender_ptype IN ('developer','agent','system')")
