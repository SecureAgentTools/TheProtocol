"""V0664 "Migrate a system", M4 (order gwo_e97a483512cfaf2151f17b7a): the template library (services/workflow_templates).

  workflow_templates           a template: its listing, owner, visibility, pricing, the share its author takes of each
                               sale of a fork of it, its lineage and its current published version
  workflow_template_versions   immutable once published: the manifest and the kit's files, their content hash
  workflow_template_purchases  one per buyer and template, recorded pending BEFORE its deposit (price, share, currency,
                               the two payees) and done after its payouts: a retry pays what the record says
                               (session-lead, room seq 3873)
  workflow_template_uses       kit downloads, instantiations and certified runs (one certified run per agent; the
                               listing counts distinct developers)
  agent_workflows              three provenance columns for a workflow started from a template

The closed words carry CHECKs (a new word needs a migration widening them). Additive; rolling back drops the columns and
the tables. The two-step rule applies (downgrade first from an image that has it, then the older image).

The chain at the V0664 cut (session-lead orders it): 0226 (session-code), 0227 (announcements), then this one. On its
own branch it revised 0225, the head of its base, so the branch's graph stayed one head; the cut re-pointed it at 0227.

Revision ID: 0228_workflow_templates
Revises: 0227_broadcast_public
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0228_workflow_templates"
down_revision = "0227_broadcast_public"   # re-pointed at the V0664 cut (was 0225)
branch_labels = None
depends_on = None

# event_type: (emit_from_registry, emit_from_teg, skip_in_projection), as 0196_emission_policy_catalog: a purchase is
# emitted by the registry as ContractTemplatePurchased is; its escrow legs emit the balance events themselves
EMISSION_POLICY_ROWS = {
    "WorkflowTemplatePurchased": (True, False, False),
}
_POLICY_DESCRIPTION = "V0664 M4: a workflow template purchase (registry-emitted, as ContractTemplatePurchased)"


def upgrade() -> None:
    op.create_table(
        "workflow_templates",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("summary", sa.String(500), nullable=True),
        sa.Column("kind", sa.String(20), nullable=False, server_default="migration"),
        sa.Column("from_kind", sa.String(20), nullable=True),
        sa.Column("to_kind", sa.String(20), nullable=True),
        sa.Column("owner_agent_did", sa.String(120), nullable=False),
        sa.Column("source_org_id", sa.String(64), nullable=True),
        sa.Column("visibility", sa.String(12), nullable=False, server_default="private"),
        sa.Column("pricing_model", sa.String(12), nullable=False, server_default="free"),
        sa.Column("price", sa.Numeric(38, 10), nullable=True),
        sa.Column("price_currency", sa.String(12), nullable=True),
        sa.Column("fork_share_bps", sa.Integer(), nullable=False, server_default="2000"),
        sa.Column("forked_from_template_id", sa.String(32), nullable=True),
        sa.Column("forked_from_version", sa.Integer(), nullable=True),
        sa.Column("current_version_id", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("owner_agent_did", "slug", name="uq_wtpl_owner_slug"),
        sa.CheckConstraint("kind IN ('migration', 'workflow')", name="ck_wtpl_kind"),
        sa.CheckConstraint("visibility IN ('private', 'org', 'unlisted', 'public')", name="ck_wtpl_visibility"),
        sa.CheckConstraint("pricing_model IN ('free', 'purchase')", name="ck_wtpl_pricing"),
        sa.CheckConstraint("fork_share_bps BETWEEN 0 AND 5000", name="ck_wtpl_fork_share"),
        sa.CheckConstraint("pricing_model = 'free' OR price > 0", name="ck_wtpl_price"),
    )
    op.create_index("ix_wtpl_owner", "workflow_templates", ["owner_agent_did"])
    op.create_index("ix_wtpl_public", "workflow_templates", ["visibility", "kind", "from_kind", "to_kind"])
    op.create_index("ix_wtpl_forked_from", "workflow_templates", ["forked_from_template_id"])

    op.create_table(
        "workflow_template_versions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("template_id", sa.String(32), sa.ForeignKey("workflow_templates.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("manifest", postgresql.JSONB(), nullable=False),
        sa.Column("files", postgresql.JSONB(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("changelog", sa.String(500), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("template_id", "version", name="uq_wtpv_template_version"),
    )

    op.create_table(
        "workflow_template_purchases",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("template_id", sa.String(32), sa.ForeignKey("workflow_templates.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("buyer_did", sa.String(120), nullable=False),
        sa.Column("price", sa.Numeric(38, 10), nullable=False),
        sa.Column("share", sa.Numeric(38, 10), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(12), nullable=True),
        sa.Column("author_did", sa.String(120), nullable=False),
        sa.Column("parent_did", sa.String(120), nullable=True),
        sa.Column("status", sa.String(8), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("template_id", "buyer_did", name="uq_wtpl_purchase"),
        sa.CheckConstraint("status IN ('pending', 'done')", name="ck_wtpl_purchase_status"),
        sa.CheckConstraint("price > 0 AND share >= 0 AND share <= price", name="ck_wtpl_purchase_amounts"),
        sa.CheckConstraint("share = 0 OR parent_did IS NOT NULL", name="ck_wtpl_purchase_parent"),
    )

    op.create_table(
        "workflow_template_uses",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("template_id", sa.String(32), sa.ForeignKey("workflow_templates.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("version", sa.Integer(), nullable=True),
        sa.Column("agent_did", sa.String(120), nullable=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("reference", sa.String(120), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('kit', 'instantiate', 'certified')", name="ck_wtpl_use_kind"),
    )
    op.create_index("ix_wtpl_uses_template_kind", "workflow_template_uses", ["template_id", "kind"])
    # a certified run counts once per template and agent (session-lead, room seq 3755)
    op.create_index("uq_wtpl_uses_certified", "workflow_template_uses", ["template_id", "agent_did"], unique=True,
                    postgresql_where=sa.text("kind = 'certified'"))

    op.add_column("agent_workflows", sa.Column("template_id", sa.String(32), nullable=True))
    op.add_column("agent_workflows", sa.Column("template_version", sa.Integer(), nullable=True))
    op.add_column("agent_workflows", sa.Column("template_content_hash", sa.String(64), nullable=True))
    conn = op.get_bind()
    for event_type, (reg, teg, skip) in EMISSION_POLICY_ROWS.items():
        conn.execute(
            sa.text("INSERT INTO event_emission_policies (event_type, emit_from_registry, emit_from_teg, skip_in_projection, "
                    "description) VALUES (:et, :reg, :teg, :skip, :d) ON CONFLICT (event_type) DO NOTHING"),
            {"et": event_type, "reg": reg, "teg": teg, "skip": skip, "d": _POLICY_DESCRIPTION})


def downgrade() -> None:
    conn = op.get_bind()
    for event_type, (reg, teg, skip) in EMISSION_POLICY_ROWS.items():
        conn.execute(
            sa.text("DELETE FROM event_emission_policies WHERE event_type = :et AND description = :d"),
            {"et": event_type, "d": _POLICY_DESCRIPTION})
    op.drop_column("agent_workflows", "template_content_hash")
    op.drop_column("agent_workflows", "template_version")
    op.drop_column("agent_workflows", "template_id")
    op.drop_index("uq_wtpl_uses_certified", table_name="workflow_template_uses")
    op.drop_index("ix_wtpl_uses_template_kind", table_name="workflow_template_uses")
    op.drop_table("workflow_template_uses")
    op.drop_table("workflow_template_purchases")
    op.drop_table("workflow_template_versions")
    op.drop_index("ix_wtpl_forked_from", table_name="workflow_templates")
    op.drop_index("ix_wtpl_public", table_name="workflow_templates")
    op.drop_index("ix_wtpl_owner", table_name="workflow_templates")
    op.drop_table("workflow_templates")
