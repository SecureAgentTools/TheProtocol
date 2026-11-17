"""V0666 repository accounts on the public code host (order gwo_662c03447bcd627afa4a11e5; services/repo_accounts).

  repo_accounts       a developer's account on code.theprotocol.cloud, made only on the developer's own request: one per developer
                      (the key), one developer per username and per code host id (unique); its state (active, paused, closed) and,
                      while paused, the record of what the pause found (paused_before), which reinstatement writes back exactly
  repo_account_ops    one leg of the developer's standing there (pause, restore, close), written in the same transaction as the
                      suspension, reinstatement or deletion it follows, drained by background_tasks/repo_account_worker

Additive and empty at first; nothing reads them while REPO_ACCOUNTS_ENABLED is off. Rolling back drops both tables: downgrade from an
image that has this migration first, then roll the image back (the two-step rule).

Revision ID: 0234_repo_accounts
Revises: 0233_guild_orders_agent_org
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0234_repo_accounts"
down_revision = "0233_guild_orders_agent_org"
branch_labels = None
depends_on = None

ACCOUNT_CHECKS = {
    "ck_repo_accounts_username": "username ~ '^[a-z0-9][a-z0-9-]{1,37}[a-z0-9]$'",
    "ck_repo_accounts_state": "state IN ('active', 'paused', 'closed')",
    "ck_repo_accounts_paused_records": "state <> 'paused' OR paused_before IS NOT NULL",
}
OP_CHECKS = {
    "ck_repo_account_ops_op": "op IN ('pause', 'restore', 'close')",
    "ck_repo_account_ops_status": "status IN ('pending', 'done')",
    "ck_repo_account_ops_attempts": "attempts >= 0",
    "ck_repo_account_ops_done_at": "status <> 'done' OR done_at IS NOT NULL",
}


def upgrade() -> None:
    op.create_table(
        "repo_accounts",
        sa.Column("developer_id", sa.Integer(), sa.ForeignKey("developers.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("username", sa.String(39), nullable=False, unique=True),
        sa.Column("host_user_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("state", sa.String(10), nullable=False, server_default="active"),
        sa.Column("paused_before", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        *[sa.CheckConstraint(expr, name=name) for name, expr in ACCOUNT_CHECKS.items()],
    )
    op.create_table(
        "repo_account_ops",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("developer_id", sa.Integer(), sa.ForeignKey("repo_accounts.developer_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("op", sa.String(10), nullable=False),
        sa.Column("cause", sa.String(64), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        *[sa.CheckConstraint(expr, name=name) for name, expr in OP_CHECKS.items()],
    )
    op.create_index("ix_repo_account_ops_pending", "repo_account_ops", ["status", "developer_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_repo_account_ops_pending", table_name="repo_account_ops")
    op.drop_table("repo_account_ops")
    op.drop_table("repo_accounts")
