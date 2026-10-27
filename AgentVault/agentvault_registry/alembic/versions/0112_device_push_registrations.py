"""0112 — POCKET FRAME: device_push_registrations (2026-07-07).

Additive-only. One new table backing mobile/desktop push notification device
registration (gated PUSH_NOTIFY_ENABLED, default OFF). NO existing table touched,
NO money path → **Δ-irrelevant** (read-side notification fan-out only; every
notified action already happened through its own audited flow).

IDEMPOTENT — replays every boot via migration_bridge. All DDL IF NOT EXISTS. Chains 0111.
"""
from alembic import op
from sqlalchemy import text

revision: str = "0112_device_push_registrations"
down_revision: str = "0111_agent_evals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS device_push_registrations (
            id            SERIAL PRIMARY KEY,
            developer_id  INTEGER NOT NULL REFERENCES developers(id) ON DELETE CASCADE,
            platform      VARCHAR(16) NOT NULL DEFAULT 'android',
            rail          VARCHAR(16) NOT NULL DEFAULT 'ntfy',
            target        VARCHAR(255) NOT NULL,
            label         VARCHAR(120),
            enabled       BOOLEAN NOT NULL DEFAULT TRUE,
            prefs         JSONB,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_device_push_dev_rail_target UNIQUE (developer_id, rail, target)
        )
    """))
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_device_push_developer "
        "ON device_push_registrations (developer_id) WHERE enabled"
    ))


def downgrade() -> None:
    # Additive-only doctrine: leave the table in place on downgrade
    # (feedback_registry_rollback_alembic_downgrade_crash).
    pass
