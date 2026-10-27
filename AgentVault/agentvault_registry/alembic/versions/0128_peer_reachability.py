"""Federation reachability tracking — make "never answered" a visible state.

frame-c federated with only 6 of 16 peers for seven weeks and every surface reported
healthy, because a peer that has NEVER synced is indistinguishable from a working one:
`status=ACTIVE`, `health_check_failure_count=0`, and the revival prober only revives rows
already marked INACTIVE. `last_synced_at` existed but nothing compared it to anything.

These three columns let the fan-out record what it already computes, so reachability can be
reported as a compliance dimension with a real diagnosis instead of a bare 401 in a log.

Additive and nullable; `consecutive_sync_failures` defaults to 0 so existing rows read as
"no failures recorded yet" rather than as failures.

Revision ID: 0128_peer_reachability
Revises: 0127_peer_spiffe_bind
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0128_peer_reachability"
down_revision: str = "0127_peer_spiffe_bind"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "peer_registries",
        sa.Column("last_sync_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "peer_registries",
        sa.Column("last_sync_error", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "peer_registries",
        sa.Column(
            "consecutive_sync_failures",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("peer_registries", "consecutive_sync_failures")
    op.drop_column("peer_registries", "last_sync_error")
    op.drop_column("peer_registries", "last_sync_attempt_at")
