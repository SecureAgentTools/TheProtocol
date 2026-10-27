"""CHAT FEDERATION (2026-08-24, §OURSTATE-3b) — host + per-registry inbox relay.

The approved model (strategy §10, D8): the creator's registry HOSTS a thread and
owns its `seq`; it delivers each message to every remote participant's HOME
registry over the peer channel; residents read and get realtime from their OWN
registry. A host outage therefore degrades to "cannot send", never to "cannot
read history" — the property that makes this worth the machinery.

Three additions, all additive:

  * `chat_federation_outbox` — the host's delivery queue. UNIQUE on
    (conversation, seq, peer) so a retry can never double-deliver, and the
    receiving side is idempotent too (see below): at-least-once on the wire,
    exactly-once in the log.
  * `conversation_participants.remote_key` + the widened `ptype` — a remote
    principal is `handle@https://their.registry`, an address this registry
    does not own and must not pretend to. It is deliberately NOT a foreign
    key: the row records who the HOST said is in the thread, and only their
    home registry can vouch for them.
  * `chat_messages.remote_seq` + `origin_registry` — on a MIRROR, the host's
    seq is the truth and the local seq is just this database's ordering.
    UNIQUE (conversation, remote_seq) is the idempotent receive: the same
    host message delivered twice lands once.

`conversations.host_registry` / `remote_ref` already exist (0155 placeholders,
written for exactly this). host_registry NULL = we host it; set = we mirror it.

Δ-irrelevant: no money columns. Nothing here can move value — a federated
thread carries the same closed card vocabulary, and every card is still a door
to a rail that does its own authorization at the registry that owns the money.

Revision ID: 0158_chat_federation
Revises: 0157_developer_handles
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0158_chat_federation"
down_revision = "0157_developer_handles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── the host's outbox ────────────────────────────────────────────────────
    op.create_table(
        "chat_federation_outbox",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36), nullable=False, index=True),
        sa.Column("seq", sa.BigInteger, nullable=False),
        sa.Column("peer_base_url", sa.String(500), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("conversation_id", "seq", "peer_base_url",
                            name="uq_chat_fed_outbox_target"),
    )
    # The worker's only query: what is due and undelivered.
    op.create_index("ix_chat_fed_outbox_due", "chat_federation_outbox",
                    ["delivered_at", "next_attempt_at"])

    # ── remote participants ──────────────────────────────────────────────────
    op.add_column("conversation_participants",
                  sa.Column("remote_key", sa.String(320), nullable=True))
    # ptype gains 'remote'. The 0155 CHECK named exactly two values; widen it
    # rather than dropping the constraint — an unconstrained ptype is how a
    # typo becomes a participant nobody can address.
    # TWO constraints from 0155 name the pair: the ptype enum and the
    # exactly-one-principal rule. Both must widen together, or the second
    # silently forbids what the first now allows.
    op.drop_constraint("ck_conv_part_ptype", "conversation_participants", type_="check")
    op.create_check_constraint(
        "ck_conv_part_ptype", "conversation_participants",
        "ptype IN ('developer','agent','remote')")
    op.drop_constraint("ck_conv_part_exactly_one", "conversation_participants", type_="check")
    op.create_check_constraint(
        "ck_conv_part_exactly_one", "conversation_participants",
        "(ptype = 'developer' AND developer_id IS NOT NULL AND agent_did IS NULL AND remote_key IS NULL) "
        "OR (ptype = 'agent' AND agent_did IS NOT NULL AND developer_id IS NULL AND remote_key IS NULL) "
        "OR (ptype = 'remote' AND remote_key IS NOT NULL AND developer_id IS NULL AND agent_did IS NULL)",
    )

    # ── mirrored messages ────────────────────────────────────────────────────
    op.add_column("chat_messages", sa.Column("remote_seq", sa.BigInteger, nullable=True))
    op.add_column("chat_messages", sa.Column("origin_registry", sa.String(500), nullable=True))
    op.create_index("uq_chat_messages_remote_seq", "chat_messages",
                    ["conversation_id", "remote_seq"], unique=True,
                    postgresql_where=sa.text("remote_seq IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("uq_chat_messages_remote_seq", table_name="chat_messages")
    op.drop_column("chat_messages", "origin_registry")
    op.drop_column("chat_messages", "remote_seq")
    op.drop_constraint("ck_conv_part_exactly_one", "conversation_participants", type_="check")
    op.create_check_constraint(
        "ck_conv_part_exactly_one", "conversation_participants",
        "(ptype = 'developer' AND developer_id IS NOT NULL AND agent_did IS NULL) "
        "OR (ptype = 'agent' AND agent_did IS NOT NULL AND developer_id IS NULL)",
    )
    op.drop_constraint("ck_conv_part_ptype", "conversation_participants", type_="check")
    op.create_check_constraint(
        "ck_conv_part_ptype", "conversation_participants",
        "ptype IN ('developer','agent')")
    op.drop_column("conversation_participants", "remote_key")
    op.drop_index("ix_chat_fed_outbox_due", table_name="chat_federation_outbox")
    op.drop_table("chat_federation_outbox")
