"""§FEDSYNCTRUTH (2026-09-03) — the pull-sync cursor: bookkeeping for every pull ATTEMPT, not only successes.

`agent_cards.last_pulled_at` is stamped only on a 200/304, so the worker's candidate order
(`last_pulled_at NULLS FIRST, created_at`) handed the SAME stalest 100 cards to every cycle: on every
node those 100 were internal hosts (skipped) or dead hostnames (4xx / connect errors), none of which
stamped anything, and the cursor never moved. Measured 2026-09-02: `last_pulled_at` NULL on 4,137 of
4,149 natives on registry-a and on every native on frame-b / frame-c / the ops, while the reachable
sovereigns behind them were never asked.

Three nullable columns, no data move:
  last_pull_attempt_at — when the worker last TRIED (any outcome) → the cursor;
  last_pull_status     — what happened ('200' | '304' | '4xx' | '5xx' | 'timeout' | 'error' | 'skipped');
  pull_failures        — consecutive failures → exponential backoff (a dead hostname is retried weekly,
                         a live card every cycle).

Revision ID: 0169_agent_card_pull_attempt
Revises: 0168_agent_health_seen
"""
from alembic import op
import sqlalchemy as sa

revision = "0169_agent_card_pull_attempt"
down_revision = "0168_agent_health_seen"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_cards", sa.Column("last_pull_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("agent_cards", sa.Column("last_pull_status", sa.String(16), nullable=True))
    op.add_column("agent_cards", sa.Column("pull_failures", sa.Integer(), nullable=False, server_default="0"))
    op.create_index("ix_agent_cards_last_pull_attempt_at", "agent_cards", ["last_pull_attempt_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_cards_last_pull_attempt_at", table_name="agent_cards")
    op.drop_column("agent_cards", "pull_failures")
    op.drop_column("agent_cards", "last_pull_status")
    op.drop_column("agent_cards", "last_pull_attempt_at")
