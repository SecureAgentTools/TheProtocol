"""0119 — GUILD v2: remote money lifts (2026-07-08).

Additive-only. Lifts the three v1 cross-registry guards, all on EXISTING rails (Δ=0):
  • STAKED REMOTE BIDS — collateral is escrowed on the worker's HOME registry (their money lives
    there) via the home proxy, tracked in `guild_remote_stakes`. Host↔home lifecycle over the
    federation channel: release = home treasury→bidder payback; slash = zero legs (the deposit
    already sits in the home treasury — "slash" just never returns it). Deterrent model: the
    slashed stake stays in the worker's home treasury (v2; poster compensation = Commander/GCC).
  • REMOTE PARTIAL DISPUTE SPLITS — admin resolve stores the split (status='resolved',
    resolved_*_amt) instead of 409ing; the POSTER triggers `/dispute-payout`, whose worker leg
    rides the exact stage-through-poster xf saga verify() uses (their refund share is held until
    they trigger — incentive-aligned).
  • FIRM REMOTE BIDS — the HOME proxy validates the org (it lives there) and relays the org
    treasury payee; the host trusts the home's assertion (same trust as the identity itself)
    via `payee_did_hint`.
IDEMPOTENT (IF NOT EXISTS), chains 0118.
"""
from alembic import op
from sqlalchemy import text

revision: str = "0119_guild_v2_remote_money"
down_revision: str = "0118_guild_travel_credentials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # remote dispute split held amounts (status='resolved' until the poster triggers payout)
    bind.execute(text("ALTER TABLE guild_work_orders ADD COLUMN IF NOT EXISTS resolved_worker_amt NUMERIC(30,10)"))
    bind.execute(text("ALTER TABLE guild_work_orders ADD COLUMN IF NOT EXISTS resolved_poster_amt NUMERIC(30,10)"))
    # firm-remote: home-validated org treasury payee, asserted with the federated bid
    bind.execute(text("ALTER TABLE guild_bids ADD COLUMN IF NOT EXISTS payee_did_hint VARCHAR(120)"))
    # HOME-side ledger of collateral locked for tasks hosted on peers
    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS guild_remote_stakes (
            id            VARCHAR(40) PRIMARY KEY,
            order_id      VARCHAR(40) NOT NULL,
            host_registry VARCHAR(300) NOT NULL,
            bidder_did    VARCHAR(120) NOT NULL,
            amount        NUMERIC(30,10) NOT NULL,
            status        VARCHAR(12) NOT NULL DEFAULT 'held',
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            resolved_at   TIMESTAMPTZ,
            CONSTRAINT uix_grs_host_order_bidder UNIQUE (host_registry, order_id, bidder_did)
        )
    """))
    bind.execute(text("CREATE INDEX IF NOT EXISTS idx_grs_held ON guild_remote_stakes (status, created_at)"))


def downgrade() -> None:
    pass
