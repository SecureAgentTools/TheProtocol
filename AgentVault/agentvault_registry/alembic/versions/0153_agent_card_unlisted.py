"""UNLISTED AGENTS (2026-08-23, §DISCREFINE) — a developer can keep an agent out of discovery.

Commander's ask: "we need an option to make agents private not listen in discovery
for devs. admins can discover them but they must be visually marked to be invisible
for others. I was thinking about the treasuries etc."

The flag lives on `agent_cards` rather than `agents` because every surface that has
to honour it reads THIS table: the discovery search, the legacy list endpoint, and
the federation export that ships cards to peers. Putting it on the identity row
would leave the export consulting a table it does not join.

UNLISTED IS NOT ACCESS CONTROL. It removes the card from browse, search, facets and
federation export. A direct DID lookup still resolves, because agent cards are how
one agent learns to talk to another and a hidden card would break the A2A handshake
for a counterparty that was legitimately handed the DID. The UI says so in those words.

⚠ Pulls cannot REMOVE: a card already mirrored at a peer stays there until that peer
drops it. Hiding stops the spread, it does not retract what already travelled. A
retraction tombstone would be its own change to the federation protocol.

Additive, defaulted FALSE, so every existing row keeps today's behaviour exactly.
Δ-irrelevant: no money column, nothing the supply audit reads.

Revision ID: 0153_agent_card_unlisted
Revises: 0152_developer_prefs
"""
from alembic import op
import sqlalchemy as sa

revision = "0153_agent_card_unlisted"
down_revision = "0152_developer_prefs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_cards",
        sa.Column(
            "unlisted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment="Hidden from discovery/search/facets and never exported to peers. "
                    "Owner-set; admins still see it, marked. Not access control: a "
                    "direct DID lookup still resolves.",
        ),
    )
    # PARTIAL on purpose: almost every row is FALSE, so an index over the whole
    # column would buy the common "not unlisted" scan nothing. The queries that
    # actually need an index are the admin/owner ones asking "which are hidden".
    op.create_index(
        "ix_agent_cards_unlisted",
        "agent_cards",
        ["unlisted"],
        postgresql_where=sa.text("unlisted"),
    )


def downgrade() -> None:
    op.drop_index("ix_agent_cards_unlisted", table_name="agent_cards")
    op.drop_column("agent_cards", "unlisted")
