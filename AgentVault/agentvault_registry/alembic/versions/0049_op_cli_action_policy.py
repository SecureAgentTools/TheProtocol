"""Event emission policy row for OperatorCliAction (BL-1 P8, 2026-05-11).

Revision ID: 0049_op_cli_action_policy
Revises: 0048_fed_license_rotate

Adds an explicit event_emission_policies row for OperatorCliAction so it
emits from registry only + skip_in_projection=true (audit-only, never
balance-affecting). Default emission policy is permissive, but being explicit
here makes the audit trail's intent visible in the policy table.

Raw SQL + ON CONFLICT DO NOTHING for idempotency (per
feedback_migration_use_raw_sql_if_not_exists.md).

Revision-id length: 24 chars (alembic_version.version_num is varchar(32)).
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0049_op_cli_action_policy"
down_revision: Union[str, None] = "0048_fed_license_rotate"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The event_emission_policies table predates this migration; we only
    # INSERT a row. ON CONFLICT DO NOTHING so re-running is safe.
    op.execute("""
        INSERT INTO event_emission_policies (
            event_type, emit_from_teg, emit_from_registry, skip_in_projection
        ) VALUES (
            'OperatorCliAction', false, true, true
        )
        ON CONFLICT (event_type) DO UPDATE
          SET emit_from_teg = EXCLUDED.emit_from_teg,
              emit_from_registry = EXCLUDED.emit_from_registry,
              skip_in_projection = EXCLUDED.skip_in_projection
    """)


def downgrade() -> None:
    op.execute("DELETE FROM event_emission_policies WHERE event_type = 'OperatorCliAction'")
