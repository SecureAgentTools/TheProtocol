"""PB-1 — Stripe Fiat → AVT on-ramp tables + emission policies (2026-05-09).

Revision ID: 0031_fiat_purchases
Revises: 0030_disputes_chain_polish

Creates the `fiat_purchases` audit table and seeds 3 emission-policy rows
covering the new fiat event types. Mainframe-only at runtime — the router
returns 403 on federated registries — but the schema is identical
everywhere so cross-registry reads stay consistent.

Idempotent (IF NOT EXISTS / WHERE NOT EXISTS) so migration_bridge replays
on every container boot remain safe.
"""
from alembic import op


revision = "0031_fiat_purchases"
down_revision = "0030_disputes_chain_polish"
branch_labels = None
depends_on = None


def upgrade():
    # -----------------------------------------------------------------------
    # 1. fiat_purchases — audit table for every Stripe Checkout Session
    # -----------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS fiat_purchases (
            id                          VARCHAR(36) PRIMARY KEY,
            stripe_session_id           VARCHAR(255) UNIQUE NOT NULL,
            stripe_event_id             VARCHAR(255) UNIQUE,
            stripe_payment_intent_id    VARCHAR(255),

            developer_id                INTEGER REFERENCES developers(id) ON DELETE SET NULL,
            agent_did                   VARCHAR(255),
            customer_email              VARCHAR(255),

            amount_eur                  NUMERIC(10, 2)   NOT NULL,
            amount_avt                  NUMERIC(30, 6)   NOT NULL,
            avt_per_eur_rate            NUMERIC(10, 2)   NOT NULL,
            tier_label                  VARCHAR(32)      NOT NULL,

            status                      VARCHAR(20)      NOT NULL DEFAULT 'pending',
            failure_reason              VARCHAR(500),
            avt_transfer_tx_id          VARCHAR(255),

            anonymous_flow              BOOLEAN          NOT NULL DEFAULT false,

            created_at                  TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
            completed_at                TIMESTAMPTZ,
            refunded_at                 TIMESTAMPTZ
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_fiat_purchases_status ON fiat_purchases(status);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_fiat_purchases_developer ON fiat_purchases(developer_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_fiat_purchases_agent_did ON fiat_purchases(agent_did);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_fiat_purchases_email ON fiat_purchases(customer_email);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_fiat_purchases_session ON fiat_purchases(stripe_session_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_fiat_purchases_event ON fiat_purchases(stripe_event_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_fiat_purchases_pi ON fiat_purchases(stripe_payment_intent_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_fiat_purchases_created ON fiat_purchases(created_at DESC);")

    # -----------------------------------------------------------------------
    # 2. event_emission_policies seeding for the 3 new fiat event types
    # -----------------------------------------------------------------------
    # Registry emits all 3 (TEG never sees fiat). FiatPurchaseSettled is
    # skip_in_projection=true because /admin/reward-fund already emits
    # TokensTransferred for the actual AVT motion (no double-count).
    op.execute("""
        INSERT INTO event_emission_policies (event_type, emit_from_teg, emit_from_registry, skip_in_projection)
        VALUES
            ('FiatPurchaseInitiated', false, true, false),
            ('FiatPurchaseSettled',   false, true, true),
            ('FiatPurchaseRefunded',  false, true, false)
        ON CONFLICT (event_type) DO UPDATE SET
            emit_from_teg       = EXCLUDED.emit_from_teg,
            emit_from_registry  = EXCLUDED.emit_from_registry,
            skip_in_projection  = EXCLUDED.skip_in_projection;
    """)


def downgrade():
    op.execute("DELETE FROM event_emission_policies WHERE event_type LIKE 'FiatPurchase%';")
    op.execute("DROP TABLE IF EXISTS fiat_purchases;")
