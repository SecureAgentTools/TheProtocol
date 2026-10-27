"""Peer topology fields — make frame / direct / discovered / cloud hierarchy explicit.

Revision ID: 0016_peer_topology_fields
Revises: 0015_blocked_suspension

Adds six columns to peer_registries so the federation topology is legible from
the data layer (previously implicit via SPIFFE path + OperatorApplication.cloud_hosted).

New columns (all nullable except peer_type which has server_default):
  - peer_type            VARCHAR(20) NOT NULL DEFAULT 'direct_peer'
                         (frame | direct_peer | discovered | cloud_operator)
  - operator_did         VARCHAR(255) NULL    — link peer to its federation license
  - parent_registry_id   INTEGER NULL FK peer_registries(id) ON DELETE SET NULL
                         — for BFS-discovered peers, the direct peer that led here
  - hop_distance         INTEGER NULL         — set by BFS crawl (1 = direct, 2+ = discovered)
  - trust_domain         VARCHAR(255) NULL    — SPIFFE trust domain for frame peers
  - discovered_at        TIMESTAMPTZ NULL     — when BFS first discovered this row

Index: ix_peer_registries_peer_type on (peer_type).

Backfill (all idempotent, WHERE guards prevent re-application):
  - Frame-B → peer_type='frame', trust_domain='frame-b.theprotocol.cloud'
  - Live cloud operators (JOIN via name) → peer_type='cloud_operator'
  - All directly-configured peers → hop_distance=1

Seeds event_emission_policies row:
  - PeerTopologyRefreshed (emit_from_registry=true, skip_in_projection=true)

IDEMPOTENCY NOTE: migration_bridge.py re-stamps alembic_version to 0001_squash on
every container boot; all post-squash migrations replay on every boot. All schema
ops here use IF NOT EXISTS; all seeds ON CONFLICT DO NOTHING; all backfills use
WHERE <target-state> guards.
"""

from alembic import op
from sqlalchemy import text


revision = "0016_peer_topology_fields"
down_revision = "0015_blocked_suspension"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # --- Column additions (idempotent) ---
    bind.execute(text("""
        ALTER TABLE peer_registries
          ADD COLUMN IF NOT EXISTS peer_type VARCHAR(20) NOT NULL DEFAULT 'direct_peer'
    """))
    bind.execute(text("""
        ALTER TABLE peer_registries
          ADD COLUMN IF NOT EXISTS operator_did VARCHAR(255) NULL
    """))
    bind.execute(text("""
        ALTER TABLE peer_registries
          ADD COLUMN IF NOT EXISTS parent_registry_id INTEGER NULL
            REFERENCES peer_registries(id) ON DELETE SET NULL
    """))
    bind.execute(text("""
        ALTER TABLE peer_registries
          ADD COLUMN IF NOT EXISTS hop_distance INTEGER NULL
    """))
    bind.execute(text("""
        ALTER TABLE peer_registries
          ADD COLUMN IF NOT EXISTS trust_domain VARCHAR(255) NULL
    """))
    bind.execute(text("""
        ALTER TABLE peer_registries
          ADD COLUMN IF NOT EXISTS discovered_at TIMESTAMPTZ NULL
    """))
    bind.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_peer_registries_peer_type
          ON peer_registries(peer_type)
    """))

    # --- Backfill: Frame-B rows get peer_type='frame' + trust_domain ---
    # Match only the frame root, NOT subdomains like op-seoul.frame-b.theprotocol.cloud
    # (those are Frame-B's operators, which land in the 'discovered' tier).
    bind.execute(text("""
        UPDATE peer_registries
           SET peer_type = 'frame',
               trust_domain = COALESCE(trust_domain, 'frame-b.theprotocol.cloud')
         WHERE (
                 name ILIKE 'Frame-B'
              OR name ILIKE 'Frame B'
              OR base_url ILIKE 'https://frame-b.theprotocol.cloud%'
              OR base_url ILIKE 'http://frame-b.theprotocol.cloud%'
              OR base_url ILIKE 'https://frame-b.theprotocol.cloud:%'
               )
           AND peer_type IS DISTINCT FROM 'frame'
    """))

    # --- Backfill: live cloud operators get peer_type='cloud_operator' ---
    bind.execute(text("""
        UPDATE peer_registries AS pr
           SET peer_type = 'cloud_operator'
          FROM operator_applications AS oa
         WHERE oa.cloud_hosted = true
           AND oa.cloud_torn_down_at IS NULL
           AND pr.name = oa.name
           AND pr.peer_type IS DISTINCT FROM 'cloud_operator'
           AND pr.peer_type IS DISTINCT FROM 'frame'
    """))

    # --- Backfill: link peers to their federation license operator_did ---
    # federation_licenses joins via operator_name; no application_id FK exists
    # (name is the shared identifier across peer_registries / operator_applications
    # / federation_licenses). Only link when license is live — revoked licenses
    # leave the peer's operator_did null so /admin/federation/licenses stays the
    # authoritative view of historical revocations.
    bind.execute(text("""
        UPDATE peer_registries AS pr
           SET operator_did = fl.operator_did
          FROM federation_licenses AS fl
         WHERE pr.name = fl.operator_name
           AND pr.operator_did IS NULL
           AND fl.status IN ('active', 'suspended')
    """))

    # --- Backfill: directly-configured peers get hop_distance=1 ---
    bind.execute(text("""
        UPDATE peer_registries
           SET hop_distance = 1
         WHERE hop_distance IS NULL
           AND peer_type IN ('direct_peer', 'cloud_operator', 'frame')
    """))

    # --- Seed PeerTopologyRefreshed event policy (audit-only, skip_in_projection=true) ---
    bind.execute(text("""
        INSERT INTO event_emission_policies
          (event_type, emit_from_teg, emit_from_registry, skip_in_projection, description, updated_at)
        VALUES
          ('PeerTopologyRefreshed', false, true, true,
           'BFS topology crawl completed. Per-cycle summary emitted once per refresh, deduped hourly. Payload: refresh_id, peers_updated, new_peers_discovered, duration_ms, local_peer_count, discovered_peer_count.',
           now())
        ON CONFLICT (event_type) DO NOTHING
    """))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("""
        DELETE FROM event_emission_policies
        WHERE event_type = 'PeerTopologyRefreshed'
    """))
    bind.execute(text("DROP INDEX IF EXISTS ix_peer_registries_peer_type"))
    bind.execute(text("ALTER TABLE peer_registries DROP COLUMN IF EXISTS discovered_at"))
    bind.execute(text("ALTER TABLE peer_registries DROP COLUMN IF EXISTS trust_domain"))
    bind.execute(text("ALTER TABLE peer_registries DROP COLUMN IF EXISTS hop_distance"))
    bind.execute(text("ALTER TABLE peer_registries DROP COLUMN IF EXISTS parent_registry_id"))
    bind.execute(text("ALTER TABLE peer_registries DROP COLUMN IF EXISTS operator_did"))
    bind.execute(text("ALTER TABLE peer_registries DROP COLUMN IF EXISTS peer_type"))
