"""0125 — auth lifecycle hardening: token_version + api-key scopes/expiry (2026-07-24).

Additive-only, idempotent (ADD COLUMN IF NOT EXISTS), chains 0124. Δ-irrelevant
(schema only). Backs the developer-credential-leak fix:
  • developers.token_version — monotonic revocation counter stamped into every
    access token as the `tv` claim. Bump it (logout / password change / admin
    force-logout) to invalidate ALL of a developer's live tokens at once. Default
    0; pre-deploy tokens carry no `tv` and are grandfathered until they expire.
  • developer_api_keys.scopes — JSONB list; existing keys grandfather to ['*']
    (full authority, unchanged — MCP bridge keys keep working). New keys may be
    minted narrower; scope enforcement is opt-in per route.
  • developer_api_keys.expires_at — optional forced-rotation expiry. NULL = never
    (all existing keys). New keys default to API_KEY_DEFAULT_TTL_DAYS at mint.

Rollback tolerant: older image ignores the extra columns; leave the migration in.
"""
from alembic import op
from sqlalchemy import text

# revision id MUST be ≤32 chars (alembic_version.version_num is varchar(32)).
revision: str = "0125_auth_lifecycle"
down_revision: str = "0124_forge_lineage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text(
        "ALTER TABLE developers ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 0"))
    bind.execute(text(
        "ALTER TABLE developer_api_keys ADD COLUMN IF NOT EXISTS scopes JSONB NOT NULL DEFAULT '[\"*\"]'::jsonb"))
    bind.execute(text(
        "ALTER TABLE developer_api_keys ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ"))
    # Partial index so the expiry sweep / lookup filter stays cheap (most keys are NULL).
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_devapikey_expires_at "
        "ON developer_api_keys (expires_at) WHERE expires_at IS NOT NULL"))


def downgrade() -> None:
    # Additive migration — no destructive downgrade (rolling DOWN past a newer
    # head crash-loops; leave the columns). Intentional no-op.
    pass
