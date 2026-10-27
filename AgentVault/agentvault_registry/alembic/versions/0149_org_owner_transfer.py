"""E1a (org adoption) — pending ownership-transfer state on organizations.

Ownership moves via a two-party handshake (owner initiates, target admin accepts),
never a role edit — these two nullable columns hold the single pending offer.
History is NOT kept here: every initiate/accept/decline/cancel emits an org
aggregate event, and the A6 audit tab reads the EventStore.

Additive only. Revision ID: 0149_org_owner_transfer
Revises: 0148_spend_caveats
"""
from alembic import op
import sqlalchemy as sa

revision = "0149_org_owner_transfer"
down_revision = "0148_spend_caveats"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("organizations",
                  sa.Column("pending_owner_id", sa.Integer,
                            sa.ForeignKey("developers.id"), nullable=True))
    op.add_column("organizations",
                  sa.Column("pending_owner_expires_at",
                            sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("organizations", "pending_owner_expires_at")
    op.drop_column("organizations", "pending_owner_id")
