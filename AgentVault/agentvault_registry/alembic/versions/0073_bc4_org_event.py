"""§bc4 T4.6 — OrgBroadcastSent audit event policy.

Revision ID: 0073_bc4_org_event
Revises: 0072_bc3_templates
Create Date: 2026-05-19

Audit row inserted whenever an admin sends a broadcast with target_org_id
set (i.e., org-scoped). Distinguishes org-targeted from federation-wide
in the EventStore audit feed.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0073_bc4_org_event"
down_revision: Union[str, None] = "0072_bc3_templates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO event_emission_policies
            (event_type, emit_from_teg, emit_from_registry, skip_in_projection)
        VALUES ('OrgBroadcastSent', false, true, true)
        ON CONFLICT (event_type) DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("DELETE FROM event_emission_policies WHERE event_type='OrgBroadcastSent';")
