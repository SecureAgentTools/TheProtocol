"""0100 — cross-frame AGORA shareholder voting: stamp the voter's home-frame on each
exchange vote (2026-06-22). Mirrors FederationVote.voter_registry_id — NULL = local
same-registry voter; set to the relaying peer's SPIFFE when a vote is relayed in from a
peer frame. Additive + idempotent. Δ-neutral (governance moves no money)."""
from alembic import op
from sqlalchemy import text

revision: str = "0100_exchange_vote_origin"
down_revision: str = "0099_exchange_proposals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(text(
        "ALTER TABLE exchange_proposal_votes ADD COLUMN IF NOT EXISTS voter_registry_id VARCHAR(255)"
    ))


def downgrade() -> None:
    op.get_bind().execute(text(
        "ALTER TABLE exchange_proposal_votes DROP COLUMN IF EXISTS voter_registry_id"
    ))
