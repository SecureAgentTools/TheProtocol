"""§LEDGERGATE (V0599, 2026-10-11) — an account deletion's forfeiture that moved no money is OWED, not stranded.

Found reading the gate's callers (FINDINGS_2026-10-11_TEG_NONNEGATIVE_AND_OUTBOX_GATE.md §9 S3): the anonymization drains
each agent's liquid balance to the treasury BEST-EFFORT (the GDPR clock must not stall on the TEG), and a drain that
failed left the balance on the revoked agent with nothing to retry it (background_tasks/account_deletion_worker:
"a forfeiture that moved no money leaves a balance stranded on a revoked agent, and nothing retries it"). The ledger gate
(the TEG refusing new value movements while its ledger cannot record them) makes an outage a common cause. Now the
anonymization writes the forfeiture it could not make into forfeitures_owed IN ITS OWN TRANSACTION, and
background_tasks/forfeiture_retry drains it with the deletion's own key once the ledger records again.

ONE table, nothing else touched. The id is the forfeiture's key (acctdel-forfeit-<deletion>-<agent>), one row per
forfeiture. The partial index is the worker's whole question: what is owed and due.

Rolling back past this is the two-step rule (downgrade first from an image that has it, then the older image); an open
row at a downgrade is a balance still on a revoked agent: drain it by hand (treasury receive with the row's id as the
Idempotency-Key) before dropping the table, or leave it to money_verify's stranded report.

Revision ID: 0190_forfeiture_owed
Revises: 0189_fiat_credit_owed
"""
from alembic import op
import sqlalchemy as sa

revision = "0190_forfeiture_owed"
down_revision = "0189_fiat_credit_owed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "forfeitures_owed",
        sa.Column("id", sa.String(length=320), primary_key=True),
        sa.Column("agent_did", sa.String(length=255), nullable=False),
        sa.Column("developer_id", sa.Integer(), nullable=True),
        sa.Column("deletion_id", sa.String(length=36), nullable=False),
        sa.Column("amount", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dead_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_forfeitures_owed_due", "forfeitures_owed", ["next_attempt_at"],
        postgresql_where=sa.text("done_at IS NULL AND dead_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_forfeitures_owed_due", table_name="forfeitures_owed")
    op.drop_table("forfeitures_owed")
