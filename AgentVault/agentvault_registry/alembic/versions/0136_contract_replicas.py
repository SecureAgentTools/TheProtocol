"""contract_replicas — cross-frame contract views (additive)

A replica is a READ-ONLY view of a contract that lives on another frame. It holds no money, has
no escrow reference it can act on, and no route may transition it. `digest` is the home frame's
content hash and `signature` is that frame's signature over it, so a replica can prove it is
current — or prove it is stale — without trusting the transport that delivered it.

`stale` is set by the reconciler when the local digest disagrees with home. It is a fact about
the replica, never about the contract.

Revision ID: 0136_contract_replicas
Revises: 0135_push_login_approvals
"""
from alembic import op
from sqlalchemy import text

revision = "0136_contract_replicas"
down_revision = "0135_push_login_approvals"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS contract_replicas (
            cid                 VARCHAR(80) PRIMARY KEY,
            home_registry       VARCHAR(300) NOT NULL,
            client_did          VARCHAR(120),
            provider_did        VARCHAR(120),
            title               VARCHAR(200),
            currency            VARCHAR(12),
            total_amount        NUMERIC(30,10),
            status              VARCHAR(20) NOT NULL,
            seq                 INTEGER NOT NULL DEFAULT 0,
            digest              VARCHAR(64) NOT NULL,
            signature           TEXT,
            payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
            stale               BOOLEAN NOT NULL DEFAULT false,
            last_synced_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))
    # The reconciler sweeps non-terminal replicas; the provider view lists by DID.
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_contract_replicas_open "
        "ON contract_replicas (status, last_synced_at) "
        "WHERE status NOT IN ('settled','cancelled','failed')"
    ))
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_contract_replicas_provider "
        "ON contract_replicas (provider_did, status)"
    ))
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_contract_replicas_home "
        "ON contract_replicas (home_registry)"
    ))

    # HOME-side outbox watermark. `contract_events` is already written in the same transaction
    # as every state change, so it IS the outbox: a mirror emitted from a worker that reads
    # COMMITTED rows can never describe a transition that rolled back. Emitting from inside
    # `audit()` would have done exactly that, and would also have needed 21 call sites touched.
    bind.execute(text(
        "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS mirrored_seq INTEGER NOT NULL DEFAULT 0"
    ))
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_contracts_mirror_pending "
        "ON contracts (counterparty_home_registry, mirrored_seq) "
        "WHERE counterparty_home_registry IS NOT NULL"
    ))


def downgrade():
    # Additive by policy: rolling an image back must never drop a peer's contract view.
    pass
