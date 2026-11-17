"""V0667 the developer passport, step 1 (order gwo_fb84e57318de0802725ab511; sessionlogs2026/DESIGN_2026-11-16_DEVELOPER_PASSPORT.md):
a developer homed on another registry proposes and reviews on the governing registry through their home, with no account there.

  code_contributors          on the GOVERNING registry: one row per (home registry, home developer id), the person behind a relayed act.
                             No password, no sign-in; authority is re-derived from the home's signed card on every act. standing is
                             active or paused (a card saying the home suspended them pauses the row; a later active card restores it).
                             In the rail's developer columns (code_changes.proposer_developer_id, code_change_reviews.reviewer_developer_id)
                             a contributor is the NEGATIVE of its id (services/code_passport.contributor_key): those columns are plain
                             integers with no foreign key, so independence, the review count and the verifier read a contributor as one
                             more distinct identity, and a developer id is never negative.
  code_contributor_unlocks   the contributor track's unlocks of a contributor (cosmetic_unlocks.developer_id references developers, so a
                             contributor's cannot live there); the same columns and checks, written by the same one writer
                             (services/contributor_track.DbTrackStore).
  developers.code_passport_consent_at   on the HOME registry: when the developer pressed "Take part" (NULL: never, or taken back). Nothing
                             is relayed or disclosed without it.
  contributor_repo_accounts, contributor_repo_account_ops   phase 4 (session-lead seq 5367): a contributor's account on the public code
                             host and the legs of its standing, with 0234's rules (repo_accounts keys a developer row, so a
                             contributor's cannot live there); the account also keeps the Terms version accepted at the press.
  A contributor's standing is active, paused (the home says not in good standing) or closed (the home deleted them; never restored).

Revision ID: 0235_code_passport
Revises: 0234_repo_accounts
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0235_code_passport"
down_revision = "0234_repo_accounts"
branch_labels = None
depends_on = None

# a contributor's repository account keeps a member's rules (0234's checks, under its own names)
ACCOUNT_CHECKS = {
    "ck_contributor_repo_accounts_username": "username ~ '^[a-z0-9][a-z0-9-]{1,37}[a-z0-9]$'",
    "ck_contributor_repo_accounts_state": "state IN ('active', 'paused', 'closed')",
    "ck_contributor_repo_accounts_paused_records": "state <> 'paused' OR paused_before IS NOT NULL",
}
OP_CHECKS = {
    "ck_contributor_repo_account_ops_op": "op IN ('pause', 'restore', 'close')",
    "ck_contributor_repo_account_ops_status": "status IN ('pending', 'done')",
    "ck_contributor_repo_account_ops_attempts": "attempts >= 0",
    "ck_contributor_repo_account_ops_done_at": "status <> 'done' OR done_at IS NOT NULL",
}


def upgrade() -> None:
    op.create_table(
        "code_contributors",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("home_registry", sa.String(120), nullable=False),
        sa.Column("home_developer_id", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=True),
        sa.Column("agent_did", sa.String(200), nullable=True),
        sa.Column("standing", sa.String(16), nullable=False, server_default="active"),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_act_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("home_registry", "home_developer_id", name="uq_code_contributor_home"),
        sa.CheckConstraint("standing IN ('active', 'paused', 'closed')", name="ck_code_contributors_standing"),
        sa.CheckConstraint("(standing <> 'active') = (paused_at IS NOT NULL)", name="ck_code_contributors_paused_at"),
    )
    op.create_table(
        "code_contributor_unlocks",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("contributor_id", sa.Integer, sa.ForeignKey("code_contributors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("item_key", sa.String(64), nullable=False),
        sa.Column("tier", sa.Integer, nullable=True),
        sa.Column("unlocked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("source", sa.String(80), nullable=False),
        sa.UniqueConstraint("contributor_id", "kind", "item_key", name="uq_code_contributor_unlock"),
        sa.CheckConstraint("kind IN ('corner', 'encirclement', 'overlay', 'title')", name="ck_code_contributor_unlocks_kind"),
    )
    op.create_index("ix_code_contributor_unlocks_contributor_id", "code_contributor_unlocks", ["contributor_id"])
    op.add_column("developers", sa.Column("code_passport_consent_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "contributor_repo_accounts",
        sa.Column("contributor_id", sa.Integer(), sa.ForeignKey("code_contributors.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("username", sa.String(39), nullable=False, unique=True),
        sa.Column("host_user_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("state", sa.String(10), nullable=False, server_default="active"),
        sa.Column("paused_before", postgresql.JSONB(), nullable=True),
        sa.Column("terms_version", sa.String(16), nullable=True),
        sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        *[sa.CheckConstraint(expr, name=name) for name, expr in ACCOUNT_CHECKS.items()],
    )
    op.create_table(
        "contributor_repo_account_ops",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("contributor_id", sa.Integer(), sa.ForeignKey("contributor_repo_accounts.contributor_id", ondelete="RESTRICT"),
                  nullable=False),
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
    op.create_index("ix_contributor_repo_account_ops_pending", "contributor_repo_account_ops", ["status", "contributor_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_contributor_repo_account_ops_pending", table_name="contributor_repo_account_ops")
    op.drop_table("contributor_repo_account_ops")
    op.drop_table("contributor_repo_accounts")
    op.drop_column("developers", "code_passport_consent_at")
    op.drop_index("ix_code_contributor_unlocks_contributor_id", table_name="code_contributor_unlocks")
    op.drop_table("code_contributor_unlocks")
    op.drop_table("code_contributors")
