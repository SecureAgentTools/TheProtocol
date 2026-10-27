"""§CHATDESK C4 — support review with consent.

A support agent may read a customer conversation ONLY while a live, visible,
ticket-bound grant exists. This table is that grant. The rules it encodes:

  * **Consent is explicit and scoped.** One row = one ticket x one
    conversation, created by the ticket's FILER (for org rooms: by an org
    owner/admin — the room belongs to the organization). Read-only by
    construction: there is no write path for the desk, because the desk never
    becomes a participant (the §OURSTATE-7 rule, unchanged).

  * **The grant dies with the relationship** (the §ORGLIFE law, applied on day
    one): when the ticket closes or resolves, every grant on it is revoked —
    and the READ SIDE validates the ticket status LIVE anyway, so even a
    missed revocation write cannot keep a closed ticket readable. Fail closed,
    both halves.

  * **Revoke, never delete.** revoked_at/revoked_reason stay as the audit
    trail; a re-grant after revocation is a NEW row. Every desk read of a
    granted transcript additionally lands in security_audit_logs.

  * **Visible, never covert.** Granting, withdrawing and ticket-close expiry
    each post a system row into the conversation itself, so every participant
    can see that (and when) the desk could look.

Revision id 26 chars (<=32, the §NOTIFV2 varchar law). No backfill: the
feature is new; there is nothing to migrate.
"""
from alembic import op
import sqlalchemy as sa

revision = "0165_support_review_grants"
down_revision = "0164_chat_support"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "support_review_grants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ticket_id", sa.Integer(),
                  sa.ForeignKey("support_tickets.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("conversation_id", sa.String(36),
                  sa.ForeignKey("conversations.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("granted_by_dev", sa.Integer(),
                  sa.ForeignKey("developers.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("scope", sa.String(16), nullable=False, server_default="read"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.String(200), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("support_review_grants")
