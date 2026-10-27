"""0090 — DevCard passport consent flag (§V0064 settings view, 2026-06-13).

developers.dev_card_passport_opt_out: a developer-level refusal switch for
owner-identity disclosure to foreign venues. Enforced in build_signed_devcard
(403 → the dev's agents cannot Passport-trade while opted out). Default FALSE:
the D24 consent model stands (the dev's own agent initiating participation IS
the consent) — this flag is the explicit override surface in Settings.

IDEMPOTENT — migration_bridge replays every migration at each container boot.
"""
from alembic import op
from sqlalchemy import text

revision: str = "0090_devcard_consent"
down_revision: str = "0089_devcard"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(text(
        "ALTER TABLE developers ADD COLUMN IF NOT EXISTS "
        "dev_card_passport_opt_out BOOLEAN NOT NULL DEFAULT FALSE"
    ))


def downgrade() -> None:
    # Forward-only (squash-replay model).
    pass
