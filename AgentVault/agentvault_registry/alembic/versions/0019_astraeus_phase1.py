"""Astraeus Phase 1 — isolated game event log.

Revision ID: 0019_astraeus_phase1
Revises: 0018_frame_invitations

Adds a SINGLE new table: `astraeus_game_events`. Used by the Astraeus space-MMO
subsystem as an isolated append-only audit log. Game events do NOT flow through
the protocol EventStore, do NOT have emission-policy rows, and do NOT touch the
supply invariant.

If Astraeus is ever shut down, this table can be dropped in one migration
with zero impact anywhere else.

IDEMPOTENCY: migration_bridge.py re-stamps alembic_version to 0001_squash on
every boot, so all post-squash migrations replay. Every op uses IF NOT EXISTS
so replay is a no-op.
"""

from alembic import op
from sqlalchemy import text


revision = "0019_astraeus_phase1"
down_revision = "0018_frame_invitations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # pgcrypto (for gen_random_uuid fallback) is already enabled in prior migrations.
    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS astraeus_game_events (
            id              BIGSERIAL PRIMARY KEY,
            ts              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            agent_did       VARCHAR(255),
            event_type      VARCHAR(64) NOT NULL,
            system          VARCHAR(16),
            correlation_id  UUID,
            payload         JSONB NOT NULL DEFAULT '{}'::jsonb
        )
    """))

    bind.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_astraeus_events_ts
            ON astraeus_game_events (ts DESC)
    """))
    bind.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_astraeus_events_did_ts
            ON astraeus_game_events (agent_did, ts DESC)
    """))
    bind.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_astraeus_events_type
            ON astraeus_game_events (event_type)
    """))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("DROP TABLE IF EXISTS astraeus_game_events"))
