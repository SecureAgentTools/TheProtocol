"""Add event_emission_policies row for AgentCardPersistentDrift (§pass47 B5).

Revision ID: 0067_drift_event
Revises: 0066_jws_events
Create Date: 2026-05-19

The new event is emitted by `reactor_agent_card_drift.py` on persistent
per-field drift (default: 3 events in 24h). Audit only, no balance impact.

Idempotent via ON CONFLICT DO NOTHING.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "0067_drift_event"
down_revision: Union[str, None] = "0066_jws_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("""
        INSERT INTO event_emission_policies
            (event_type, emit_from_teg, emit_from_registry, skip_in_projection)
        VALUES ('AgentCardPersistentDrift', false, true, true)
        ON CONFLICT (event_type) DO NOTHING;
    """))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text(
        "DELETE FROM event_emission_policies WHERE event_type = 'AgentCardPersistentDrift';"
    ))
