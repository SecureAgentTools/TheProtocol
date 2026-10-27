"""Seed CrossRegistryBlockedBySuspension event policy (Option D-light Phase D6).

Revision ID: 0015_blocked_suspension
Revises: 0014_drift_event_policy

Audit-only event emitted by services.federation_license_gate when a
cross-operator interaction is rejected because the peer operator's
federation license is not active. Emission is deduped per
(operator_did, context, yyyy-mm-dd-HH) to suppress retry flood while
preserving the blocking signal.
"""

from alembic import op
from sqlalchemy import text


revision = "0015_blocked_suspension"
down_revision = "0014_drift_event_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("""
        INSERT INTO event_emission_policies
          (event_type, emit_from_teg, emit_from_registry, skip_in_projection, description, updated_at)
        VALUES
          ('CrossRegistryBlockedBySuspension', false, true, true,
           'Cross-operator interaction rejected because the peer operator''s federation license is not active. Deduped per (operator_did, context, hour). Payload: operator_did, license_id, license_status, context, actor_agent_did, actor_registry_did, attempted_at.',
           now())
        ON CONFLICT (event_type) DO NOTHING
    """))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("""
        DELETE FROM event_emission_policies
        WHERE event_type = 'CrossRegistryBlockedBySuspension'
    """))
