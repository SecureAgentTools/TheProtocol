"""0120 — developer ToS consent record (2026-07-09).

Additive-only. Persists proof that a developer accepted the Terms at registration — the audit trail
behind the register form's checkbox, which until now was CLIENT-SIDE ONLY (a scripted client could
register with no acceptance signal at all). The SERVER stamps the version it currently serves +
the timestamp, so the record is authoritative and the client cannot lie about which terms it saw.

  tos_accepted_version : the ToS version string in force when the account was created (server-stamped)
  tos_accepted_at      : when acceptance was recorded

Both nullable — pre-existing accounts have no record (never claimed to), and the fiat-onramp
auto-create path is untouched. IDEMPOTENT (IF NOT EXISTS), chains 0119.
"""
from alembic import op
from sqlalchemy import text

revision: str = "0120_developer_tos_consent"
down_revision: str = "0119_guild_v2_remote_money"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("ALTER TABLE developers ADD COLUMN IF NOT EXISTS tos_accepted_version VARCHAR(40)"))
    bind.execute(text("ALTER TABLE developers ADD COLUMN IF NOT EXISTS tos_accepted_at TIMESTAMPTZ"))


def downgrade() -> None:
    pass
