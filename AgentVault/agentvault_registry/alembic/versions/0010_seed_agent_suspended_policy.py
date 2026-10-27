"""Seed AgentSuspended event_emission_policies row (M2).

The original M1 migration (0009) pre-dated the M2 admin_agents.py router which
emits AgentSuspended events from POST /admin/agents/bulk/suspend.  Added after
0009 was already marked applied, so we ship this as a new idempotent seed step.

Revision ID: 0010_seed_agent_suspended_policy
Revises: 0009_developer_admin_mgmt
"""

from alembic import op
from sqlalchemy import text


revision = "0010_seed_agent_suspended_policy"
down_revision = "0009_developer_admin_mgmt"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        text("""
            INSERT INTO event_emission_policies
              (event_type, emit_from_teg, emit_from_registry, skip_in_projection, description, updated_at)
            VALUES
              ('AgentSuspended', false, true, true,
               'Admin (or bulk) suspended an agent without a prior enforcement-queue proposal.',
               now())
            ON CONFLICT (event_type) DO NOTHING
        """)
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        text("DELETE FROM event_emission_policies WHERE event_type = 'AgentSuspended'")
    )
