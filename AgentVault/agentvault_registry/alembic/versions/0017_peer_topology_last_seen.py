"""Peer topology last-seen — make chain-reachability a first-class signal.

Revision ID: 0017_peer_topology_last_seen
Revises: 0016_peer_topology_fields

Adds one column to peer_registries so the drift detector can tell the difference
between "partial teardown" (peer offline, license orphaned) and "chain-federated"
(peer not directly peered but reachable through another peer's published
topology). Before this migration, drift rule 3 (`peer_inactive_license_active`)
fires on every chain-federated operator — which created an incentive to
direct-peer every cloud op to the main frame, collapsing chain topology back to
hub-and-spoke.

New column:
  - last_seen_in_topology_at  TIMESTAMPTZ NULL
                              — updated by BFS writeback every cycle the peer
                                appears in fresh topology output. Drift rule 3
                                suppresses when this is fresh (≤30 min) because
                                BFS-reachable peers are chain-federated, not drift.

Backfill (idempotent, only touches rows currently NULL):
  - Active seed peers (status='ACTIVE', peer_type in frame/direct_peer/cloud_operator)
    → NOW() (presumed reachable; next BFS cycle refreshes or lets them go stale).
  - Discovered peers with hop_distance set (BFS has been finding them)
    → NOW().
  - INACTIVE cloud operators with hop_distance set (the chain-reached case,
    e.g., op-london/op-paris/op-washington after chain reconstruction) → NOW(),
    so they don't drift-flag during BFS warm-up after this migration.

Legacy VPS direct peers (INACTIVE, no hop_distance) stay NULL → correctly drift.

No event policy changes — FederationStateDriftDetected keeps the same schema,
only its firing condition tightens in the Python code (not in the DB).

IDEMPOTENCY: migration_bridge.py re-stamps alembic_version to 0001_squash on
every boot. All ops use IF NOT EXISTS or WHERE guards so replay is a no-op.
"""

from alembic import op
from sqlalchemy import text


revision = "0017_peer_topology_last_seen"
down_revision = "0016_peer_topology_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # --- Column addition (idempotent) ---
    bind.execute(text("""
        ALTER TABLE peer_registries
          ADD COLUMN IF NOT EXISTS last_seen_in_topology_at TIMESTAMPTZ NULL
    """))

    # --- Backfill: seed NOW() for currently-reachable peers ---
    # Three branches cover every reachable peer at migration time:
    #   1. ACTIVE seeds (direct config): will refresh on next BFS cycle anyway.
    #   2. Discovered peers with hop_distance: BFS has been finding them.
    #   3. INACTIVE cloud operators with hop_distance (chain-reconstructed ops):
    #      chain-reachable via op-berlin but deactivated as direct peers.
    #
    # Anything else (INACTIVE direct_peer with no hop_distance = legacy VPS
    # operators truly gone) stays NULL so drift rule 3 correctly fires.
    bind.execute(text("""
        UPDATE peer_registries
           SET last_seen_in_topology_at = NOW()
         WHERE last_seen_in_topology_at IS NULL
           AND (
                 (UPPER(status) = 'ACTIVE'
                   AND peer_type IN ('frame', 'direct_peer', 'cloud_operator'))
              OR (peer_type = 'discovered' AND hop_distance IS NOT NULL)
              OR (peer_type = 'cloud_operator'
                   AND UPPER(status) = 'INACTIVE'
                   AND hop_distance IS NOT NULL)
               )
    """))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text(
        "ALTER TABLE peer_registries DROP COLUMN IF EXISTS last_seen_in_topology_at"
    ))
