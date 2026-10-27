"""local_trust_scores.tx_volume: BigInteger -> Numeric(36, 18)

§VITALS 2026-09-04, the sibling of mig 0170, verified before it was written.

WHAT WAS VERIFIED, on 24h of real registry-a traffic (4,668 TokensTransferred
events read from the live EventStore, `scratchpad/vitals/prove_trust_truncation.py`):

    transfers with a fractional part : 3,412  (73.1%)
    transfers stored as ZERO         : 2,661  (57.0%)
    senders active but scoring vol=0 : 19 of 29
    true volume                      : 17,158.33
    volume as int(float(amount))     : 16,166
    ERASED                           :    992.33  (5.8%)

TWO LAYERS, and the column alone is not the defect
--------------------------------------------------
`routers/teg_integration.py::_record_transfer_ancillary` did
`amount_int = int(float(transfer_amount))` — Python truncation toward zero — BEFORE
the DB ever saw the value, and the column was BIGINT so it could not have held a
fraction anyway. Migrating the column without fixing the call site would change
nothing; both move together in this batch.

WHY IT MATTERS
--------------
`services/eigentrust_engine.py` Step 8 weights the global trust vector by volume
(`vol ** VOLUME_WEIGHT_EXP`, :208) and projects the result into
`Agent.reputation_score`. An agent transacting only sub-unit amounts scored
`vol = 0` and therefore kept the DEFAULT weight of 1.0, so 19 of 29 active senders
were systematically down-weighted against the 10 that happened to move whole units
— regardless of the value they actually moved. `routers/reputation_trust.py` reports
the same column as an agent's volume, rank and average per peer.

NOT the same as mig 0170: that one fed a money CONTROL (the IRONKEY spend cap).
This one feeds a reputation SIGNAL. Both are load-bearing; only 0170 could refuse
a payment.
"""
from alembic import op
import sqlalchemy as sa

revision = "0171_local_trust_volume_numeric"
down_revision = "0170_velocity_volume_numeric"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Widening only: every existing BIGINT value is representable exactly, so the
    # USING cast cannot fail or lose data. 5,937 rows on registry-a at the time of
    # writing — a rewrite measured in milliseconds.
    op.alter_column(
        "local_trust_scores",
        "tx_volume",
        existing_type=sa.BigInteger(),
        type_=sa.Numeric(36, 18),
        existing_nullable=False,
        existing_server_default=sa.text("0"),
        postgresql_using="tx_volume::numeric(36,18)",
        comment="Bilateral transfer volume for this pair. NUMERIC(36,18) since mig 0171 "
                "— as a BigInteger, with int(float(amount)) at the call site, 57% of real "
                "transfers stored as 0 and 19 of 29 active senders scored zero volume in "
                "the EigenTrust volume weighting.",
    )


def downgrade() -> None:
    # ⚠ LOSSY BY CONSTRUCTION: back to whole units, which is the defect this removes.
    op.alter_column(
        "local_trust_scores",
        "tx_volume",
        existing_type=sa.Numeric(36, 18),
        type_=sa.BigInteger(),
        existing_nullable=False,
        existing_server_default=sa.text("0"),
        postgresql_using="tx_volume::bigint",
    )
