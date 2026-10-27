"""§OURSTATE-6 — the disappearing timer, and honest hosting.

The E2EE spike (2026-08-24) argued that the honest way to reduce what an
operator retains is not to pretend they cannot read what they host, but to
keep less of it. This is that: a per-thread retention window, set by a
participant, enforced by a sweeper, and stated in the thread.

Design notes:

  * **Null means keep** — D9's ruling was "keep by default", so an untouched
    thread behaves exactly as it did yesterday.
  * **The window lives on the CONVERSATION, not the participant.** A timer that
    one side could set privately would be a promise about the other side's copy
    that we cannot keep; both sides see the same window and are told when it
    changes.
  * **Messages are DELETED, not tombstoned.** §11: chat text is not a financial
    record (the ledger and receipts carry that), so it can be genuinely
    deleted — and a "deleted" marker that keeps the row is the privacy theatre
    the same section forbids. Money cards leave their trace on the ledger,
    which is where a receipt belongs anyway.
"""
from alembic import op
import sqlalchemy as sa

revision = "0163_chat_retention"
down_revision = "0162_org_chat_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column(
        "retention_hours", sa.Integer, nullable=True))
    op.add_column("conversations", sa.Column(
        "retention_set_by", sa.String(255), nullable=True))
    op.add_column("conversations", sa.Column(
        "retention_set_at", sa.DateTime(timezone=True), nullable=True))
    # The sweeper asks "which threads have a window at all", which is a tiny
    # fraction of rows — a partial index keeps that scan honest as the table
    # grows.
    op.create_index("ix_conversations_retention", "conversations",
                    ["retention_hours"],
                    postgresql_where=sa.text("retention_hours IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("ix_conversations_retention", table_name="conversations")
    op.drop_column("conversations", "retention_set_at")
    op.drop_column("conversations", "retention_set_by")
    op.drop_column("conversations", "retention_hours")
