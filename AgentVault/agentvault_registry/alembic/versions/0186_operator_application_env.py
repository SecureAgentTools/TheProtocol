"""§FESUITE V0595 (2026-10-11, his word "we need env setup in the application forms"): an operator application keeps the
configuration its applicant chose.

operator_applications gains env_choices (JSONB, '{}' by default): the catalog keys an applicant chose
(services/env_catalog.py, operator-scope only; the route refuses the frame's), which the provisioner writes into the
operator's env after its inherited posture. Adds only; existing rows read '{}' (nothing chosen, everything inherited);
the downgrade drops the column.
"""
from alembic import op

revision = "0186_operator_application_env"
down_revision = "0185_proposal_tally_record"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE operator_applications ADD COLUMN IF NOT EXISTS env_choices JSONB NOT NULL DEFAULT '{}'::jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE operator_applications DROP COLUMN IF EXISTS env_choices")
