"""DEVELOPER HANDLES (2026-08-24, §OURSTATE-3 REACH) — an opt-in public name.

D5, approved: a person may CLAIM one handle so others can reach them without
knowing a numeric id — `@ruffa` instead of `developer_id 10`. Deliberately
minimal, and deliberately opt-in:

  * NULLABLE. Nobody gets a handle by existing; the column stays empty until
    someone claims one, and an account with no handle is unreachable by name —
    which is the current, private, correct default.
  * UNIQUE on the LOWERCASED value (a functional index), because "@ruFFa" and
    "@ruffa" must not be two people. The stored value keeps the claimant's
    capitalisation; every lookup lowercases.
  * A handle is an ADDRESS, not an identity: it resolves to the developer the
    registry already knows, and the profile it opens obeys the EXISTING
    `profile_visibility` field. Claiming a handle does not publish anything
    that was private.
  * `handle_claimed_at` is kept so a later release-and-reclaim policy has the
    one fact it will need. No release rail ships here: an unreleasable name is
    a smaller problem than a name that silently changes owner.

Δ-irrelevant: no money columns, nothing the supply audit reads. Additive only.

Revision ID: 0157_developer_handles
Revises: 0156_chat_rooms
"""
from alembic import op
import sqlalchemy as sa

revision = "0157_developer_handles"
down_revision = "0156_chat_rooms"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("developers", sa.Column("handle", sa.String(32), nullable=True))
    op.add_column("developers", sa.Column(
        "handle_claimed_at", sa.DateTime(timezone=True), nullable=True))
    # Case-insensitive uniqueness without a citext dependency.
    op.execute(
        "CREATE UNIQUE INDEX uq_developers_handle_lower "
        "ON developers (lower(handle)) WHERE handle IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_developers_handle_lower")
    op.drop_column("developers", "handle_claimed_at")
    op.drop_column("developers", "handle")
