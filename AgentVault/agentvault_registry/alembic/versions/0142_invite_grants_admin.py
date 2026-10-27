"""invite_grants_admin — let an invite code mint a full admin, so a handed-over registry
needs no pre-made admin account and no password ever travels by email (additive)

Context: a sovereign frame given to an outside party has to get its first administrator
somehow. Until now that meant creating the account here and mailing the credentials, which
means (a) a password travels through a mailbox, (b) we know it, and (c) the recipient never
accepts the terms themselves because the account predates them.

An admin-granting invite inverts that. The operator generates ONE code, sends only the code,
and the recipient registers themselves: they choose the password, they accept the terms, and
the account is an admin from the moment it exists. Nobody else ever holds the credential.

Deliberately a column on the code rather than a separate table or a role: the grant is a
property OF THE INVITATION, consumed exactly once with it, and `use_count`/`max_uses` already
bound how many accounts a code can mint. Default FALSE, so every existing code and every code
generated without the new flag behaves exactly as before — this migration cannot change the
meaning of an outstanding invitation.

Revision ID: 0142_invite_grants_admin (≤32 chars — alembic_version.version_num is VARCHAR(32))
Revises: 0141_registry_card_assets
"""
from alembic import op
from sqlalchemy import text

revision = "0142_invite_grants_admin"
down_revision = "0141_registry_card_assets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IF NOT EXISTS so a re-run (migration_bridge replays on boot) is a no-op.
    op.execute(text(
        "ALTER TABLE invite_codes "
        "ADD COLUMN IF NOT EXISTS grants_admin BOOLEAN NOT NULL DEFAULT false"
    ))


def downgrade() -> None:
    # Deliberately additive-only. Dropping the column would silently downgrade any
    # outstanding admin invitation to an ordinary one, which is a worse failure than
    # leaving an unused boolean behind.
    pass
