"""§bc5 T5.6 — CICDNotificationSent audit policy.

Revision ID: 0074_bc5_cicd_notif
Revises: 0073_bc4_org_event
Create Date: 2026-05-19

Audit-only event emitted by reactor_cicd_notification.py whenever a
CI/CD deployment event is converted into a user-targeted notification.
Proof-of-delivery for ops review. skip_in_projection=true because no
tokens move.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0074_bc5_cicd_notif"
down_revision: Union[str, None] = "0073_bc4_org_event"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO event_emission_policies
            (event_type, emit_from_teg, emit_from_registry, skip_in_projection)
        VALUES ('CICDNotificationSent', false, true, true)
        ON CONFLICT (event_type) DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("DELETE FROM event_emission_policies WHERE event_type='CICDNotificationSent';")
