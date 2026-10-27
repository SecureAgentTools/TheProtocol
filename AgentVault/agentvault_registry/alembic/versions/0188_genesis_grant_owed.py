"""§LEDGERGATE (V0598, 2026-10-11) — a first agent's genesis grant the TEG could not pay is OWED, not lost.

Found reading the gate's callers (FINDINGS_2026-10-11_TEG_NONNEGATIVE_AND_OUTBOX_GATE.md §9 S3): onboarding's
`mint_genesis_grant` turned any TEG failure into `initial_funding_status: failed` in the creation's answer, and nothing
retried it: no row, no worker. Any TEG hiccup already lost a developer's first grant for good; the ledger gate (the TEG
refusing new value movements while its ledger cannot record them) makes an outage a common cause. A row here is a grant
the creation could not pay; `background_tasks/genesis_grant_retry` pays it under leadership with the SAME idempotency key
the creation used (`genesis-{agent_did}`, so a retry can never pay twice), closes it with `granted_at`, and parks one
past its attempt budget with `dead_at` (kept, logged with the agent and the reason; never deleted).

ONE table, nothing else touched: no existing column, no data, no backfill. The agent's DID is the key: one grant per
agent at most. The partial index is the worker's whole question: what is due and still open.

Rolling back past this is the two-step rule (downgrade first from an image that has it, then the older image); an open
row at a downgrade is a grant a person is still owed: pay it by hand (FLOW 4) before dropping the table.

Revision ID: 0188_genesis_grant_owed
Revises: 0187_template_unit_prose
"""
from alembic import op
import sqlalchemy as sa

revision = "0188_genesis_grant_owed"
down_revision = "0187_template_unit_prose"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "genesis_grants_owed",
        sa.Column("agent_did", sa.String(length=255), primary_key=True),
        sa.Column("developer_id", sa.Integer(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("funding_status", sa.String(length=32), nullable=True),
        sa.Column("transaction_id", sa.String(length=255), nullable=True),
        sa.Column("dead_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_genesis_grants_owed_due", "genesis_grants_owed", ["next_attempt_at"],
        postgresql_where=sa.text("granted_at IS NULL AND dead_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_genesis_grants_owed_due", table_name="genesis_grants_owed")
    op.drop_table("genesis_grants_owed")
