"""PB-2 — Routed Fiat Purchase: operator storefront → mainframe Stripe → operator treasury (2026-05-09).

Revision ID: 0038_fiat_routed
Revises: 0037_account_deletion

Adds the schema needed for the routed-fiat flow where a buyer pays on an
operator registry's storefront, mainframe runs the Stripe checkout, and AVT
lands on the operator's TEG via the existing 2-phase cross-TEG fund
orchestrator. See:
  • sessionlogs2026/INVESTIGATION_2026-05-09_ROUTED_FIAT_PURCHASE_FROM_OPERATORS.md
  • sessionlogs2026/HANDOVER_2026-05-09_ROUTED_FIAT_IMPLEMENTATION.md

Schema changes
==============

A) `fiat_purchases` — extend with 9 columns covering both sides:

   • routed                              BOOLEAN  default false
       Master discriminator: true ⇒ routed-via-operator, false ⇒ direct
       mainframe-only flow (existing PB-1).
   • target_operator_did                 VARCHAR(255) nullable
       Mainframe-side only — DID of the operator's federation license.
   • target_operator_registry_name       VARCHAR(255) nullable
       Mainframe-side only — peer name slug for the cross-teg-fund target
       (e.g., 'cloud-op-op-london', 'Sandbox Alpha').
   • cross_teg_correlation_id            VARCHAR(36)  nullable
       Mainframe-side only — UUID linking to the cross-teg-fund txn so
       reconciler + auditor can correlate. Set after step ② commits.
   • operator_callback_status            VARCHAR(20)  nullable
       Mainframe-side only — one of {pending, success, failed,
       manual_intervention}. Reconciler retries on pending|failed.
   • operator_callback_attempts          INTEGER  default 0
       Mainframe-side only — retry counter (max 5 before MANUAL_INTERVENTION).
   • operator_callback_last_error        VARCHAR(500) nullable
       Mainframe-side only — last failure detail for support.
   • operator_callback_last_attempted_at TIMESTAMPTZ  nullable
       Mainframe-side only — for reconciler retry-cadence gating.
   • mainframe_fiat_purchase_id          VARCHAR(36)  nullable UNIQUE
       Operator-side only — links operator's row to mainframe's row.
       UNIQUE prevents double-callback processing (idempotency layer 3).

B) `peer_registries` — extend with `callback_secret` for HMAC-signed
   mainframe → operator callbacks. NULL ⇒ derive from FEDERATION_INTERNAL_SECRET
   (sandbox shortcut). Production: admin issues a per-operator secret at
   peer-activation time; rotatable.

C) Indexes:

   • idx_fiat_purchases_routed_pending — partial index on
     (operator_callback_last_attempted_at) WHERE routed=true AND status='PROCESSING'
     AND operator_callback_status IN ('pending','failed'). Keeps the daily
     mainframe-side reconciler scan cheap regardless of fleet size.

Idempotent (ADD COLUMN IF NOT EXISTS, CREATE INDEX IF NOT EXISTS).

Apply on: registry-a (mainframe), registry-test (sandbox-A), and the 3
sandbox operators (sandboxalpha/beta/gamma) — all 5 DBs.
"""
from alembic import op


revision = "0038_fiat_routed"
down_revision = "0037_account_deletion"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE fiat_purchases
            ADD COLUMN IF NOT EXISTS routed                              BOOLEAN      NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS target_operator_did                 VARCHAR(255),
            ADD COLUMN IF NOT EXISTS target_operator_registry_name       VARCHAR(255),
            ADD COLUMN IF NOT EXISTS cross_teg_correlation_id            VARCHAR(36),
            ADD COLUMN IF NOT EXISTS operator_callback_status            VARCHAR(20),
            ADD COLUMN IF NOT EXISTS operator_callback_attempts          INTEGER      NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS operator_callback_last_error        VARCHAR(500),
            ADD COLUMN IF NOT EXISTS operator_callback_last_attempted_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS mainframe_fiat_purchase_id          VARCHAR(36);
    """)

    # UNIQUE on the operator-side mainframe link (idempotency layer 3).
    # Partial constraint: only enforced on rows where the column is set, so
    # mainframe-side rows (which don't populate this column) coexist freely.
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_fiat_purchases_mainframe_id
        ON fiat_purchases (mainframe_fiat_purchase_id)
        WHERE mainframe_fiat_purchase_id IS NOT NULL;
    """)

    # Daily mainframe-side reconciler scan target.
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_fiat_purchases_routed_pending
        ON fiat_purchases (operator_callback_last_attempted_at)
        WHERE routed = TRUE
          AND status = 'PROCESSING'
          AND operator_callback_status IN ('pending', 'failed');
    """)

    # peer_registries.callback_secret — per-operator HMAC secret for
    # mainframe → operator routed-settle callbacks. Sandbox falls back to
    # FEDERATION_INTERNAL_SECRET when this is NULL; production sets it
    # explicitly at peer-activation time.
    op.execute("""
        ALTER TABLE peer_registries
            ADD COLUMN IF NOT EXISTS callback_secret VARCHAR(255);
    """)


def downgrade():
    op.execute("ALTER TABLE peer_registries DROP COLUMN IF EXISTS callback_secret;")
    op.execute("DROP INDEX IF EXISTS idx_fiat_purchases_routed_pending;")
    op.execute("DROP INDEX IF EXISTS uq_fiat_purchases_mainframe_id;")
    op.execute("""
        ALTER TABLE fiat_purchases
            DROP COLUMN IF EXISTS mainframe_fiat_purchase_id,
            DROP COLUMN IF EXISTS operator_callback_last_attempted_at,
            DROP COLUMN IF EXISTS operator_callback_last_error,
            DROP COLUMN IF EXISTS operator_callback_attempts,
            DROP COLUMN IF EXISTS operator_callback_status,
            DROP COLUMN IF EXISTS cross_teg_correlation_id,
            DROP COLUMN IF EXISTS target_operator_registry_name,
            DROP COLUMN IF EXISTS target_operator_did,
            DROP COLUMN IF EXISTS routed;
    """)
