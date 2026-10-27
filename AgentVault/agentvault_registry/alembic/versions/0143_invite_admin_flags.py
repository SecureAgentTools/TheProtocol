"""invite_admin_flags — an admin-granting invite now names WHICH admin capability it
confers, and stops handing out the legacy is_admin super-flag (additive)

0142 made `grants_admin` all-or-nothing, and "all" meant `is_admin` plus every granular
flag. That was wrong in two ways.

First, `is_admin` is not the authorization system. Every one of the 351 admin route gates
in this codebase calls `require_admin_flag("admin_<area>")`; `is_admin` appears inside that
gate only as a blanket short-circuit kept from before the granular flags existed. So an
invitation never needed it: the five granular flags reach the entire admin surface on their
own, and granting the bypass as well hands a new account authority that no gate asked for
and that cannot be narrowed later without editing the row by hand.

Second, all-or-nothing meant the only admin you could invite was a total one. A registry
that wants to invite a support desk, or a treasury operator, or a federation contact had to
either create the account itself (a password travels, we know it) or make that person a
superadmin. Both are worse than the thing 0142 set out to fix.

So: `admin_flags` is a JSONB list of granular flag names, chosen at mint time, and
redemption sets exactly those and leaves `is_admin` alone.

Compatibility. NULL means "minted before this column existed" and resolves to all five
granular flags — the same effective authority that invitation promised, minus the bypass.
An outstanding invitation therefore still opens every admin surface its holder was told it
would; the only thing it loses is a flag whose entire function is to skip the checks. There
is exactly one such live code in the fleet at the time of writing and it is unredeemed.

Revision ID: 0143_invite_admin_flags (≤32 chars — alembic_version.version_num is VARCHAR(32))
Revises: 0142_invite_grants_admin
"""
from alembic import op
from sqlalchemy import text

revision = "0143_invite_admin_flags"
down_revision = "0142_invite_grants_admin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IF NOT EXISTS so a re-run (migration_bridge replays on boot) is a no-op.
    # Nullable on purpose: NULL is meaningful here (see the docstring), so it must be
    # distinguishable from an empty list, which means "grants nothing".
    op.execute(text(
        "ALTER TABLE invite_codes ADD COLUMN IF NOT EXISTS admin_flags JSONB"
    ))


def downgrade() -> None:
    # Additive-only, same reasoning as 0142: dropping the column would turn every
    # narrowly-scoped invitation back into a full-admin one on the next redemption,
    # which is the dangerous direction to fail.
    pass
