"""§pass66.9 (2026-05-23) — Add is_federation_shadow flag to developers.

Backfills the flag for all existing rows where `hashed_password =
'FEDERATED_ACCOUNT_NO_LOGIN'` (the literal marker the federation_sync code
path writes when creating placeholder rows to satisfy `agent_cards.developer_id
NOT NULL` for federated agent cards whose remote developer_id is unknown
locally).

Replaces the `views/AdminDevelopers.vue` FE-only filter (§pass66.4) with
a proper column-backed filter that:
  - Works for ANY consumer of the `developers` table (CLI, future API
    clients, internal reports) not just the AdminDevelopers UI
  - Survives `hashed_password` literal renames if we ever change the
    canonical marker string
  - Indexable so `WHERE NOT is_federation_shadow` is O(real_devs)
    not O(all_devs)

Idempotent (the column-add uses IF NOT EXISTS pattern; backfill uses
UPDATE WHERE which is naturally idempotent).
"""
from alembic import op
import sqlalchemy as sa


revision: str = "0081_federation_shadow_flag"
down_revision: str = "0080_astraeus_drop"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add column with default FALSE so existing rows are NON-shadow by default.
    # We then immediately UPDATE the federation-shadow rows.
    op.execute("""
        ALTER TABLE developers
            ADD COLUMN IF NOT EXISTS is_federation_shadow BOOLEAN NOT NULL DEFAULT FALSE;
    """)
    op.execute("""
        UPDATE developers
        SET is_federation_shadow = TRUE
        WHERE hashed_password = 'FEDERATED_ACCOUNT_NO_LOGIN'
          AND is_federation_shadow = FALSE;
    """)
    # Partial index — the common query is "list real developers" which is
    # WHERE NOT is_federation_shadow. Partial index keeps it O(real_devs)
    # instead of O(all_devs incl. shadows).
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_developers_real_only
        ON developers(id)
        WHERE NOT is_federation_shadow;
    """)


def downgrade() -> None:
    # No-op — we will not regress.
    pass
