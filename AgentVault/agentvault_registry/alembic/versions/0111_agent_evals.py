"""0111 — Agent Evals: eval_suites / eval_tasks / eval_results (2026-07-05).

Additive-only. Three new tables backing the Agent Evals feature (gated EVALS_ENABLED,
default OFF). NO existing table touched, NO money path → **Δ-irrelevant** (evals score
agents; any pay-per-task rides the existing reward waterfall / /teg/transfer, which keeps
Δ=0 by construction). Inert until a suite is created + enabled.

IDEMPOTENT — replays every boot via migration_bridge. All DDL IF NOT EXISTS. Chains 0110.
"""
from alembic import op
from sqlalchemy import text

revision: str = "0111_agent_evals"
down_revision: str = "0110_widen_totp_secret"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS eval_suites (
            id                     SERIAL PRIMARY KEY,
            key                    VARCHAR(80) NOT NULL UNIQUE,
            name                   VARCHAR(160) NOT NULL,
            description            TEXT,
            task_type              VARCHAR(24) NOT NULL DEFAULT 'http_probe',
            config                 JSONB,
            interval_minutes       INTEGER,
            enabled                BOOLEAN NOT NULL DEFAULT FALSE,
            pay_per_task           NUMERIC(38,18) NOT NULL DEFAULT 0,
            emit_reputation_signal BOOLEAN NOT NULL DEFAULT FALSE,
            target_dids            JSONB,
            next_run_at            TIMESTAMPTZ,
            created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """))
    bind.execute(text("CREATE INDEX IF NOT EXISTS ix_eval_suites_key ON eval_suites(key);"))

    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS eval_tasks (
            id        SERIAL PRIMARY KEY,
            suite_id  INTEGER NOT NULL REFERENCES eval_suites(id) ON DELETE CASCADE,
            name      VARCHAR(160) NOT NULL,
            input     JSONB,
            scorer    VARCHAR(24) NOT NULL DEFAULT 'status_ok',
            expected  JSONB,
            weight    DOUBLE PRECISION NOT NULL DEFAULT 1.0
        );
    """))
    bind.execute(text("CREATE INDEX IF NOT EXISTS ix_eval_tasks_suite ON eval_tasks(suite_id);"))

    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS eval_results (
            id               BIGSERIAL PRIMARY KEY,
            run_id           VARCHAR(64) NOT NULL,
            suite_id         INTEGER NOT NULL,
            task_id          INTEGER,
            agent_did        VARCHAR(120) NOT NULL,
            score            DOUBLE PRECISION NOT NULL DEFAULT 0.0,
            passed           BOOLEAN NOT NULL DEFAULT FALSE,
            latency_ms       INTEGER,
            response_excerpt TEXT,
            error            TEXT,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """))
    bind.execute(text("CREATE INDEX IF NOT EXISTS ix_eval_results_run ON eval_results(run_id);"))
    bind.execute(text("CREATE INDEX IF NOT EXISTS ix_eval_results_suite ON eval_results(suite_id);"))
    bind.execute(text("CREATE INDEX IF NOT EXISTS ix_eval_results_agent ON eval_results(agent_did);"))
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_eval_results_agent_suite_time "
        "ON eval_results(agent_did, suite_id, created_at);"
    ))


def downgrade() -> None:
    # Additive migrations stay in place on rollback (house rule); dropping would
    # lose eval history. No-op.
    pass
