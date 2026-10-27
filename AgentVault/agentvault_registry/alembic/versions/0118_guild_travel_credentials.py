"""0118 — THE GUILD: trust that travels (2026-07-08).

Additive-only. Work done on ANY peer registry credits the worker's HOME reputation:
after a cross-registry settle, the HOST ships the Ed25519-signed work credential (the existing
attestation-signer bundle) to the worker's HOME over the federation channel. The home registry
verifies the signature against the host's published signing pubkey (fetched over the same
mTLS peer channel, allowlisted via peer_registries.ACTIVE), stores the credential here, and
folds a poster→worker `local_trust_scores` edge into ITS OWN EigenTrust graph — the exact
fold the local guild settle already uses (`guild_reputation.fold_work_reputation`).
Δ-irrelevant (reputation + signature verification only; no money).
IDEMPOTENT (IF NOT EXISTS), chains 0117.
"""
from alembic import op
from sqlalchemy import text

revision: str = "0118_guild_travel_credentials"
down_revision: str = "0117_guild_crossframe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS guild_travel_credentials (
            id            VARCHAR(40) PRIMARY KEY,
            order_id      VARCHAR(40) NOT NULL,
            host_registry VARCHAR(300) NOT NULL,
            worker_did    VARCHAR(120) NOT NULL,
            poster_did    VARCHAR(120) NOT NULL,
            stars         INTEGER,
            bounty        NUMERIC(30, 10),
            currency      VARCHAR(12),
            bundle        JSONB NOT NULL,
            pubkey_id     VARCHAR(32),
            verified      BOOLEAN NOT NULL DEFAULT FALSE,
            received_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uix_gtc_host_order UNIQUE (host_registry, order_id)
        )
    """))
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_gtc_worker ON guild_travel_credentials (worker_did, received_at DESC)"))


def downgrade() -> None:
    pass
