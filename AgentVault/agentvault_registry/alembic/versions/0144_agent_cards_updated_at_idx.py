"""agent_cards_updated_at_idx — the index every federation pull was missing

Every federation export (`GET /api/v1/federation/agent-cards`) filters on
`agent_cards.updated_at` and orders by `(updated_at, id)`. Without an index that
is a full-table sequential scan plus sort on EVERY peer pull — measured on
registry-a: 9,142 shared buffers / 68 ms warm, 30+ seconds with a cold page
cache, which is what drove the 2026-08-05 load-722 incident (18 registries
polling each other on one box, each empty pull paying O(corpus)). With the
index the same empty-window pull reads 2 buffers in 0.09 ms.

The index was built ONLINE (`CREATE INDEX CONCURRENTLY`) on all 18 live
registry DBs on 2026-08-05 — this migration exists for NEW nodes, where
`create_all`/migration_bridge is the only path that runs (the §ESINDEX drift
lesson: `create_all` never retrofits indexes onto existing tables, and a
model-only index silently never lands on already-provisioned DBs).

Plain CREATE INDEX here, not CONCURRENTLY: alembic runs transactional, a fresh
node's table is empty-to-tiny at boot, and IF NOT EXISTS makes the replay on
already-indexed nodes a no-op.

Revision ID: 0144_agent_cards_updated_at_idx (30 chars — alembic_version.version_num is VARCHAR(32))
Revises: 0143_invite_admin_flags
"""
from alembic import op
from sqlalchemy import text

revision = "0144_agent_cards_updated_at_idx"
down_revision = "0143_invite_admin_flags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_agent_cards_updated_at_id "
        "ON agent_cards (updated_at, id)"
    ))


def downgrade() -> None:
    op.execute(text("DROP INDEX IF EXISTS ix_agent_cards_updated_at_id"))
