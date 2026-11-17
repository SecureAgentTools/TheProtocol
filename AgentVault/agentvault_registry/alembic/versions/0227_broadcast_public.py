"""V0664 public announcements: admin_broadcasts.is_public (default false).

An announcement an admin marks public is readable by visitors with no sign-in (GET /api/v1/public/announcements). Additive and
off for every existing row, so nothing becomes public by this migration. Rolling back drops the column (roll the image back
first: the routes then fail for want of it).

0227 was handed out beside session-code's 0226_chat_outbox_drop; both revise 0225_code_changes, and the one that merges second
re-points onto the other (as 0225 did at the V0663 cut).

Revision ID: 0227_broadcast_public
Revises: 0226_chat_outbox_drop
"""
from alembic import op
import sqlalchemy as sa

revision = "0227_broadcast_public"
down_revision = "0226_chat_outbox_drop"   # re-pointed at the V0664 cut (was 0225)
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("admin_broadcasts", sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("admin_broadcasts", "is_public")
