"""Seed FederationStateDriftDetected event policy (Option D-light Phase D4).

Revision ID: 0014_drift_event_policy
Revises: 0013_license_cascade

Seeds a single event type used by the license_drift_monitor background task
to record cross-table state inconsistencies. The `drift_type` field in the
payload disambiguates:
  - license_revoked_operator_active
  - operator_revoked_license_active
  - peer_inactive_license_active

Audit-only (emit_from_registry=true, skip_in_projection=true).
"""

from alembic import op
from sqlalchemy import text


revision = "0014_drift_event_policy"
down_revision = "0013_license_cascade"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("""
        INSERT INTO event_emission_policies
          (event_type, emit_from_teg, emit_from_registry, skip_in_projection, description, updated_at)
        VALUES
          ('FederationStateDriftDetected', false, true, true,
           'License/operator/peer state drift surfaced by license_drift_monitor (Option D-light Phase D4). Payload: drift_type, license_id, application_id, peer_id, license_status, operator_status, peer_status, detected_at.',
           now())
        ON CONFLICT (event_type) DO NOTHING
    """))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("""
        DELETE FROM event_emission_policies
        WHERE event_type = 'FederationStateDriftDetected'
    """))
