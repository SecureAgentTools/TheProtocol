"""Attestation schedules (Phase 5 — periodic attestation cron).

Revision ID: 0024_attestation_schedules
Revises: 0022_attestation_bundle_cache

Adds the `attestation_schedules` table — registry-side bookkeeping for
agents that publish recurring claims. Each row binds (agent_did, circuit_id)
to an interval; the daily cron emits `AttestationDueReminder` when an
entry slips past `next_due_at` (with daily idempotency via `last_reminder_at`).

Idempotent: CREATE TABLE / INDEX IF NOT EXISTS.
"""

from alembic import op
from sqlalchemy import text


revision = "0024_attestation_schedules"
down_revision = "0022_attestation_bundle_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS attestation_schedules (
            id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_did              VARCHAR(255) NOT NULL,
            circuit_id             VARCHAR(255) NOT NULL,
            interval_hours         INTEGER NOT NULL,
            enabled                BOOLEAN NOT NULL DEFAULT TRUE,
            last_attestation_at    TIMESTAMPTZ,
            next_due_at            TIMESTAMPTZ NOT NULL,
            last_reminder_at       TIMESTAMPTZ,
            created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))

    bind.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_attestation_schedules_agent_circuit "
        "ON attestation_schedules (agent_did, circuit_id)"
    ))

    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_attestation_schedules_due "
        "ON attestation_schedules (next_due_at) "
        "WHERE enabled = TRUE"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("DROP INDEX IF EXISTS ix_attestation_schedules_due"))
    bind.execute(text("DROP INDEX IF EXISTS uq_attestation_schedules_agent_circuit"))
    bind.execute(text("DROP TABLE IF EXISTS attestation_schedules"))
