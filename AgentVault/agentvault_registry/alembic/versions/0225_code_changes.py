"""V0663 governed code, first slice: code_changes and code_change_reviews.

`code_changes`: a change to the code base proposed by a member's agent (repository, paths, problem; a bounty's Guild
order or a branch's commit), its acceptance record, the governance proposal that decides it (type code_change), the
maintainer's veto or go, and the merge recorded on the result (services/code_changes). `code_change_reviews`: one
reviewer's word on one commit. Additive; rolling back drops both tables (the routes then answer 500 for want of them,
so roll the image back first, then downgrade).

0225 was handed out for this order (0220-0224 belong to the workflows lane); at the V0663 cut it re-points onto the
lane's last, 0222_chat_fed_events (gwo_bf78f34918fddad4590f0bf3; 0223 and 0224 are not used in V0663).

Revision ID: 0225_code_changes
Revises: 0222_chat_fed_events
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0225_code_changes"
down_revision = "0222_chat_fed_events"   # re-pointed at the V0663 cut (was 0219)
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "code_changes",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("repository", sa.String(120), nullable=False),
        sa.Column("paths", postgresql.JSONB(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("problem", sa.Text(), nullable=False),
        sa.Column("mode", sa.String(10), nullable=False),
        sa.Column("branch", sa.String(200), nullable=True),
        sa.Column("commit", sa.String(64), nullable=True),
        sa.Column("order_id", sa.String(64), nullable=True),
        sa.Column("proposer_did", sa.String(200), nullable=False),
        sa.Column("proposer_developer_id", sa.Integer(), nullable=False),
        sa.Column("sensitive", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("state", sa.String(20), nullable=False, server_default="proposed"),
        sa.Column("acceptance", postgresql.JSONB(), nullable=True),
        sa.Column("proposal_id", sa.Integer(), nullable=True),
        sa.Column("passed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("veto", postgresql.JSONB(), nullable=True),
        sa.Column("go", postgresql.JSONB(), nullable=True),
        sa.Column("merged", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_code_changes_order_id", "code_changes", ["order_id"])
    op.create_index("ix_code_changes_state", "code_changes", ["state"])
    op.create_table(
        "code_change_reviews",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code_change_id", sa.String(40), sa.ForeignKey("code_changes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reviewer_developer_id", sa.Integer(), nullable=False),
        sa.Column("verdict", sa.String(10), nullable=False),
        sa.Column("commit", sa.String(64), nullable=False),
        sa.Column("findings", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_code_change_reviews_code_change_id", "code_change_reviews", ["code_change_id"])


def downgrade() -> None:
    op.drop_index("ix_code_change_reviews_code_change_id", table_name="code_change_reviews")
    op.drop_table("code_change_reviews")
    op.drop_index("ix_code_changes_state", table_name="code_changes")
    op.drop_index("ix_code_changes_order_id", table_name="code_changes")
    op.drop_table("code_changes")
