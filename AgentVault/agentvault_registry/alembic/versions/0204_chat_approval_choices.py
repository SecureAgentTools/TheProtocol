"""V0652 (ab) (2026-10-31, agentvault2-14): choice cards, a decision that is not yes or no.

Order gwo_dfa5e1d0ce56a8ceb0d1f61b. TWO nullable columns on `chat_approvals`, nothing else touched: `options` (JSONB, the
2 to 5 labels a choice request offers; NULL for an approval, so every existing row stays an approval) and
`chosen_option` (the index of the option the org's owner or a named approver chose; NULL until then, and for an
approval). A choice is recorded, decided, expired, signed and shown by the same rail as an approval (its status reads
`chosen`); it opens no act. No backfill: no choice existed before this revision.

Rolling back drops both (a choice then reads as an approval request without its options, and a chosen one as an
unknown status); the two-step rule applies as for every additive revision (downgrade first from an image that has it,
then the older image).

Revision ID: 0204_chat_approval_choices
Revises: 0203_chat_message_sent_by (rechained at the V0652 cut, after (aj)'s 0203)
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0204_chat_approval_choices"
down_revision = "0203_chat_message_sent_by"   # rechained at the V0652 cut, after (aj)'s 0203
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_approvals", sa.Column("options", postgresql.JSONB(), nullable=True))
    op.add_column("chat_approvals", sa.Column("chosen_option", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("chat_approvals", "chosen_option")
    op.drop_column("chat_approvals", "options")
