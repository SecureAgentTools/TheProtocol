"""0093 — federated_stock_cards (Federated Stock Cards consume cache, 2026-06-17).

Additive table: one cached AGORA Stock Card per federated peer (by SPIFFE).
Catalog-only (no live prices). Populated ONLY by federation_sync when
STOCK_CARD_SYNC_ENABLED + signature verifies (fail-closed). Touches no existing
table → Δ-irrelevant (read-only metadata; trading settles via passport/escrow).

IDEMPOTENT — migration_bridge.py resets alembic_version to 0001_squash on every
container boot, so every post-squash migration REPLAYS. All raw SQL is
`IF NOT EXISTS` (see 0092_fx_reserve_keeper.py for the same pattern).
"""
from alembic import op
from sqlalchemy import text

revision: str = "0093_federated_stock_cards"
down_revision: str = "0092_fx_reserve_keeper"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text(
        """
        CREATE TABLE IF NOT EXISTS federated_stock_cards (
            id                    BIGSERIAL      PRIMARY KEY,
            source_spiffe_id      VARCHAR(255)   NOT NULL UNIQUE,
            source_registry_name  VARCHAR(128),
            currency              VARCHAR(8),
            listings_json         JSON           NOT NULL DEFAULT '[]'::json,
            digest                VARCHAR(80)    NOT NULL,
            signature_verified    BOOLEAN        NOT NULL DEFAULT false,
            fetched_at            TIMESTAMPTZ    NOT NULL DEFAULT now(),
            updated_at            TIMESTAMPTZ    NOT NULL DEFAULT now()
        )
        """
    ))
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_federated_stock_cards_source_spiffe_id "
        "ON federated_stock_cards (source_spiffe_id)"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("DROP TABLE IF EXISTS federated_stock_cards"))
