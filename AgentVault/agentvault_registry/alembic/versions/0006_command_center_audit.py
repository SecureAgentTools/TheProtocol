"""Seed event_emission_policies for Command Center audit events.

Adds two audit-only event types used by /api/v1/admin/diagnostics/* and the
remediation actions in phase 1D. Both emit from the registry only and are
skipped by the supply projection (audit trail, not financial).

Idempotent via ON CONFLICT DO NOTHING — safe on every fresh boot or rerun.

Revision ID: 0006_command_center_audit
Revises: 0005_token_bridge
"""

from alembic import op
from sqlalchemy import text

revision = "0006_command_center_audit"
down_revision = "0005_token_bridge"
branch_labels = None
depends_on = None


_POLICIES = (
    (
        "CommandCenterProbe",
        "Audit trail for a single diagnostic probe execution by the Command Center.",
    ),
    (
        "CommandCenterAction",
        "Audit trail for a remediation action invoked from the Command Center.",
    ),
)


def upgrade() -> None:
    bind = op.get_bind()
    for event_type, description in _POLICIES:
        bind.execute(
            text(
                """
                INSERT INTO event_emission_policies
                  (event_type, emit_from_teg, emit_from_registry, skip_in_projection, description, updated_at)
                VALUES
                  (:event_type, false, true, true, :description, now())
                ON CONFLICT (event_type) DO NOTHING
                """
            ),
            {"event_type": event_type, "description": description},
        )


def downgrade() -> None:
    bind = op.get_bind()
    for event_type, _ in _POLICIES:
        bind.execute(
            text("DELETE FROM event_emission_policies WHERE event_type = :event_type"),
            {"event_type": event_type},
        )
