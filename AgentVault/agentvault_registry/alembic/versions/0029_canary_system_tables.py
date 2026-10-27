"""Canary system Phase 2 — canary_agents + canary_paths + canary_test_results (2026-05-04).

Revision ID: 0029_canary_system_tables
Revises: 0028_agents_is_canary

Phase 2 of the canary transfer system. Creates the configurable, hot-reloadable
matrix of canary agents + test paths + test result history. Lives only on the
Frame A mainframe (registry-a). Phase 3 `canary_runner` reads `canary_paths`,
fires transfers, writes Redis state. Phase 5 `canary_judge` writes final
outcomes to `canary_test_results`.

Idempotent (IF NOT EXISTS) so migration_bridge.py replays on every container
boot remain safe.

Schema follows HANDOVER_2026-05-04_CANARY_TRANSFER_SYSTEM.md §"Configurable matrix".
"""
from alembic import op


revision = "0029_canary_system_tables"
down_revision = "0028_agents_is_canary"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS canary_agents (
            id              BIGSERIAL PRIMARY KEY,
            agent_did       VARCHAR(255) UNIQUE NOT NULL,
            client_id       VARCHAR(255) NOT NULL,
            client_secret   TEXT NOT NULL,
            registry_id     VARCHAR(64) NOT NULL,
            registry_url    VARCHAR(255) NOT NULL,
            frame           VARCHAR(64) NOT NULL,
            is_active       BOOLEAN NOT NULL DEFAULT true,
            prefund_amount  NUMERIC(36, 18) NOT NULL DEFAULT 100000,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            notes           TEXT
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_canary_agents_active ON canary_agents(is_active) WHERE is_active = true;")
    op.execute("CREATE INDEX IF NOT EXISTS idx_canary_agents_frame ON canary_agents(frame);")

    op.execute("""
        CREATE TABLE IF NOT EXISTS canary_paths (
            id                    BIGSERIAL PRIMARY KEY,
            path_id               VARCHAR(128) UNIQUE NOT NULL,
            sender_agent_id       BIGINT NOT NULL REFERENCES canary_agents(id) ON DELETE RESTRICT,
            receiver_agent_id     BIGINT NOT NULL REFERENCES canary_agents(id) ON DELETE RESTRICT,
            backend               VARCHAR(16) NOT NULL,
            amount                NUMERIC(36, 18) NOT NULL DEFAULT 1.0,
            interval_sec          INTEGER NOT NULL DEFAULT 60,
            slo_http_ms           INTEGER NOT NULL DEFAULT 1000,
            slo_settled_sec       INTEGER NOT NULL DEFAULT 60,
            slo_p95_latency_ms    INTEGER,
            is_active             BOOLEAN NOT NULL DEFAULT true,
            reverse_pair_id       BIGINT REFERENCES canary_paths(id) ON DELETE SET NULL,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            notes                 TEXT,
            CONSTRAINT canary_paths_backend_check CHECK (backend IN ('async', '2pc', 'intra'))
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_canary_paths_active ON canary_paths(is_active) WHERE is_active = true;")
    op.execute("CREATE INDEX IF NOT EXISTS idx_canary_paths_backend ON canary_paths(backend);")

    op.execute("""
        CREATE TABLE IF NOT EXISTS canary_test_results (
            id                BIGSERIAL PRIMARY KEY,
            test_id           VARCHAR(128) UNIQUE NOT NULL,
            path_id           BIGINT NOT NULL REFERENCES canary_paths(id) ON DELETE CASCADE,
            fired_at          TIMESTAMPTZ NOT NULL,
            completed_at      TIMESTAMPTZ,
            backend           VARCHAR(16) NOT NULL,
            sender_did        VARCHAR(255) NOT NULL,
            receiver_did      VARCHAR(255) NOT NULL,
            amount            NUMERIC(36, 18) NOT NULL,
            transfer_id       VARCHAR(64),
            http_status       INTEGER,
            http_latency_ms   INTEGER,
            total_latency_ms  INTEGER,
            phase_latencies   JSONB,
            outcome           VARCHAR(16) NOT NULL DEFAULT 'fired',
            failure_type      VARCHAR(64),
            failure_detail    JSONB,
            CONSTRAINT canary_test_results_outcome_check CHECK (outcome IN ('fired', 'passed', 'failed'))
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_canary_results_path_fired ON canary_test_results(path_id, fired_at DESC);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_canary_results_failures ON canary_test_results(fired_at DESC) WHERE outcome = 'failed';")
    op.execute("CREATE INDEX IF NOT EXISTS idx_canary_results_outcome ON canary_test_results(outcome, fired_at DESC);")


def downgrade():
    op.execute("DROP TABLE IF EXISTS canary_test_results;")
    op.execute("DROP TABLE IF EXISTS canary_paths;")
    op.execute("DROP TABLE IF EXISTS canary_agents;")
