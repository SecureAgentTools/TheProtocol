"""velocity_metrics.tx_volume: BigInteger -> Numeric(36, 18)

§VITALS 2026-09-04. His word: "migration approved if you have fully verified its
needed. truncation is not good."

WHAT WAS VERIFIED, on live registry-a data
------------------------------------------
`velocity_metrics.tx_volume` was BIGINT, so a fractional hourly volume was ROUNDED
to a whole unit on the way in — half away from zero, so it both LOSES and
OVER-COUNTS:

    0.01 -> 0     0.1 -> 0     0.49 -> 0     0.5 -> 1     0.6 -> 1     1.5 -> 2

End-to-end on the same agent, same window, same run: the worker aggregated
`did:theprotocol:b8e328dd… count=10 volume=0.1000` from the live EventStore, and
the row it wrote reads `tx_count=10, tx_volume=0`.

WHY IT MATTERS
--------------
`agent_authz.check_spend_admission` (agent_authz.py:279) sums this column for the
IRONKEY rolling-24h `max_per_day` cap, and `max_per_day` is NUMERIC(36, 18). An
integer denominator against an 18-decimal ceiling means sub-unit spend is
invisible to the cap: a thousand 0.5-unit transfers can sum to 0. 17 policies on
registry-a carry a day cap. `routers/organizations.py:2346` sums the same column
for the org spend view.

NUMERIC(36, 18) is chosen to MATCH `agent_spend_policies.max_per_day` — the sum
and the ceiling it is compared against now live in the same domain.

NOT IN SCOPE: `local_trust_scores.tx_volume` is a DIFFERENT column of the same
name and shape (BIGINT, 5,937 rows, feeding EigenTrust + guild reputation + the
fee service's velocity index). It plausibly has the same defect but it was NOT
verified here, and its blast radius is reputation math. Named, not touched.
"""
from alembic import op
import sqlalchemy as sa

revision = "0170_velocity_volume_numeric"
down_revision = "0169_agent_card_pull_attempt"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Widening only: every existing BIGINT value is representable exactly, so the
    # USING cast cannot fail or lose data. The table is bounded by design (the
    # worker prunes rows older than 7 days), so the rewrite is small everywhere.
    op.alter_column(
        "velocity_metrics",
        "tx_volume",
        existing_type=sa.BigInteger(),
        type_=sa.Numeric(36, 18),
        existing_nullable=False,
        existing_server_default=sa.text("0"),
        postgresql_using="tx_volume::numeric(36,18)",
        comment="Total volume transferred in this window. NUMERIC(36,18) to match "
                "agent_spend_policies.max_per_day — an integer here rounded sub-unit "
                "spend away and made the IRONKEY rolling-24h cap unable to see it.",
    )


def downgrade() -> None:
    # ⚠ LOSSY BY CONSTRUCTION: going back to BIGINT re-introduces the rounding this
    # migration exists to remove. Kept only so the chain is reversible.
    op.alter_column(
        "velocity_metrics",
        "tx_volume",
        existing_type=sa.Numeric(36, 18),
        type_=sa.BigInteger(),
        existing_nullable=False,
        existing_server_default=sa.text("0"),
        postgresql_using="tx_volume::bigint",
    )
