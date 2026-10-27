"""License suspension cascade metadata + 3 event policies (Option D-light, Phase D1).

Revision ID: 0013_license_cascade
Revises: 0012_admin_flags_policy

Adds suspension audit columns to federation_licenses:
  - suspended_at        TIMESTAMPTZ NULL
  - suspended_by        INTEGER NULL REFERENCES developers(id)
  - suspended_reason    VARCHAR(500) NULL

Seeds event_emission_policies rows (audit-only, skip_in_projection=true):
  - FederationLicenseSuspended    (Phase D2a)
  - FederationLicenseReinstated   (Phase D2b)
  - PeerRegistryDeactivated       (Phase D3)

IDEMPOTENCY NOTE: migration_bridge.py re-stamps alembic_version to 0001_squash
on every container boot, causing every post-squash migration to replay. All
schema ops here use IF NOT EXISTS guards; all seed ops use ON CONFLICT DO
NOTHING. Pattern follows 0011_admin_flag_split.
"""

from alembic import op
from sqlalchemy import text


revision = "0013_license_cascade"
down_revision = "0012_admin_flags_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    bind.execute(text("""
        ALTER TABLE federation_licenses
          ADD COLUMN IF NOT EXISTS suspended_at TIMESTAMPTZ NULL
    """))
    bind.execute(text("""
        ALTER TABLE federation_licenses
          ADD COLUMN IF NOT EXISTS suspended_by INTEGER NULL REFERENCES developers(id) ON DELETE SET NULL
    """))
    bind.execute(text("""
        ALTER TABLE federation_licenses
          ADD COLUMN IF NOT EXISTS suspended_reason VARCHAR(500) NULL
    """))

    bind.execute(text("""
        INSERT INTO event_emission_policies
          (event_type, emit_from_teg, emit_from_registry, skip_in_projection, description, updated_at)
        VALUES
          ('FederationLicenseSuspended', false, true, true,
           'Federation license suspended (cascade from suspend_operator). Payload: license_id, operator_did, reason, actor.',
           now()),
          ('FederationLicenseReinstated', false, true, true,
           'Federation license reinstated (cascade from reinstate_operator). Payload: license_id, operator_did, actor.',
           now()),
          ('PeerRegistryDeactivated', false, true, true,
           'Peer registry marked inactive (cascade from cloud teardown or admin deactivate). Payload: peer_id, peer_name, reason, actor.',
           now())
        ON CONFLICT (event_type) DO NOTHING
    """))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("""
        DELETE FROM event_emission_policies
        WHERE event_type IN (
          'FederationLicenseSuspended',
          'FederationLicenseReinstated',
          'PeerRegistryDeactivated'
        )
    """))
    bind.execute(text("ALTER TABLE federation_licenses DROP COLUMN IF EXISTS suspended_reason"))
    bind.execute(text("ALTER TABLE federation_licenses DROP COLUMN IF EXISTS suspended_by"))
    bind.execute(text("ALTER TABLE federation_licenses DROP COLUMN IF EXISTS suspended_at"))
