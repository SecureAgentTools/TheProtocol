"""§LEDGERGATE (V0599, 2026-10-11) — a paid fiat purchase whose credit did not land is OWED, not failed and forgotten.

Found reading the gate's callers (FINDINGS_2026-10-11_TEG_NONNEGATIVE_AND_OUTBOX_GATE.md §9 S3): fiat_onramp's direct flow
marked a purchase FAILED ("reward_fund_failed") whenever the TEG did not credit it, and the webhook had already answered
200 (it credits in a background task), so the provider never retries; only an admin replay recovered it, and that replay
carried no Idempotency-Key. The ledger gate (the TEG refusing new value movements while its ledger cannot record them)
makes an outage a common cause. Now the purchase stays `processing` with failure_reason "credit_owed: <why>" and
background_tasks/fiat_credit_retry credits it with the purchase's own key (fiat-credit-<id>) on a growing wait.

TWO columns on fiat_purchases, nothing else touched: `credit_attempts` (failed credit attempts) and
`credit_next_attempt_at` (when the worker asks again). The partial index is the worker's whole question: what is owed and
due on the direct flow.

Rolling back past this is the two-step rule (downgrade first from an image that has it, then the older image). The
downgrade hands every owed purchase to the older image's human path first: it becomes failed, "reward_fund_failed",
which the forensic scanner and the stuck-funds board name (an older image leaves a processing direct-flow row alone).

Revision ID: 0189_fiat_credit_owed
Revises: 0188_genesis_grant_owed
"""
from alembic import op
import sqlalchemy as sa

revision = "0189_fiat_credit_owed"
down_revision = "0188_genesis_grant_owed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fiat_purchases", sa.Column("credit_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("fiat_purchases", sa.Column("credit_next_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_fiat_purchases_credit_due", "fiat_purchases", ["credit_next_attempt_at"],
        postgresql_where=sa.text("status = 'processing' AND routed = false"),
    )


def downgrade() -> None:
    op.execute(
        "UPDATE fiat_purchases SET status = 'failed', failure_reason = 'reward_fund_failed' "
        "WHERE status = 'processing' AND routed = false AND failure_reason LIKE 'credit_owed:%'"
    )
    op.drop_index("ix_fiat_purchases_credit_due", table_name="fiat_purchases")
    op.drop_column("fiat_purchases", "credit_next_attempt_at")
    op.drop_column("fiat_purchases", "credit_attempts")
