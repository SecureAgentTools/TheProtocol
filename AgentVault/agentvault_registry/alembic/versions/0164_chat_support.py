"""§OURSTATE-7 D — support becomes a thread.

The last item of the frozen OurState program. Until now a support ticket lived
in a parallel inbox: a developer filed one, an admin replied, and the reply
arrived as a notification pointing at a settings tab nobody opens. The
untargeted-broadcast half of that was fixed in §OURSTATE-2 (the reply notifies
the ticket OWNER and only them); this is the other half — the conversation
lands where conversations land.

Two changes, both small on purpose:

  * **`kind = 'support'`** joins the closed conversation vocabulary. It is its
    own kind rather than a `dm` with a special participant because its rules
    genuinely differ: it has no counterparty principal, a client may not write
    into it directly, and its authority lives on the support rail.

  * **`conversations.support_ticket_id`** is a real COLUMN, not a prefix parsed
    back out of `dm_pair_key`. The pair key still carries `support|{id}` because
    that is what makes the thread unique per ticket (the same trick org rooms
    use), but a thing this code has to read on every message is a column.

⚠ NO BACKFILL, deliberately, and the Commander's own words are the reason:
*"we dont have any active real support tickets so no migration needed"*. Every
existing ticket keeps working through the support rail exactly as before; the
first message written after this deploy opens its thread. A backfill that
invented conversations for dead tickets would fill the list with archaeology.

⚠ The support desk is NOT a participant. Admin replies are written by the RAIL
(`sender_ptype = 'system'`), which the message table has always allowed — so
this needs no participant-table change, and an admin never silently becomes a
member of a thread by answering it.
"""
from alembic import op
import sqlalchemy as sa

revision = "0164_chat_support"
down_revision = "0163_chat_retention"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column(
        "support_ticket_id", sa.Integer, nullable=True))
    # The lookup is always "the thread for THIS ticket" — a partial index over
    # the handful of support rows, not the whole conversation table.
    op.create_index("ix_conversations_support_ticket", "conversations",
                    ["support_ticket_id"],
                    postgresql_where=sa.text("support_ticket_id IS NOT NULL"))

    # Widen the kind vocabulary. Drop-and-recreate is the only way to edit a
    # CHECK; the window is one transaction.
    op.drop_constraint("ck_conversations_kind", "conversations", type_="check")
    op.create_check_constraint(
        "ck_conversations_kind", "conversations",
        "kind IN ('dm','agent_service','org','system','group','support')")


def downgrade() -> None:
    # Going back means the widened vocabulary is gone, so any support thread
    # would violate the narrower CHECK. Delete them — they are a MIRROR; the
    # tickets and their messages live on `support_tickets` / `support_messages`
    # and are untouched by this, which is exactly why the mirror is safe to drop.
    op.execute("DELETE FROM chat_messages WHERE conversation_id IN "
               "(SELECT id FROM conversations WHERE kind = 'support')")
    op.execute("DELETE FROM conversation_participants WHERE conversation_id IN "
               "(SELECT id FROM conversations WHERE kind = 'support')")
    op.execute("DELETE FROM conversations WHERE kind = 'support'")
    op.drop_constraint("ck_conversations_kind", "conversations", type_="check")
    op.create_check_constraint(
        "ck_conversations_kind", "conversations",
        "kind IN ('dm','agent_service','org','system','group')")
    op.drop_index("ix_conversations_support_ticket", table_name="conversations")
    op.drop_column("conversations", "support_ticket_id")
