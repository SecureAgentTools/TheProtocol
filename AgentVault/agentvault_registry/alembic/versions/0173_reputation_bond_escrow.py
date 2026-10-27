"""§REPBOND — the reputation bond becomes escrow-backed money, one row per agent.

Until now `reputation_bonds` recorded a bond that had NEVER moved a token: the
deposit route subtracted the amount from `agents.liquid_balance` (the registry's
CACHE of the TEG balance) and the next `eventstore_balance_sync` cycle wrote the
TEG truth back over it. `matured_at` / `forfeited_at` were never written and no
rail ever READ the bond (measured 2026-09-05: ONE row network-wide, 50 units,
`locked` since 2026-03-24, beside 15,443 active agents on registry-a). Numbered
R54 in the money inventory.

From here the bond is held by the TEG treasury under an idempotent escrow
reference (`services/reputation_bond.py`), so this table needs to say WHO funded
it, HOW, and with WHICH ledger transaction:

  amount          INTEGER → NUMERIC(36,18)  (the profile derives it from the grant,
                                             25 % of 1,000 is a whole number today
                                             and will not stay one)
  funder_did      the account the escrow deposit debited (self, or the owner's
                  wallet agent); NULL for a treasury backstop
  funded_by       self | wallet | treasury
  escrow_ref      the idempotency reference the deposit rode on (repbond-<did>)
  teg_transaction_id / release_teg_transaction_id
                  the ledger transactions of the deposit and of the release
  released_at     when a matured bond was paid back
  release_ref     the reference the release payout rode on

`status` stays a plain varchar; the value set widens to
  locked | matured | released | forfeited | voided.

DATA STEP, deliberate: every pre-existing `locked` row is set to `voided` and the
mirrored `agents.reputation_bond_*` columns are reset. Those rows never moved
money on ANY node (the deposit path was cache-only everywhere the image ran), so
there is nothing to return; leaving them `locked` would let a bond that holds
nothing pass the gate this batch introduces. The Commander's word on the old
50-unit bond: "if we replace we replace".

Applying this on a node whose image predates the feature widens a column, adds
nullable columns and voids rows nothing reads — no behaviour change. Two other
sessions share this tree and a committed migration rides into builds they make
(§VITALS): this one touches `reputation_bonds` and the two `agents.reputation_bond_*`
mirror columns, nothing else.

Downgrade is LOSSY by construction (NUMERIC → INTEGER rounds, the new columns
are dropped, voided rows stay voided).

Revision id is 27 chars (<= the 32-char varchar law).
"""
from alembic import op
import sqlalchemy as sa

revision = "0173_reputation_bond_escrow"
down_revision = "0172_frame_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "reputation_bonds", "amount",
        existing_type=sa.Integer(),
        type_=sa.Numeric(36, 18),
        existing_nullable=False,
        postgresql_using="amount::numeric(36,18)",
    )
    op.add_column("reputation_bonds", sa.Column("funder_did", sa.String(), nullable=True))
    op.add_column("reputation_bonds", sa.Column("funded_by", sa.String(16), nullable=True))
    op.add_column("reputation_bonds", sa.Column("escrow_ref", sa.String(160), nullable=True))
    op.add_column("reputation_bonds", sa.Column("teg_transaction_id", sa.String(120), nullable=True))
    op.add_column("reputation_bonds", sa.Column("release_ref", sa.String(160), nullable=True))
    op.add_column("reputation_bonds", sa.Column("release_teg_transaction_id", sa.String(120), nullable=True))
    op.add_column("reputation_bonds", sa.Column("released_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("reputation_bonds", sa.Column("forfeit_ref", sa.String(160), nullable=True))
    op.add_column("reputation_bonds", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))

    # The data step: pre-escrow rows hold nothing. Void them and reset the mirror.
    op.execute(
        "UPDATE reputation_bonds SET status = 'voided', forfeit_reason = 'pre-escrow bond voided by 0173', "
        "updated_at = NOW() WHERE escrow_ref IS NULL AND status IN ('locked', 'matured')"
    )
    op.execute(
        "UPDATE agents SET reputation_bond_status = 'none', reputation_bond_amount = 0 "
        "WHERE reputation_bond_status IN ('locked', 'matured') "
        "AND did IN (SELECT agent_did FROM reputation_bonds WHERE status = 'voided')"
    )


def downgrade() -> None:
    op.drop_column("reputation_bonds", "updated_at")
    op.drop_column("reputation_bonds", "forfeit_ref")
    op.drop_column("reputation_bonds", "released_at")
    op.drop_column("reputation_bonds", "release_teg_transaction_id")
    op.drop_column("reputation_bonds", "release_ref")
    op.drop_column("reputation_bonds", "teg_transaction_id")
    op.drop_column("reputation_bonds", "escrow_ref")
    op.drop_column("reputation_bonds", "funded_by")
    op.drop_column("reputation_bonds", "funder_did")
    op.alter_column(
        "reputation_bonds", "amount",
        existing_type=sa.Numeric(36, 18),
        type_=sa.Integer(),
        existing_nullable=False,
        postgresql_using="round(amount)::integer",
    )
