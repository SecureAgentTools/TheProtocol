"""§MEMBERSHIP phase D2 (2026-10-02): the link from a local member vote to the federation proposal it decides.

governance_proposals.federation_ref = "<host trust domain>/<federation proposal id>" on a local proposal of type
`federation_ballot` (opened by POST /api/v1/admin/federation/ballots/local-vote): its members' result becomes this
registry's ONE ballot in that federation proposal. NULL on every other proposal. Adds only; the downgrade drops it.
"""
from alembic import op

revision = "0184_federation_ballot_ref"
down_revision = "0183_commons_seasons"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE governance_proposals ADD COLUMN IF NOT EXISTS federation_ref VARCHAR(200) NULL")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_governance_proposals_federation_ref "
               "ON governance_proposals (federation_ref) WHERE federation_ref IS NOT NULL")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_governance_proposals_federation_ref")
    op.execute("ALTER TABLE governance_proposals DROP COLUMN IF EXISTS federation_ref")
