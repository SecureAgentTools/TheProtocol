"""0099 — AGORA share-weighted shareholder governance (P3.1, 2026-06-21).

Creates exchange_proposals / exchange_proposal_holders / exchange_proposal_votes for
listing-level shareholder voting (power = shares held at a frozen snapshot, treasury
excluded). Δ-irrelevant (governance rows, no money). IDEMPOTENT — CREATE TABLE IF NOT
EXISTS (runs once via `alembic upgrade head`).
"""
from alembic import op
from sqlalchemy import text

revision: str = "0099_exchange_proposals"
down_revision: str = "0098_treasury_mm_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text(
        """
        CREATE TABLE IF NOT EXISTS exchange_proposals (
            id                  VARCHAR(36) PRIMARY KEY,
            listing_id          VARCHAR(36) NOT NULL REFERENCES exchange_listings(id),
            proposer_did        VARCHAR(120) NOT NULL,
            title               VARCHAR(255) NOT NULL,
            description         TEXT NOT NULL,
            status              VARCHAR(12) NOT NULL DEFAULT 'voting',
            quorum_pct          DOUBLE PRECISION NOT NULL DEFAULT 20.0,
            pass_pct            DOUBLE PRECISION NOT NULL DEFAULT 50.0,
            snapshot_seq        BIGINT NOT NULL DEFAULT 0,
            enfranchised_total  BIGINT NOT NULL DEFAULT 0,
            end_at              TIMESTAMPTZ NOT NULL,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    ))
    bind.execute(text(
        """
        CREATE TABLE IF NOT EXISTS exchange_proposal_holders (
            id            BIGSERIAL PRIMARY KEY,
            proposal_id   VARCHAR(36) NOT NULL REFERENCES exchange_proposals(id),
            agent_did     VARCHAR(120) NOT NULL,
            weight        BIGINT NOT NULL,
            CONSTRAINT uq_eph_proposal_agent UNIQUE (proposal_id, agent_did)
        )
        """
    ))
    bind.execute(text(
        """
        CREATE TABLE IF NOT EXISTS exchange_proposal_votes (
            id            BIGSERIAL PRIMARY KEY,
            proposal_id   VARCHAR(36) NOT NULL REFERENCES exchange_proposals(id),
            agent_did     VARCHAR(120) NOT NULL,
            vote          BOOLEAN NOT NULL,
            weight        BIGINT NOT NULL,
            reason        VARCHAR(255),
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_epv_proposal_agent UNIQUE (proposal_id, agent_did)
        )
        """
    ))
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_exchange_proposals_listing ON exchange_proposals(listing_id, status)"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("DROP TABLE IF EXISTS exchange_proposal_votes"))
    bind.execute(text("DROP TABLE IF EXISTS exchange_proposal_holders"))
    bind.execute(text("DROP TABLE IF EXISTS exchange_proposals"))
