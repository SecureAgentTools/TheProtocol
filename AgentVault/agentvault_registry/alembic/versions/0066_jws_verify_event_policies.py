"""Add event_emission_policies rows for JWS verify lifecycle (§pass47 A6).

Revision ID: 0066_jws_events
Revises: 0065_org_events
Create Date: 2026-05-19

Adds policy rows for the two JWS-verify lifecycle events:

  - AgentCardJWSVerifyFailed      — emitted by pull-sync on invalid signature
                                     (when JWS_VERIFY_ENABLED=true)
  - AgentFlaggedForJWSFailures    — emitted by the throttle reactor after the
                                     Nth failure within the window

Both registry-emitted, audit-only (skip_in_projection=true).
Idempotent via ON CONFLICT DO NOTHING.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "0066_jws_events"
down_revision: Union[str, None] = "0065_org_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_TYPES = (
    "AgentCardJWSVerifyFailed",
    "AgentFlaggedForJWSFailures",
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
