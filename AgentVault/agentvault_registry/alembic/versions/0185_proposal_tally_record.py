"""§MEMBERSHIP (2026-10-02): a decided proposal keeps the numbers it was decided on.

governance_proposals gains the tally-time record a real tally writes: tally_weight_mode ('lock' | 'member', the unit of
the two numbers, since a registry may switch modes later), tally_network_power (veToken power or members' points),
tally_quorum_required (quorum_percent of it), tally_quorum_met and tallied_at. NULL on proposals tallied before this and on
open ones. Adds only; the downgrade drops the five columns.
"""
from alembic import op

revision = "0185_proposal_tally_record"
down_revision = "0184_federation_ballot_ref"
branch_labels = None
depends_on = None

_COLUMNS = (
    ("tally_weight_mode", "VARCHAR(10)"),
    ("tally_network_power", "DOUBLE PRECISION"),
    ("tally_quorum_required", "DOUBLE PRECISION"),
    ("tally_quorum_met", "BOOLEAN"),
    ("tallied_at", "TIMESTAMP WITH TIME ZONE"),
)


def upgrade() -> None:
    for name, kind in _COLUMNS:
        op.execute(f"ALTER TABLE governance_proposals ADD COLUMN IF NOT EXISTS {name} {kind} NULL")


def downgrade() -> None:
    for name, _kind in reversed(_COLUMNS):
        op.execute(f"ALTER TABLE governance_proposals DROP COLUMN IF EXISTS {name}")
