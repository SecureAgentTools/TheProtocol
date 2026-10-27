"""Seed OperatorApplicationRevoked + PeerRegistryUrlAutoCorrected policies (2026-04-28).

Revision ID: 0025_revoked_event_policies
Revises: 0024_attestation_schedules

Two new event types introduced 2026-04-28:

1. `OperatorApplicationRevoked` — emitted by the revoke endpoint
   unconditionally (closes the cascade gap when an operator with no
   license gets revoked). Payload: application_id, operator_name,
   operator_did, had_license, license_id, reason, revoked_by, revoked_at.
   Fan-out: OperatorApplicationRevokedReactor flips peer_registries
   to INACTIVE + emits PeerRegistryDeactivated for downstream.

2. `PeerRegistryUrlAutoCorrected` — emitted by PeerUrlSelfHealReactor
   when it auto-heals a misconfigured peer URL (probes 27N43 candidates
   with mTLS, UPDATEs base_url on first 200 response). Payload: peer_id,
   peer_name, old_url, new_url, drift_type, auto_corrected_at, probe_status.

Both audit-only (emit_from_registry=true, skip_in_projection=true).
"""

from alembic import op
from sqlalchemy import text


revision = "0025_revoked_event_policies"
down_revision = "0024_attestation_schedules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("""
        INSERT INTO event_emission_policies
          (event_type, emit_from_teg, emit_from_registry, skip_in_projection, description, updated_at)
        VALUES
          ('OperatorApplicationRevoked', false, true, true,
           'Operator application revoked via admin UI. Emitted unconditionally (regardless of whether a federation_license existed). Triggers OperatorApplicationRevokedReactor which flips peer_registries to INACTIVE.',
           now()),
          ('PeerRegistryUrlAutoCorrected', false, true, true,
           'PeerUrlSelfHealReactor auto-corrected a peer.base_url after detecting peer_url_misconfigured drift. Payload includes old_url, new_url, probe_status. Audit-only — no downstream side effect.',
           now())
        ON CONFLICT (event_type) DO NOTHING
    """))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("""
        DELETE FROM event_emission_policies
        WHERE event_type IN ('OperatorApplicationRevoked', 'PeerRegistryUrlAutoCorrected')
    """))
