"""V0666 D1, code distributions (order gwo_f1c05b131b9208a94074beae; design sessionlogs2026/DESIGN_2026-11-15_DISTRIBUTIONS.md
and its D1 note): an organization's release line on top of our release, its deciders' own ballot.

  code_distributions        one per line: the organization, a slug (unique on the frame; the release name is
                            <base_release>_<slug>), a title, its base release, its open paths (a subset of the platform's,
                            checked in code), the team whose leads decide (RESTRICT: a team a line names is not deleted),
                            quorum 50-100 and the pass rule, the state with the pause's reason and who paused it.
  code_distribution_votes   one decider's vote on one change: PRIMARY KEY (change, developer), never changed.
  code_changes              code_distribution_id (NULL = the main line), ballot_rule (the line's rule as at the ballot's
                            open), ballot_ends, ballot_result (written once at close), org_go (the organization owner's go
                            and veto record; the platform maintainer's stay in go and veto).

Every closed word carries a CHECK (a new value needs a migration widening it). No value moves anywhere: no balance, no
TEG. Additive; rolling back drops the columns and the two tables (the lines and their votes go with them). The two-step
rule applies: downgrade first from an image that has it, then the older image.

Revision ID: 0231_code_distributions
Revises: 0230_contributor_track
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0231_code_distributions"
down_revision = "0230_contributor_track"
branch_labels = None
depends_on = None

CHECKS = {
    "ck_code_distributions_slug": "slug ~ '^[a-z][a-z0-9-]{1,39}$'",
    "ck_code_distributions_base_release": "base_release ~ '^V[0-9]{4}$'",
    "ck_code_distributions_quorum": "quorum_percent BETWEEN 50 AND 100",
    "ck_code_distributions_pass_rule": "pass_rule IN ('simple')",
    "ck_code_distributions_state": "state IN ('active', 'paused')",
    "ck_code_distributions_paused_says_why": ("state = 'active' OR (paused_reason IS NOT NULL AND "
                                             "paused_by_developer_id IS NOT NULL)"),
}


def upgrade() -> None:
    op.create_table(
        "code_distributions",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("organization_id", sa.String, sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("slug", sa.String(40), nullable=False, unique=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("base_release", sa.String(8), nullable=False),
        sa.Column("open_paths", JSONB, nullable=False),
        sa.Column("decider_team_id", sa.String, sa.ForeignKey("teams.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("quorum_percent", sa.Integer, nullable=False, server_default="50"),
        sa.Column("pass_rule", sa.String(12), nullable=False, server_default="simple"),
        sa.Column("state", sa.String(10), nullable=False, server_default="active"),
        sa.Column("paused_reason", sa.String(500), nullable=True),
        sa.Column("paused_by_developer_id", sa.Integer, nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_developer_id", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        *[sa.CheckConstraint(sql, name=name) for name, sql in CHECKS.items()],
    )
    op.create_index("ix_code_distributions_organization_id", "code_distributions", ["organization_id"])
    op.add_column("code_changes", sa.Column("code_distribution_id", sa.String(40),
                                            sa.ForeignKey("code_distributions.id", ondelete="RESTRICT"), nullable=True))
    op.create_index("ix_code_changes_code_distribution_id", "code_changes", ["code_distribution_id"])
    op.add_column("code_changes", sa.Column("ballot_rule", JSONB, nullable=True))
    op.add_column("code_changes", sa.Column("ballot_ends", sa.DateTime(timezone=True), nullable=True))
    op.add_column("code_changes", sa.Column("ballot_result", JSONB, nullable=True))
    op.add_column("code_changes", sa.Column("org_go", JSONB, nullable=True))
    op.create_table(
        "code_distribution_votes",
        sa.Column("code_change_id", sa.String(40), sa.ForeignKey("code_changes.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("developer_id", sa.Integer, primary_key=True),
        sa.Column("vote", sa.Boolean, nullable=False),
        sa.Column("agent_did", sa.String(200), nullable=False),
        sa.Column("cast_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("code_distribution_votes")
    op.drop_column("code_changes", "org_go")
    op.drop_column("code_changes", "ballot_result")
    op.drop_column("code_changes", "ballot_ends")
    op.drop_column("code_changes", "ballot_rule")
    op.drop_index("ix_code_changes_code_distribution_id", table_name="code_changes")
    op.drop_column("code_changes", "code_distribution_id")
    op.drop_index("ix_code_distributions_organization_id", table_name="code_distributions")
    op.drop_table("code_distributions")
