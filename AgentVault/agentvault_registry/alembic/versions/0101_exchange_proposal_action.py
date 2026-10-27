"""0101 — P1.4 governance-gated corporate actions (2026-06-22). Adds proposal_type +
action_params to exchange_proposals so a proposal can carry an on-chain action (e.g. a
share dilution executed on pass). Additive + idempotent. Δ-neutral (shares ≠ money)."""
from alembic import op
from sqlalchemy import text

revision: str = "0101_exchange_proposal_action"
down_revision: str = "0100_exchange_vote_origin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    b = op.get_bind()
    b.execute(text("ALTER TABLE exchange_proposals ADD COLUMN IF NOT EXISTS proposal_type VARCHAR(16) NOT NULL DEFAULT 'advisory'"))
    b.execute(text("ALTER TABLE exchange_proposals ADD COLUMN IF NOT EXISTS action_params JSON"))


def downgrade() -> None:
    b = op.get_bind()
    b.execute(text("ALTER TABLE exchange_proposals DROP COLUMN IF EXISTS action_params"))
    b.execute(text("ALTER TABLE exchange_proposals DROP COLUMN IF EXISTS proposal_type"))
