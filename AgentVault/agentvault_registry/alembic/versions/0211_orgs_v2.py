"""V0657 (b), session-code 2026-11-06: orgs v2, local (order gwo_526ffa9f951232f15adbaeb8; the discovery: room seq 1475,
orgs_v2_discovery_2026-11-06.md; the Commander's answer: room seq 1482).

`organization_logos`: an organization's logo, hosted by its own registry (item 3). The bytes live here and the registry
serves them from its own origin, so no viewer's browser calls a third party; a `logo_url` on another host is no longer
shown. One row per organization, replaced by the next upload, gone with the organization.

`agents.show_org`: the agent's (or its owner's) "show my org" (item 2). An agent's organization is stated on its card,
here and on every peer's mirror, only while the organization is listed (its setting `public_listing`) AND this is on.
On by default; the organization's listing is what starts the mark travelling.

`organization_agent_requests`: an agent asks to join an organization, or its owner proposes it, and an administrator
of the organization accepts or declines (polish 9). Assigning stays an act that needs the agent's owner: a request is
how a member brings an agent in without being an administrator, and how an administrator adds a member's agent.

Additive; rolling back drops the two tables and the column (the two-step rule as for every additive revision: downgrade
first from an image that has it, then the older image).

Revision ID: 0211_orgs_v2
Revises: 0210_disputes_v2
"""
from alembic import op
import sqlalchemy as sa

revision = "0211_orgs_v2"
down_revision = "0210_disputes_v2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "organization_logos",
        sa.Column("organization_id", sa.String(255), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("content_type", sa.String(32), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.add_column("agents", sa.Column("show_org", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_table(
        "organization_agent_requests",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("organization_id", sa.String(255), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("agent_did", sa.String(255), nullable=False),
        sa.Column("requested_by_kind", sa.String(16), nullable=False),
        sa.Column("requested_by_ref", sa.String(255), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by_kind", sa.String(16), nullable=True),
        sa.Column("decided_by_ref", sa.String(255), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
    )
    op.create_index("ix_org_agent_requests_org_status", "organization_agent_requests", ["organization_id", "status"])
    op.create_index("ix_org_agent_requests_agent", "organization_agent_requests", ["agent_did"])
    # one open request per agent and organization
    op.create_index("uq_org_agent_requests_pending", "organization_agent_requests", ["organization_id", "agent_did"],
                    unique=True, postgresql_where=sa.text("status = 'pending'"))


def downgrade():
    op.drop_index("uq_org_agent_requests_pending", table_name="organization_agent_requests")
    op.drop_index("ix_org_agent_requests_agent", table_name="organization_agent_requests")
    op.drop_index("ix_org_agent_requests_org_status", table_name="organization_agent_requests")
    op.drop_table("organization_agent_requests")
    op.drop_column("agents", "show_org")
    op.drop_table("organization_logos")
