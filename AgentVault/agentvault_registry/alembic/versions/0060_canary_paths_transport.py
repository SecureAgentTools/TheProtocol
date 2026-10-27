"""Add transport column to canary_paths + canary_test_results (§pass30 IRONHAND canary).

Revision ID: 0060_canary_paths_transport
Revises: 0059_saga_timeout_policies
Create Date: 2026-05-17

§pass30 — Pattern A IRONHAND mTLS canary.

Two schema changes:

1. canary_paths.transport — which transport the runner should use for this path.
   - 'bearer'         (default, existing behaviour)
   - 'federation_mtls' (legacy §15 flag-gated path using registry SVID)
   - 'ironhand_mtls'  (new Pattern A — per-agent SVID via Workload API workload container)

   NOT NULL, server_default='bearer' so existing 30 rows backfill seamlessly.

2. canary_test_results.transport — which transport the runner actually used on this fire.
   Nullable because pre-§pass30 rows pre-date the column.

   Closes a pre-existing gap: canary_runner.py was already setting result["transport"]
   in the dict but _record_fire never persisted it, leaving the admin event feed
   unable to filter by transport post-hoc.

Both indexes added so /admin/canary-judge + /admin/canary-ironhand filters scan fast.

Idempotent on retry: column-exists guards via inspector to allow re-runs in dev.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0060_canary_paths_transport"
down_revision: Union[str, None] = "0059_saga_timeout_policies"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # canary_paths.transport
    cp_cols = {c["name"] for c in inspector.get_columns("canary_paths")}
    if "transport" not in cp_cols:
        op.add_column(
            "canary_paths",
            sa.Column(
                "transport",
                sa.String(16),
                nullable=False,
                server_default="bearer",
            ),
        )
        op.create_check_constraint(
            "canary_paths_transport_check",
            "canary_paths",
            "transport IN ('bearer','federation_mtls','ironhand_mtls')",
        )
        op.create_index(
            "idx_canary_paths_transport",
            "canary_paths",
            ["transport"],
        )

    # canary_test_results.transport
    ctr_cols = {c["name"] for c in inspector.get_columns("canary_test_results")}
    if "transport" not in ctr_cols:
        op.add_column(
            "canary_test_results",
            sa.Column("transport", sa.String(32), nullable=True),
        )
        op.create_index(
            "idx_canary_test_results_transport",
            "canary_test_results",
            ["transport"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    ctr_cols = {c["name"] for c in inspector.get_columns("canary_test_results")}
    if "transport" in ctr_cols:
        op.drop_index("idx_canary_test_results_transport", "canary_test_results")
        op.drop_column("canary_test_results", "transport")

    cp_cols = {c["name"] for c in inspector.get_columns("canary_paths")}
    if "transport" in cp_cols:
        op.drop_index("idx_canary_paths_transport", "canary_paths")
        op.drop_constraint("canary_paths_transport_check", "canary_paths")
        op.drop_column("canary_paths", "transport")
