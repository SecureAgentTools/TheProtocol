"""0089 — DevCard v0.1 disclosure audit (AGORA Passport §9).

dev_card_disclosures: one row per DevCard pull — who (peer SPIFFE), for which
agent, when, for what purpose. The GDPR purpose-binding ledger for the lazy,
consent-bound owner-identity disclosure (DevCards are NEVER bulk-synced).

IDEMPOTENT — migration_bridge replays every migration at each container boot.
"""
from alembic import op
from sqlalchemy import text

revision: str = "0089_devcard"
down_revision: str = "0088_agora_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(text("""
        CREATE TABLE IF NOT EXISTS dev_card_disclosures (
            id BIGSERIAL PRIMARY KEY,
            developer_id INTEGER NOT NULL,
            agent_did VARCHAR(120) NOT NULL,
            requested_by VARCHAR(255) NOT NULL,
            purpose VARCHAR(64) NOT NULL DEFAULT 'exchange_participation',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))
    op.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_dev_card_disclosures_dev ON dev_card_disclosures (developer_id, created_at)"
    ))


def downgrade() -> None:
    # Forward-only (squash-replay model).
    pass
