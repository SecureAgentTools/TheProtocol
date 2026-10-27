"""S3 — bind a federation peer to its SPIFFE identity.

`require_peer_registry_identity` has only ever been a SHAPE check: any SVID whose
path contains `/service/registry-` or `/operator/` passed, with no link to a
specific ACTIVE `peer_registries` row. Batch-1 added the revoked-license bite for
operator-shaped identities; this adds the column that lets the gate bind the
identity to an actual peer.

Additive and nullable: existing rows carry NULL and keep working (the gate treats
an unstamped fleet as legacy mode and only warns). Enforcement is a separate,
Commander-scheduled flip via FEDERATION_REQUIRE_PEER_SPIFFE_BIND.

Revision ID: 0127_peer_spiffe_bind
Revises: 0126_oauth_federation
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0127_peer_spiffe_bind"
down_revision: str = "0126_oauth_federation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "peer_registries",
        sa.Column("spiffe_id", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "ix_peer_registries_spiffe_id", "peer_registries", ["spiffe_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_peer_registries_spiffe_id", table_name="peer_registries")
    op.drop_column("peer_registries", "spiffe_id")
