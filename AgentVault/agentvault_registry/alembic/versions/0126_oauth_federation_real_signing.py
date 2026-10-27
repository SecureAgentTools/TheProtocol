"""OAuth federation real signing + revocation (RA1/RA2/RA3).

Additive only, so it replays clean fleet-wide and is safe to leave in place on a
rollback:

* ``oauth_token_exchanges`` gains the columns an exchange record needs to be
  authoritative rather than decorative: who asked for it, what constraints were
  minted into the token, and whether it has since been revoked. Single-use was
  already expressible via the existing ``used_at``.
* ``registry_trust_config`` gains the two fields real verification needs: the
  ``issuer`` we must see in a peer's ``iss`` claim, and the per-peer
  ``max_amount`` ceiling that goes into the exchanged token's constraints.

Revision ID: 0126_oauth_federation
Revises: 0125_auth_lifecycle
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0126_oauth_federation"
down_revision: str = "0125_auth_lifecycle"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- oauth_token_exchanges: make the audit row authoritative ---
    op.add_column(
        "oauth_token_exchanges",
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "oauth_token_exchanges",
        sa.Column("revoked_reason", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "oauth_token_exchanges",
        sa.Column("client_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "oauth_token_exchanges",
        sa.Column("constraints", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    # --- registry_trust_config: what real verification needs ---
    op.add_column(
        "registry_trust_config",
        sa.Column("issuer", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "registry_trust_config",
        sa.Column("max_amount", sa.Numeric(precision=20, scale=6), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("registry_trust_config", "max_amount")
    op.drop_column("registry_trust_config", "issuer")
    op.drop_column("oauth_token_exchanges", "constraints")
    op.drop_column("oauth_token_exchanges", "client_id")
    op.drop_column("oauth_token_exchanges", "revoked_reason")
    op.drop_column("oauth_token_exchanges", "revoked_at")
