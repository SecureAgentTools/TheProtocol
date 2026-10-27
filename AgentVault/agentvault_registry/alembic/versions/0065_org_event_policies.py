"""Add event_emission_policies rows for the Organization service (§pass47 O3).

Revision ID: 0065_org_events
Revises: 0064_cicd_events
Create Date: 2026-05-19

Adds emission policies for the 5 organization lifecycle events emitted by
`services/organization_service.py`. All registry-emitted audit-only events.

  - OrganizationCreated
  - OrganizationDeleted
  - OrganizationMemberInvited
  - OrganizationMemberJoined
  - OrganizationMemberRemoved

All emit_from_registry=true · emit_from_teg=false · skip_in_projection=true
(no balance impact; audit trail only).

Idempotent via ON CONFLICT DO NOTHING.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "0065_org_events"
down_revision: Union[str, None] = "0064_cicd_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_TYPES = (
    "OrganizationCreated",
    "OrganizationDeleted",
    "OrganizationMemberInvited",
    "OrganizationMemberJoined",
    "OrganizationMemberRemoved",
)


def upgrade() -> None:
    bind = op.get_bind()
    for evt in _NEW_TYPES:
        bind.execute(text("""
            INSERT INTO event_emission_policies
                (event_type, emit_from_teg, emit_from_registry, skip_in_projection)
            VALUES (:evt, false, true, true)
            ON CONFLICT (event_type) DO NOTHING;
        """), {"evt": evt})


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text(
        "DELETE FROM event_emission_policies WHERE event_type IN ("
        + ",".join(f"'{t}'" for t in _NEW_TYPES)
        + ");"
    ))
