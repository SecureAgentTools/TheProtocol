"""CHAT CORE (2026-08-24, §OURSTATE-1) — the first conversation primitive this platform has ever had.

The 2026-08-24 census (four parallel scouts over 154 migrations / ~130 routers)
found NO conversation, DM or thread primitive anywhere: only support tickets,
one-way notifications and admin broadcasts. OurState — the chat-native layer the
Commander approved in full — needs exactly four tables, and law 1 of the program
("chat has NO money code") means none of them carries a money column: every
economic act in a thread is a typed CARD that doors into an EXISTING rail and a
ledger ref the client re-verifies. Δ-irrelevant by construction.

Shapes (STRATEGY_2026-08-24_OURSTATE_CHAT_SUPERAPP.md §9, frozen):
  * conversations         — kind CHECK (plain varchar, NOT a PG enum: the
                            UPPERCASE-enum trap), per-thread `last_seq` counter
                            (seq is assigned by an atomic UPDATE..RETURNING, so
                            ordering is total per thread by construction),
                            `dm_pair_key` UNIQUE = the one-thread-per-pair dedup,
                            nullable federation placeholders (host_registry /
                            remote_ref) that OURSTATE-3 will use and CORE ignores.
                            `service_inflight_at` is the one-in-flight-service-call
                            flag the plan asked for "on the conversation row" — a
                            timestamp rather than a bool so a crashed worker's
                            stale flag ages out instead of bricking the thread.
  * conversation_participants — typed principals (developer|agent), exactly one
                            id set (CHECK), request-folder state machine
                            (active|pending|left), monotonic `last_read_seq`
                            (unread = last_seq - last_read_seq, never a counter
                            column), `hidden_before_seq` = Burn-for-me.
  * chat_messages         — UNIQUE(conversation_id, seq) is the order;
                            UNIQUE(conversation, sender, client_ref) is the
                            retry/offline-queue idempotency. body cap (4KB) and
                            card cap (8KB) are enforced in code — a DB CHECK on
                            byte length of TEXT is a false comfort across
                            encodings. NOTE: the plan lists an extra
                            INDEX(conversation_id, seq DESC); the UNIQUE
                            constraint's index already serves backward scans in
                            Postgres, so the duplicate is deliberately NOT
                            created (dead write weight, zero read gain).
  * chat_blocks           — user-level block primitive (the census found none
                            exists anywhere): composite pk over the typed pair,
                            enforced at conversation-create AND message-send,
                            both directions, silently.

Additive only. The downgrade is written but the house rule stands: never run it
on a node whose head has moved past this revision.

Revision ID: 0155_chat_core
Revises: 0154_stepup_challenges
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0155_chat_core"
down_revision = "0154_stepup_challenges"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("title", sa.String(160), nullable=True),
        sa.Column("org_id", sa.String, sa.ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by_ptype", sa.String(12), nullable=False),
        sa.Column("created_by_id", sa.String(255), nullable=False),
        sa.Column("last_seq", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_preview", sa.String(160), nullable=True),
        # Canonical unordered pair key ("dm|a|b" / "svc|a|b") — the dedup that makes
        # a second thread to the same counterparty land in the FIRST thread. NULL for
        # kinds that are not pair-shaped (org/system/group).
        sa.Column("dm_pair_key", sa.String(600), nullable=True, unique=True),
        # One service call in flight per thread; a stale timestamp ages out in code.
        sa.Column("service_inflight_at", sa.DateTime(timezone=True), nullable=True),
        # OURSTATE-3 federation placeholders — unused in CORE, deliberately nullable.
        sa.Column("host_registry", sa.String(255), nullable=True),
        sa.Column("remote_ref", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('dm','agent_service','org','system','group')",
            name="ck_conversations_kind",
        ),
    )
    op.create_index("ix_conversations_last_message_at", "conversations", ["last_message_at"])

    op.create_table(
        "conversation_participants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36),
                  sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ptype", sa.String(12), nullable=False),
        sa.Column("developer_id", sa.Integer,
                  sa.ForeignKey("developers.id", ondelete="CASCADE"), nullable=True),
        sa.Column("agent_did", sa.String(255), nullable=True),
        sa.Column("role", sa.String(12), nullable=False, server_default="member"),
        sa.Column("state", sa.String(12), nullable=False, server_default="active"),
        sa.Column("last_read_seq", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("hidden_before_seq", sa.BigInteger, nullable=True),
        sa.Column("muted", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("ptype IN ('developer','agent')", name="ck_conv_part_ptype"),
        sa.CheckConstraint("state IN ('active','pending','left')", name="ck_conv_part_state"),
        sa.CheckConstraint("role IN ('owner','member')", name="ck_conv_part_role"),
        # Exactly one principal id set, matching ptype.
        sa.CheckConstraint(
            "(ptype = 'developer' AND developer_id IS NOT NULL AND agent_did IS NULL) OR "
            "(ptype = 'agent' AND agent_did IS NOT NULL AND developer_id IS NULL)",
            name="ck_conv_part_exactly_one",
        ),
        sa.UniqueConstraint("conversation_id", "ptype", "developer_id", "agent_did",
                            name="uq_conv_part_principal"),
    )
    # Inbox queries scan by principal; partial indexes keep them tight.
    op.create_index("ix_conv_part_developer", "conversation_participants", ["developer_id"],
                    postgresql_where=sa.text("developer_id IS NOT NULL"))
    op.create_index("ix_conv_part_agent", "conversation_participants", ["agent_did"],
                    postgresql_where=sa.text("agent_did IS NOT NULL"))
    op.create_index("ix_conv_part_conversation", "conversation_participants", ["conversation_id"])

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36),
                  sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.BigInteger, nullable=False),
        sa.Column("sender_ptype", sa.String(12), nullable=False),
        sa.Column("sender_id", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("body", sa.Text, nullable=True),
        sa.Column("card", JSONB, nullable=True),
        sa.Column("reply_to", sa.String(36), nullable=True),
        sa.Column("client_ref", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('text','card','system')", name="ck_chat_msg_kind"),
        sa.CheckConstraint("sender_ptype IN ('developer','agent','system')", name="ck_chat_msg_sender_ptype"),
        sa.UniqueConstraint("conversation_id", "seq", name="uq_chat_msg_conv_seq"),
        sa.UniqueConstraint("conversation_id", "sender_ptype", "sender_id", "client_ref",
                            name="uq_chat_msg_client_ref"),
    )

    op.create_table(
        "chat_blocks",
        sa.Column("blocker_ptype", sa.String(12), primary_key=True),
        sa.Column("blocker_id", sa.String(255), primary_key=True),
        sa.Column("blocked_ptype", sa.String(12), primary_key=True),
        sa.Column("blocked_id", sa.String(255), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("chat_blocks")
    op.drop_table("chat_messages")
    op.drop_index("ix_conv_part_conversation", table_name="conversation_participants")
    op.drop_index("ix_conv_part_agent", table_name="conversation_participants")
    op.drop_index("ix_conv_part_developer", table_name="conversation_participants")
    op.drop_table("conversation_participants")
    op.drop_index("ix_conversations_last_message_at", table_name="conversations")
    op.drop_table("conversations")
