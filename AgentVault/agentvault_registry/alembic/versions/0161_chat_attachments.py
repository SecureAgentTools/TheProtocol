"""§OURSTATE-5e — media: attachments as POINTERS, files on the durable volume.

A chat that accepts uploads is, mechanically, a file host bolted to a payment
network — so this table is built to make the boring questions answerable:
who uploaded it, into which thread, how big, what type, and what is its hash.

Design notes that are load-bearing rather than decorative:

  * **The bytes are NOT in the database.** They live under the registry's
    durable data volume (the same one §AGENTDISC gave every node for signing
    keys), keyed by SHA-256. Postgres holds the metadata and the pointer.
  * **`sha256` + `conversation_id` are UNIQUE together.** Sending the same file
    twice into one thread stores one copy and two cards. Across threads the
    file is stored again on purpose: a delete in one conversation must never
    reach into another.
  * **`deleted_at` is a tombstone, not a DELETE.** A message may be burned
    while the counterparty still holds the thread; the row survives so that
    "this was removed" can be rendered honestly instead of a broken card.

⚠ The card that references an attachment is a POINTER, exactly like
`contract.offer` and `guild.order`. The registry never inlines bytes into a
message body, so a thread read stays cheap no matter what people send.
"""
from alembic import op
import sqlalchemy as sa

revision = "0161_chat_attachments"
down_revision = "0160_contact_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_attachments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36), nullable=False),
        sa.Column("uploader_key", sa.String(255), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("mime", sa.String(120), nullable=False),
        sa.Column("bytes", sa.BigInteger, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_path", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_chat_attachments_conv", "chat_attachments", ["conversation_id"])
    op.create_index("ix_chat_attachments_uploader", "chat_attachments", ["uploader_key"])
    op.create_unique_constraint(
        "uq_chat_attachment_conv_sha", "chat_attachments", ["conversation_id", "sha256"])


def downgrade() -> None:
    op.drop_constraint("uq_chat_attachment_conv_sha", "chat_attachments", type_="unique")
    op.drop_index("ix_chat_attachments_uploader", table_name="chat_attachments")
    op.drop_index("ix_chat_attachments_conv", table_name="chat_attachments")
    op.drop_table("chat_attachments")
