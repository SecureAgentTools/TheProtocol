"""V0667 D5 (order gwo_d238dcda72add8e05b6d657b): the fast lane, an organization's own content changed after its line's ballot and our check.

  content_changes        one change of an organization's CONTENT on its code distribution (services/content_changes): its kind (a migration kit, a proxy spec,
                         a policy value, a console text, its branding), the target, the content, our checker's verdict, the ballot's rule, end and result, and,
                         once applied, the before and after, the time, and the one-step undo
  content_change_votes   one decider's vote on one content change (one per developer, never changed)

D5b adds to content_changes the room a change is announced in (announce_conversation_id, announce_message_id, announce_state): its live card and its state lines.

Additive: two new tables, nothing else is touched. Rolling back drops them (the applied content they recorded stays in the organization's space: the
undo is the change's own step, not the migration's). The two-step rule applies: downgrade first from an image that has it, then the older image.

Revision ID: 0236_content_changes
Revises: 0235_code_passport
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0236_content_changes"
down_revision = "0235_code_passport"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "content_changes",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("code_distribution_id", sa.String(40), sa.ForeignKey("code_distributions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("organization_id", sa.String(), sa.ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("target", sa.String(200), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("problem", sa.Text(), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("checker", postgresql.JSONB(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="balloting"),
        sa.Column("proposer_did", sa.String(200), nullable=False),
        sa.Column("proposer_developer_id", sa.Integer(), nullable=False),
        sa.Column("ballot_rule", postgresql.JSONB(), nullable=False),
        sa.Column("ballot_ends", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ballot_result", postgresql.JSONB(), nullable=True),
        sa.Column("before", postgresql.JSONB(), nullable=True),
        sa.Column("after", postgresql.JSONB(), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("apply_error", sa.String(500), nullable=True),
        sa.Column("undone", postgresql.JSONB(), nullable=True),
        sa.Column("announce_conversation_id", sa.String(36), sa.ForeignKey("conversations.id", ondelete="SET NULL", name="fk_content_changes_announce_conversation_id"),
                  nullable=True),
        sa.Column("announce_message_id", sa.String(36), nullable=True),
        sa.Column("announce_state", sa.String(16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('kit', 'proxy_spec', 'policy_value', 'console_text', 'branding', 'compliance_pack')", name="ck_content_changes_kind"),
        sa.CheckConstraint("state IN ('balloting', 'failed', 'apply_failed', 'applied', 'undone', 'withdrawn')", name="ck_content_changes_state"),
        sa.CheckConstraint("announce_state IS NULL OR announce_state IN ('balloting', 'failed', 'apply_failed', 'applied', 'undone', 'withdrawn')",
                           name="ck_content_changes_announce_state"),
    )
    op.create_index("ix_content_changes_code_distribution_id", "content_changes", ["code_distribution_id"])
    op.create_index("ix_content_changes_organization_id", "content_changes", ["organization_id"])
    op.create_index("ix_content_changes_state", "content_changes", ["state"])
    op.create_table(
        "content_change_votes",
        sa.Column("content_change_id", sa.String(40), sa.ForeignKey("content_changes.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("developer_id", sa.Integer(), primary_key=True),
        sa.Column("vote", sa.Boolean(), nullable=False),
        sa.Column("agent_did", sa.String(200), nullable=False),
        sa.Column("cast_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("content_change_votes")
    op.drop_index("ix_content_changes_state", table_name="content_changes")
    op.drop_index("ix_content_changes_organization_id", table_name="content_changes")
    op.drop_index("ix_content_changes_code_distribution_id", table_name="content_changes")
    op.drop_table("content_changes")
