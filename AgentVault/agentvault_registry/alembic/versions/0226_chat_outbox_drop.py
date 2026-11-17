"""V0664 (order gwo_efdd53bd198423a5ec2b742d): an admin may drop one stuck chat federation outbox row, with a reason.

`chat_federation_outbox.dropped_at`, `dropped_by` (the admin's developer id) and `drop_reason`: a dropped row stays (the record of
what was not delivered, and why), is never due again and never holds the later rows of its thread. The message itself is never
deleted. Nullable columns, no default: every existing row reads "not dropped".

Rolling back keeps a dropped row from being sent by the older image: it reads as given up there (attempts at least 12, the
MAX_ATTEMPTS of this release) with the reason in last_error, then the columns go. The two-step rule applies (downgrade first from
an image that has it, then the older image).

Revision ID: 0226_chat_outbox_drop
Revises: 0225_code_changes
"""
from alembic import op
import sqlalchemy as sa

revision = "0226_chat_outbox_drop"
down_revision = "0225_code_changes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_federation_outbox", sa.Column("dropped_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("chat_federation_outbox", sa.Column("dropped_by", sa.Integer(), nullable=True))
    op.add_column("chat_federation_outbox", sa.Column("drop_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.execute("UPDATE chat_federation_outbox SET attempts = GREATEST(attempts, 12), "
               "last_error = 'dropped by an admin: ' || COALESCE(drop_reason, '') "
               "WHERE dropped_at IS NOT NULL AND delivered_at IS NULL")
    op.drop_column("chat_federation_outbox", "drop_reason")
    op.drop_column("chat_federation_outbox", "dropped_by")
    op.drop_column("chat_federation_outbox", "dropped_at")
