"""FLARESHOP (2026-08-16) — cosmetic flares purchasable in the frame's own currency.

The fiat on-ramp is off on every frame today, which left the cosmetic flares
(and with shadow_chancellor, the 37 encirclement variants + 21 broken-machine
overlays) with no way to reach anyone. This table records the local-currency
lane: one row per purchase, written `pending` BEFORE the money moves so a crash
between the debit and the grant is re-drivable, then `completed` with the TEG
transaction id.

Deliberately NOT reusing fiat_purchases: that table's amount_eur feeds the
cumulative Shadow Chancellor evaluation, the Founders Wall and Stripe
reconciliation. A local-currency purchase must be invisible to all three.

Additive only. Revision ID: 0151_flare_shop
Revises: 0150_regulatory_auth
"""
from alembic import op
import sqlalchemy as sa

revision = "0151_flare_shop"
down_revision = "0150_regulatory_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "flare_shop_purchases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("developer_id", sa.Integer, sa.ForeignKey("developers.id"), nullable=False),
        sa.Column("buyer_agent_did", sa.String(255), nullable=False),
        sa.Column("target_agent_did", sa.String(255), nullable=True),
        sa.Column("tier", sa.String(32), nullable=False),
        sa.Column("price", sa.Numeric(30, 6), nullable=False),
        sa.Column("currency", sa.String(16), nullable=False),
        sa.Column("teg_tx_id", sa.String(128), nullable=True),
        sa.Column("status", sa.String(12), nullable=False, server_default="pending"),
        sa.Column("failure_reason", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_flareshop_dev_status", "flare_shop_purchases", ["developer_id", "status"])
    op.create_index("ix_flareshop_buyer", "flare_shop_purchases", ["buyer_agent_did"])


def downgrade() -> None:
    op.drop_index("ix_flareshop_buyer", table_name="flare_shop_purchases")
    op.drop_index("ix_flareshop_dev_status", table_name="flare_shop_purchases")
    op.drop_table("flare_shop_purchases")
