"""Admin flag split (Fix 1): add 5 granular admin_* flags + backfill from is_admin.

Adds five boolean columns to developers for granular platform-admin roles:
  - admin_treasury       — fund-agent, mint, emission policies, projection snapshots, funding requests
  - admin_support        — support tickets, broadcast, invite codes
  - admin_enforcement    — disputes ruling, agent suspend/revoke/slash, enforcement policy
  - admin_federation     — operator approve/reject/revoke, licenses, cloud provisioning, Docker pull tokens
  - admin_platform       — diagnostics, api-tester, simulation, tutorials, system-health, developer admin

Backfill: every existing developer with is_admin=True gets all five flags set to True
(preserves the status quo — today only dev_id=10 Commander). Legacy is_admin column
remains untouched as the canonical source of truth until routers migrate to
require_admin_flag(); once migration is complete, is_admin becomes a computed derivative
of any(five flags) and can be dropped.

Revision ID: 0011_admin_flag_split
Revises: 0010_seed_agent_suspended_policy
"""

from alembic import op
from sqlalchemy import text


revision = "0011_admin_flag_split"
down_revision = "0010_seed_agent_suspended_policy"
branch_labels = None
depends_on = None


_FLAG_COLUMNS = (
    "admin_treasury",
    "admin_support",
    "admin_enforcement",
    "admin_federation",
    "admin_platform",
)


def upgrade() -> None:
    bind = op.get_bind()

    for col in _FLAG_COLUMNS:
        bind.execute(text(f"""
            ALTER TABLE developers
            ADD COLUMN IF NOT EXISTS {col} BOOLEAN NOT NULL DEFAULT FALSE
        """))

    # Backfill: any developer currently marked is_admin=True gets all 5 flags
    # This preserves every existing admin's full authority. Going forward, new
    # sub-admins get only the flags they need.
    bind.execute(text(f"""
        UPDATE developers
        SET {", ".join(f"{col} = TRUE" for col in _FLAG_COLUMNS)}
        WHERE is_admin = TRUE
    """))


def downgrade() -> None:
    bind = op.get_bind()
    for col in _FLAG_COLUMNS:
        bind.execute(text(f"ALTER TABLE developers DROP COLUMN IF EXISTS {col}"))
