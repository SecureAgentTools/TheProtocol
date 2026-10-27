"""0084 — API-key O(1) lookup: add indexed key_sha256 to developer_api_keys.

API keys are 256-bit random tokens (`secrets.token_urlsafe(32)`). They were stored
ONLY as a bcrypt hash, which is salted/non-deterministic — so authenticating a key
meant loading every active key row and bcrypt-verifying each until a match (O(N)
bcrypts/request, ~215 ms each). Add a deterministic, UNIQUE-indexed SHA-256 column so
a key is found in O(1). The column is nullable: pre-existing rows keep NULL and are
backfilled lazily on their next successful auth, so this migration touches no data.

IDEMPOTENT — `migration_bridge.py` resets alembic_version to 0001_squash on every
container boot, so every post-squash migration replays. Uses raw `IF NOT EXISTS`.
"""
from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = "0084_api_key_sha256_lookup"
down_revision: str = "0083_backfill_schema_drift"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text(
        "ALTER TABLE developer_api_keys "
        "ADD COLUMN IF NOT EXISTS key_sha256 VARCHAR(64) NULL"
    ))
    # UNIQUE index on a nullable column: Postgres treats NULLs as distinct, so the
    # many existing NULL rows do not collide — only real sha256 values are deduped.
    bind.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_developer_api_keys_key_sha256 "
        "ON developer_api_keys (key_sha256)"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("DROP INDEX IF EXISTS ix_developer_api_keys_key_sha256"))
    bind.execute(text("ALTER TABLE developer_api_keys DROP COLUMN IF EXISTS key_sha256"))
