"""§pass51 Block 1 — Bundles core schema + signing keys + quotas + event policies.

Revision ID: 0075_bdl_bundles_core
Revises: 0074_bc5_cicd_notif
Create Date: 2026-05-20

Bundles feature foundation (see PLAN_2026-05-20_BUNDLES_AAA_REBOOT.md
Part I §3 + Part II §18). Adds:

  - agent_bundles: snapshot/template/migration archives of agent(s)
  - bundle_installations: audit trail of who installed what when
  - bundle_ratings: 1-5 star ratings (one per dev per bundle)
  - bundle_reports: moderation queue rows
  - developer_quotas: per-dev caps on bundle count / size
  - developer_signing_keys: JWS signing keypair per developer
  - agents.is_federated_mirror: column for MIRROR mode (added; not used in v1)
  - 15 new event_emission_policies rows for bundle lifecycle events

All additive + idempotent (IF NOT EXISTS, ON CONFLICT DO NOTHING).
Downgrade drops tables, drops column, deletes policy rows.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0075_bdl_bundles_core"
down_revision: Union[str, None] = "0074_bc5_cicd_notif"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


BUNDLE_EVENT_TYPES = [
    "BundleCreated",
    "BundleDownloaded",
    "BundleInstalled",
    "BundleInstallRepaired",
    "BundleRated",
    "BundleVisibilityChanged",
    "BundleReported",
    "BundleHidden",
    "BundleDeleted",
    "BundleExpired",
    "BundleStorageOrphanReaped",
    "BundleScanFlagged",
    "BundleSubmitterBanned",
    "DeveloperSigningKeyRotated",
    "DeveloperSigningKeyRevoked",
]


def upgrade() -> None:
    # ── agent_bundles ───────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_bundles (
            id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            bundle_kind                 VARCHAR(16) NOT NULL CHECK (bundle_kind IN ('snapshot','template','migration')),
            name                        VARCHAR(160) NOT NULL,
            slug                        VARCHAR(80),
            description                 TEXT,
            category                    VARCHAR(40),
            manifest_json               JSONB NOT NULL,
            bundle_sha256               VARCHAR(64) NOT NULL,
            bundle_size_bytes           BIGINT NOT NULL,
            storage_key                 VARCHAR(255) NOT NULL,
            source_dev_id               INTEGER REFERENCES developers(id) ON DELETE SET NULL,
            source_org_id               UUID,
            source_did                  VARCHAR(160),
            visibility                  VARCHAR(16) NOT NULL DEFAULT 'private'
                                        CHECK (visibility IN ('private','org','public')),
            is_official                 BOOLEAN NOT NULL DEFAULT FALSE,
            is_pinned                   BOOLEAN NOT NULL DEFAULT FALSE,
            is_hidden                   BOOLEAN NOT NULL DEFAULT FALSE,
            is_official_for_org         BOOLEAN NOT NULL DEFAULT FALSE,
            signature_jws               TEXT,
            signature_tier              SMALLINT NOT NULL DEFAULT 0,
            supersedes_bundle_id        UUID REFERENCES agent_bundles(id) ON DELETE SET NULL,
            expires_at                  TIMESTAMP WITH TIME ZONE,
            retention_until             TIMESTAMP WITH TIME ZONE,
            download_count              INTEGER NOT NULL DEFAULT 0,
            install_count               INTEGER NOT NULL DEFAULT 0,
            rating_sum                  INTEGER NOT NULL DEFAULT 0,
            rating_count                INTEGER NOT NULL DEFAULT 0,
            created_at                  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at                  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_bundles_source_dev ON agent_bundles(source_dev_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_bundles_source_org ON agent_bundles(source_org_id) WHERE source_org_id IS NOT NULL;")
    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_bundles_visibility_kind ON agent_bundles(visibility, bundle_kind);")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_bundles_slug ON agent_bundles(slug) WHERE slug IS NOT NULL;")
    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_bundles_retention ON agent_bundles(retention_until) WHERE retention_until IS NOT NULL;")
    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_bundles_expires ON agent_bundles(expires_at) WHERE expires_at IS NOT NULL;")

    # ── bundle_installations ────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS bundle_installations (
            id                          BIGSERIAL PRIMARY KEY,
            bundle_id                   UUID NOT NULL REFERENCES agent_bundles(id) ON DELETE CASCADE,
            installer_dev_id            INTEGER NOT NULL REFERENCES developers(id),
            installer_org_id            UUID,
            produced_dids               TEXT[] NOT NULL DEFAULT '{}',
            conflict_resolution         VARCHAR(16) NOT NULL,
            mode                        VARCHAR(16) NOT NULL DEFAULT 'copy',
            pull_sync_triggered         BOOLEAN NOT NULL DEFAULT FALSE,
            pull_sync_succeeded         BOOLEAN NOT NULL DEFAULT FALSE,
            cicd_install_succeeded      BOOLEAN NOT NULL DEFAULT TRUE,
            last_repair_attempt_at      TIMESTAMP WITH TIME ZONE,
            installed_at                TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_bundle_installations_bundle ON bundle_installations(bundle_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_bundle_installations_dev ON bundle_installations(installer_dev_id);")

    # ── bundle_ratings ──────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS bundle_ratings (
            id                          BIGSERIAL PRIMARY KEY,
            bundle_id                   UUID NOT NULL REFERENCES agent_bundles(id) ON DELETE CASCADE,
            rater_dev_id                INTEGER NOT NULL REFERENCES developers(id),
            rating                      SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
            comment                     TEXT,
            created_at                  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            UNIQUE (bundle_id, rater_dev_id)
        );
    """)

    # ── bundle_reports ──────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS bundle_reports (
            id                          BIGSERIAL PRIMARY KEY,
            bundle_id                   UUID NOT NULL REFERENCES agent_bundles(id) ON DELETE CASCADE,
            reporter_dev_id             INTEGER NOT NULL REFERENCES developers(id),
            reason_code                 VARCHAR(40) NOT NULL,
            comment                     TEXT,
            resolved_at                 TIMESTAMP WITH TIME ZONE,
            resolved_by_dev_id          INTEGER REFERENCES developers(id),
            resolution                  VARCHAR(40),
            created_at                  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_bundle_reports_open ON bundle_reports(bundle_id) WHERE resolved_at IS NULL;")

    # ── developer_quotas ────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS developer_quotas (
            developer_id                INTEGER PRIMARY KEY REFERENCES developers(id) ON DELETE CASCADE,
            max_bundle_count            INTEGER NOT NULL DEFAULT 100,
            max_bundle_total_bytes      BIGINT  NOT NULL DEFAULT 1073741824,
            max_individual_bundle_bytes BIGINT  NOT NULL DEFAULT 104857600,
            bundle_create_rate_per_day  INTEGER NOT NULL DEFAULT 10,
            custom_quota_reason         TEXT,
            updated_at                  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        );
    """)

    # ── developer_signing_keys ──────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS developer_signing_keys (
            id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            developer_id                INTEGER NOT NULL REFERENCES developers(id) ON DELETE CASCADE,
            public_key_jwk              JSONB NOT NULL,
            private_key_pem             TEXT NOT NULL,
            fingerprint                 VARCHAR(64) NOT NULL UNIQUE,
            rotation_seq                INTEGER NOT NULL DEFAULT 1,
            created_at                  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            revoked_at                  TIMESTAMP WITH TIME ZONE,
            revoked_retroactive_at      TIMESTAMP WITH TIME ZONE,
            superseded_by_key_id        UUID REFERENCES developer_signing_keys(id) ON DELETE SET NULL,
            revoke_reason               TEXT
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_dev_signing_keys_dev_active ON developer_signing_keys(developer_id) WHERE revoked_at IS NULL;")

    # ── agents.is_federated_mirror (MIRROR mode column; deferred feature) ──
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='agents' AND column_name='is_federated_mirror'
            ) THEN
                ALTER TABLE agents ADD COLUMN is_federated_mirror BOOLEAN NOT NULL DEFAULT FALSE;
            END IF;
        END $$;
    """)

    # ── 15 event_emission_policies rows ─────────────────────────────────────
    for evt in BUNDLE_EVENT_TYPES:
        op.execute(f"""
            INSERT INTO event_emission_policies
                (event_type, emit_from_teg, emit_from_registry, skip_in_projection)
            VALUES ('{evt}', false, true, true)
            ON CONFLICT (event_type) DO NOTHING;
        """)


def downgrade() -> None:
    # Drop in reverse FK order
    for evt in BUNDLE_EVENT_TYPES:
        op.execute(f"DELETE FROM event_emission_policies WHERE event_type='{evt}';")
    op.execute("DROP TABLE IF EXISTS bundle_reports;")
    op.execute("DROP TABLE IF EXISTS bundle_ratings;")
    op.execute("DROP TABLE IF EXISTS bundle_installations;")
    op.execute("DROP TABLE IF EXISTS agent_bundles;")
    op.execute("DROP TABLE IF EXISTS developer_quotas;")
    op.execute("DROP TABLE IF EXISTS developer_signing_keys;")
    op.execute("ALTER TABLE agents DROP COLUMN IF EXISTS is_federated_mirror;")
