"""§pass49 B1 — agent_flags table for persistent flag state.

Revision ID: 0068_agent_flags
Revises: 0067_drift_event
Create Date: 2026-05-19

Reactors (JWS throttle, drift) currently emit EventStore events but the
flag state lives ONLY in the reactor's in-memory ring buffer. There's no
way to: (a) ask "is agent X currently flagged?" via SQL, (b) acknowledge
a flag from the UI, (c) keep flag history across registry restarts.

This migration adds `agent_flags` — one row per (agent_did, flag_type)
raised event, with acknowledged_at/by populated when an admin clears it.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "0068_agent_flags"
down_revision: Union[str, None] = "0067_drift_event"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_flags (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_did               VARCHAR(255) NOT NULL,
            flag_type               VARCHAR(64)  NOT NULL,
            raised_at               TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            raised_by_event_id      VARCHAR(36),
            reason                  VARCHAR(500),
            source                  VARCHAR(64),
            details                 JSONB,
            acknowledged_at         TIMESTAMPTZ,
            acknowledged_by_dev_id  INTEGER REFERENCES developers(id) ON DELETE SET NULL,
            ack_notes               VARCHAR(500)
        );
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_agent_flags_did_type
        ON agent_flags(agent_did, flag_type);
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_agent_flags_unacked
        ON agent_flags(agent_did, flag_type, raised_at DESC)
        WHERE acknowledged_at IS NULL;
    """)
    # Policy row for the acknowledgement event.
    op.execute("""
        INSERT INTO event_emission_policies
            (event_type, emit_from_teg, emit_from_registry, skip_in_projection)
        VALUES ('AgentFlagAcknowledged', false, true, true)
        ON CONFLICT (event_type) DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_agent_flags_unacked;")
    op.execute("DROP INDEX IF EXISTS idx_agent_flags_did_type;")
    op.execute("DROP TABLE IF EXISTS agent_flags;")
    op.execute("DELETE FROM event_emission_policies WHERE event_type='AgentFlagAcknowledged';")
