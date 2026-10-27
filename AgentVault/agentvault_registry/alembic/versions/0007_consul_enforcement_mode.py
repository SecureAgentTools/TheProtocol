"""CONSUL: add compliance_enforcement_mode kill switch + seed CONSUL audit event policies.

Adds three columns to registry_operating_state:
  - compliance_enforcement_mode VARCHAR(20) NOT NULL DEFAULT 'off'
  - compliance_mode_updated_at TIMESTAMPTZ NULL
  - compliance_mode_updated_by VARCHAR(255) NULL

Seeds three event_emission_policies for the CONSUL (Compliance Oversight,
Network Surveillance, Unified Lockdown) dashboard audit trail:
  - ComplianceDryRunDrift         — drift that WOULD have quarantined in enforcing mode
  - ComplianceEnforcementModeChanged — admin flipped the kill switch
  - CompliancePollCycleCompleted  — poller cycle summary (one per cycle)

All three emit from registry only, skip_in_projection=true.

Idempotent via IF NOT EXISTS / ON CONFLICT DO NOTHING.

Revision ID: 0007_consul_enforcement_mode
Revises: 0006_command_center_audit
"""

from alembic import op
from sqlalchemy import text


revision = "0007_consul_enforcement_mode"
down_revision = "0006_command_center_audit"
branch_labels = None
depends_on = None


_EVENT_POLICIES = (
    (
        "ComplianceDryRunDrift",
        "CONSUL: Drift detected in dry-run mode — no quarantine fired. Contains what_would_happen payload.",
    ),
    (
        "ComplianceEnforcementModeChanged",
        "CONSUL: Admin flipped compliance enforcement mode (off / dry_run / enforcing).",
    ),
    (
        "CompliancePollCycleCompleted",
        "CONSUL: Summary emitted at the end of each compliance poll cycle.",
    ),
)


def upgrade() -> None:
    bind = op.get_bind()

    # Column additions (idempotent)
    bind.execute(text("""
        ALTER TABLE registry_operating_state
        ADD COLUMN IF NOT EXISTS compliance_enforcement_mode VARCHAR(20) NOT NULL DEFAULT 'off'
    """))
    bind.execute(text("""
        ALTER TABLE registry_operating_state
        ADD COLUMN IF NOT EXISTS compliance_mode_updated_at TIMESTAMPTZ NULL
    """))
    bind.execute(text("""
        ALTER TABLE registry_operating_state
        ADD COLUMN IF NOT EXISTS compliance_mode_updated_by VARCHAR(255) NULL
    """))

    # Seed the three audit-event policies
    for event_type, description in _EVENT_POLICIES:
        bind.execute(
            text("""
                INSERT INTO event_emission_policies
                  (event_type, emit_from_teg, emit_from_registry, skip_in_projection, description, updated_at)
                VALUES
                  (:event_type, false, true, true, :description, now())
                ON CONFLICT (event_type) DO NOTHING
            """),
            {"event_type": event_type, "description": description},
        )


def downgrade() -> None:
    bind = op.get_bind()

    bind.execute(text("ALTER TABLE registry_operating_state DROP COLUMN IF EXISTS compliance_mode_updated_by"))
    bind.execute(text("ALTER TABLE registry_operating_state DROP COLUMN IF EXISTS compliance_mode_updated_at"))
    bind.execute(text("ALTER TABLE registry_operating_state DROP COLUMN IF EXISTS compliance_enforcement_mode"))

    for event_type, _ in _EVENT_POLICIES:
        bind.execute(
            text("DELETE FROM event_emission_policies WHERE event_type = :event_type"),
            {"event_type": event_type},
        )
