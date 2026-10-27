"""Federation license self-serve rotation idempotency table (BL-1, 2026-05-11).

Revision ID: 0048_fed_license_rotate
Revises: 0047_dual_slot_bearer_dedup

Adds federation_license_rotations table for idempotent self-serve license
rotation via POST /api/v1/federation/license/rotate-self.

Three-phase commit (per Operator_CLI_Strategy.md §7.2.1):
  Phase 1: pre-allocate new license row + write row to this table (status='pending')
  Phase 2: revoke old license + flip this row to status='committed'
  Phase 3: return plain key + flip this row to status='returned'

Idempotency-key TTL 24h. Background GC sweeps rows older than 24h.

Raw SQL + IF NOT EXISTS per feedback_migration_use_raw_sql_if_not_exists.md
(cloud-op migration bridge resets to 0001_squash on each boot).

Revision-id length: 23 chars (alembic_version.version_num is varchar(32)).
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0048_fed_license_rotate"
down_revision: Union[str, None] = "0047_dual_slot_bearer_dedup"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS federation_license_rotations (
            id              VARCHAR(36)  PRIMARY KEY,
            idempotency_key VARCHAR(64)  NOT NULL UNIQUE,
            caller_license_id VARCHAR(36) NOT NULL,
            prev_license_key_hash VARCHAR(64) NOT NULL,
            new_license_id  VARCHAR(36)  NULL,
            status          VARCHAR(20)  NOT NULL DEFAULT 'pending',
            reason          VARCHAR(64)  NULL,
            new_license_key VARCHAR(80)  NULL,
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            committed_at    TIMESTAMPTZ  NULL,
            returned_at     TIMESTAMPTZ  NULL,
            expires_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW() + INTERVAL '24 hours'
        )
    """)
    # Idempotent add for existing tables (sandbox-A already has it without the column).
    op.execute("""
        ALTER TABLE federation_license_rotations
          ADD COLUMN IF NOT EXISTS prev_license_key_hash VARCHAR(64) NOT NULL DEFAULT ''
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_fed_lic_rotations_caller
          ON federation_license_rotations (caller_license_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_fed_lic_rotations_expires
          ON federation_license_rotations (expires_at)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS federation_license_rotations CASCADE")
