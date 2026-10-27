"""§OURSTATE-5a — priced first contact + the personal Genesis.

Spam control here is ECONOMIC, not editorial (strategy §6): a person may
declare what it costs a stranger to open a thread, and the price is paid on
the rails that already move money. Nothing in this migration is a wallet: the
price is a DECLARATION, the payment is an ordinary transfer, and
`chat_intro_payments` is a RECEIPT LEDGER whose only job is to stop one
payment from opening ten threads.

Three columns and one table:

  * `developers.contact_policy` — open | contacts | priced. Default 'open', so
    every existing account behaves exactly as it did yesterday.
  * `developers.contact_price` / `contact_currency` / `contact_purse_did` — the
    declaration. The purse is one of the person's OWN agents, because humans
    hold no balance on this network and a price payable to nobody is not a
    price.
  * `developers.genesis` — the personal terms card, same two-register shape as
    the room Genesis (`stated` by the person, enforced chips derived live from
    the columns above).

⚠ The price is stored WITH its currency and never without: a bare number is
the §FOREIGNACT defect waiting to happen on a network with three currencies.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0160_contact_policy"
down_revision = "0159_chat_remote_sender"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("developers", sa.Column(
        "contact_policy", sa.String(16), nullable=False, server_default="open"))
    op.add_column("developers", sa.Column(
        "contact_price", sa.Numeric(24, 8), nullable=True))
    op.add_column("developers", sa.Column(
        "contact_currency", sa.String(12), nullable=True))
    op.add_column("developers", sa.Column(
        "contact_purse_did", sa.String(255), nullable=True))
    op.add_column("developers", sa.Column(
        "genesis", postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    # varchar + CHECK, never a PG enum: adding a value to an enum in a
    # migration is a lock and a redeploy, and this vocabulary will grow.
    op.create_check_constraint(
        "ck_developers_contact_policy", "developers",
        "contact_policy IN ('open','contacts','priced')")

    # The receipt ledger. UNIQUE on the transaction ref is the whole
    # anti-replay mechanism: one settled transfer opens exactly one thread.
    op.create_table(
        "chat_intro_payments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tx_ref", sa.String(128), nullable=False),
        sa.Column("payer_key", sa.String(255), nullable=False),
        sa.Column("payee_developer_id", sa.Integer, nullable=False),
        sa.Column("purse_did", sa.String(255), nullable=False),
        sa.Column("amount", sa.Numeric(24, 8), nullable=False),
        sa.Column("currency", sa.String(12), nullable=False),
        sa.Column("conversation_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_unique_constraint(
        "uq_chat_intro_payment_tx", "chat_intro_payments", ["tx_ref"])
    op.create_index("ix_chat_intro_payments_payee", "chat_intro_payments",
                    ["payee_developer_id"])


def downgrade() -> None:
    op.drop_index("ix_chat_intro_payments_payee", table_name="chat_intro_payments")
    op.drop_constraint("uq_chat_intro_payment_tx", "chat_intro_payments", type_="unique")
    op.drop_table("chat_intro_payments")
    op.drop_constraint("ck_developers_contact_policy", "developers", type_="check")
    for col in ("genesis", "contact_purse_did", "contact_currency",
                "contact_price", "contact_policy"):
        op.drop_column("developers", col)
