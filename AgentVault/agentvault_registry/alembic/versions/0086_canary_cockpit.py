"""0086 — Canary Cockpit: master-side remote-path schedule + dispatch audit ledger.

§V0045: registry-a (CANARY_RUNNER_MODE=master) schedules canary fires for the WHOLE
fleet; peer registries execute via the federation mTLS channel (/api/v1/federation/
canary-fire) — their agents fire, their SVIDs/creds stay home (the IRONHAND cockpit
pattern generalized to the scheduled canary system). Two master-side tables (harmless
empty on followers/standalone):
  - canary_remote_paths : schedule rows for paths homed on peer registries
                          (master owns scheduling; the home keeps execution config)
  - canary_dispatches   : audit ledger of dispatched fires (test_id = the end-to-end
                          idempotency key; outcome sent|acked|replayed|rejected|dispatch_failed)

IDEMPOTENT — migration_bridge.py resets alembic_version to 0001_squash on every container
boot, so every post-squash migration REPLAYS. All raw SQL is `IF NOT EXISTS`.
"""
from alembic import op
from sqlalchemy import text

revision: str = "0086_canary_cockpit"
down_revision: str = "0085_fx_router_keeper"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(text("""
        CREATE TABLE IF NOT EXISTS canary_remote_paths (
            id BIGSERIAL PRIMARY KEY,
            home_registry VARCHAR(128) NOT NULL,
            remote_path_id BIGINT NOT NULL,
            path_label VARCHAR(128) NOT NULL,
            interval_sec INTEGER NOT NULL DEFAULT 60,
            is_active BOOLEAN NOT NULL DEFAULT true,
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_canary_remote_paths_home_path UNIQUE (home_registry, remote_path_id)
        )
    """))
    op.execute(text("""
        CREATE TABLE IF NOT EXISTS canary_dispatches (
            id BIGSERIAL PRIMARY KEY,
            test_id VARCHAR(160) NOT NULL UNIQUE,
            home_registry VARCHAR(128) NOT NULL,
            remote_path_id BIGINT NOT NULL,
            path_label VARCHAR(128) NOT NULL,
            dispatched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            outcome VARCHAR(32) NOT NULL DEFAULT 'sent',
            http_status INTEGER,
            latency_ms INTEGER,
            error TEXT
        )
    """))
    op.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_canary_dispatches_dispatched_at ON canary_dispatches (dispatched_at)"
    ))
    op.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_canary_dispatches_home_time ON canary_dispatches (home_registry, dispatched_at)"
    ))


def downgrade() -> None:
    # Forward-only (matches the squash-replay model); tables are additive + tiny.
    pass
