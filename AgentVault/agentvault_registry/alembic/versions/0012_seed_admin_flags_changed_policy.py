"""Seed DeveloperAdminFlagsChanged event policy (Fix 1).

Revision ID: 0012_admin_flags_policy
Revises: 0011_admin_flag_split

(Shortened from 0012_seed_admin_flags_changed_policy because alembic_version.version_num
is VARCHAR(32) and the original string was 37 chars.)
"""

from alembic import op
from sqlalchemy import text


revision = "0012_admin_flags_policy"
down_revision = "0011_admin_flag_split"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        text("""
            INSERT INTO event_emission_policies
              (event_type, emit_from_teg, emit_from_registry, skip_in_projection, description, updated_at)
            VALUES
              ('DeveloperAdminFlagsChanged', false, true, true,
               'Admin modified granular admin flags on a developer (Fix 1 role split). Payload: before/after per flag.',
               now())
            ON CONFLICT (event_type) DO NOTHING
        """)
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        text("DELETE FROM event_emission_policies WHERE event_type = 'DeveloperAdminFlagsChanged'")
    )
