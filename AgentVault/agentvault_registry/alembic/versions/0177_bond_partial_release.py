"""§BONDFILL-3 (2026-09-11) — maturity unlocks capital instead of ending the business.

Before this, the ONLY right a matured bond conferred was `release()`, and release set
`is_bonded = false`, which under REPUTATION_BOND_MODE=enforce refuses the agent at all six
provider gates. The reward for proving yourself over thirty days was the right to stop trading.

His decision (2026-09-11): at maturity a DECLARED share of the bond comes back and the rest stays
locked, so the agent keeps trading with less capital tied up — how a surety bond's premium falls as
the record lengthens. The full `release()` is untouched and keeps its real meaning: an EXIT.

FOUR nullable columns, one migration. All nullable and no default, so the ALTER is metadata-only on
Postgres (no table rewrite, no lock held beyond the catalog update) and every existing row reads
"never unlocked", which is true.

    reputation_bonds.partial_released_amount            what came back at maturity
    reputation_bonds.partial_released_at                when (NULL = never; guards a second unlock)
    reputation_bonds.partial_release_ref                the idempotency ref, persisted BEFORE the
                                                        payout so a retry after a lost commit reuses it
    reputation_bonds.partial_release_teg_transaction_id the ledger transaction it rode on

`amount` keeps meaning what is HELD, so every reader of it — the slash waterfall, the six gates, the
card — stays correct without a change: a slash can reach exactly the collateral still at risk. The
original amount is `amount + partial_released_amount`, derived rather than stored twice.

⚠ A column added here lives in THREE places (§COCKPITA): this migration, the ORM model, and every
dict that assembles a row by hand. `bond_dict` is the one that matters for this table.

Revision ID: 0177_bond_partial_release
Revises: 0176_frame_licence_and_svc
"""
from alembic import op
import sqlalchemy as sa

revision = "0177_bond_partial_release"
down_revision = "0176_frame_licence_and_svc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reputation_bonds", sa.Column(
        "partial_released_amount", sa.Numeric(36, 18), nullable=True,
        comment="The share of the bond returned at maturity (§BONDFILL-3); NULL = never unlocked"))
    op.add_column("reputation_bonds", sa.Column(
        "partial_released_at", sa.DateTime(timezone=True), nullable=True,
        comment="When the maturity unlock was paid; NULL = never. Guards a second unlock"))
    op.add_column("reputation_bonds", sa.Column(
        "partial_release_ref", sa.String(160), nullable=True,
        comment="Idempotency ref of the unlock payout, persisted BEFORE the payout"))
    op.add_column("reputation_bonds", sa.Column(
        "partial_release_teg_transaction_id", sa.String(120), nullable=True,
        comment="The ledger transaction the unlock payout rode on"))


def downgrade() -> None:
    for col in ("partial_release_teg_transaction_id", "partial_release_ref",
                "partial_released_at", "partial_released_amount"):
        op.drop_column("reputation_bonds", col)
