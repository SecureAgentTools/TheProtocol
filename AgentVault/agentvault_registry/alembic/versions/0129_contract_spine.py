"""0129 — THE CONTRACT SPINE (2026-07-25).

Contracts become the durable, escrowed, milestoned AGREEMENT primitive that every origination
surface (direct, agent discovery, THE GUILD, templates) mints into — replacing the RUC
(`refactoring_upgrade_contracts`), which never escrowed (money was first touched at
approve-completion, AFTER the work), had no currency/deadline/cancel/expiry and integer-only money.

**Δ-irrelevant tables**: money NEVER lives here — it is escrowed on the TEG treasury via the shared
rail (`services/escrow.py`, `ctrref:{id}:{leg}` legs), so every leg is a zero-sum move and the
supply invariant is untouched. `total_amount >= 0`: zero = AGREEMENT-ONLY (MOU/NDA/framework form,
full lifecycle, no escrow legs at all — institutional scale, §P4.5).

Also migrates the ~15 fleet-wide RUC rows in as `origin_surface='legacy'` history (terminal rows
keep their outcome; non-terminal rows carry NO escrow — release refuses on them, see router) and
adds `contract_ref` to a2a_payment_authorizations + disputes (additive; the legacy int columns stay).

IDEMPOTENT — replays every boot via migration_bridge. All DDL IF NOT EXISTS / ON CONFLICT. Chains 0128.
"""
import os

from alembic import op
from sqlalchemy import text

revision: str = "0129_contract_spine"
down_revision: str = "0128_peer_reachability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS contracts (
            id                  VARCHAR(40) PRIMARY KEY,          -- ctr_<hex> (ctr_l… = migrated RUC)
            legacy_ruc_id       INTEGER UNIQUE,                   -- adapter lookups by old int id
            contract_type       VARCHAR(32)  NOT NULL DEFAULT 'work_order',
            origin_surface      VARCHAR(24)  NOT NULL DEFAULT 'direct',
            origin_ref          VARCHAR(80),
            client_did          VARCHAR(120) NOT NULL,
            provider_did        VARCHAR(120),
            payee_did           VARCHAR(120),
            payee_org_id        VARCHAR(64),
            title               VARCHAR(200) NOT NULL,
            terms               JSONB,
            currency            VARCHAR(12)  NOT NULL,
            total_amount        NUMERIC(30,10) NOT NULL CHECK (total_amount >= 0),
            fee_bps             INTEGER NOT NULL DEFAULT 0,
            fee_charged         NUMERIC(30,10),
            escrow_ref          VARCHAR(80),
            template_version_id VARCHAR(64),
            template_royalty_bps INTEGER,
            template_price_paid NUMERIC(30,10),
            status              VARCHAR(20) NOT NULL DEFAULT 'draft',
            deadline            TIMESTAMPTZ,
            offer_expires_at    TIMESTAMPTZ,
            dispute_id          VARCHAR(80),
            counterparty_home_registry VARCHAR(300),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            agreed_at TIMESTAMPTZ, completed_at TIMESTAMPTZ,
            cancelled_at TIMESTAMPTZ, updated_at TIMESTAMPTZ
        )
    """))
    bind.execute(text("CREATE INDEX IF NOT EXISTS ix_contracts_client ON contracts (client_did, status)"))
    bind.execute(text("CREATE INDEX IF NOT EXISTS ix_contracts_provider ON contracts (provider_did, status)"))
    bind.execute(text("CREATE INDEX IF NOT EXISTS ix_contracts_status_deadline ON contracts (status, deadline)"))
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_contracts_offered_open ON contracts (status, created_at) WHERE status='offered'"
    ))

    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS contract_milestones (
            id            VARCHAR(48) PRIMARY KEY,                -- ctm_<hex>
            contract_id   VARCHAR(40) NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
            seq           INTEGER NOT NULL,
            title         VARCHAR(200) NOT NULL,
            terms         JSONB,
            amount        NUMERIC(30,10) NOT NULL CHECK (amount >= 0),  -- 0 = sign-off step, no legs
            status        VARCHAR(16) NOT NULL DEFAULT 'pending',
            deliverable   JSONB,
            due_at TIMESTAMPTZ, submitted_at TIMESTAMPTZ, released_at TIMESTAMPTZ,
            CONSTRAINT uq_contract_milestone_seq UNIQUE (contract_id, seq)
        )
    """))
    bind.execute(text("CREATE INDEX IF NOT EXISTS ix_contract_milestones_cid ON contract_milestones (contract_id, status)"))

    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS contract_events (
            id BIGSERIAL PRIMARY KEY,
            contract_id VARCHAR(40) NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
            seq INTEGER NOT NULL,
            event_type VARCHAR(32) NOT NULL,
            actor_did VARCHAR(120),
            payload JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))
    bind.execute(text("CREATE INDEX IF NOT EXISTS ix_contract_events_cid ON contract_events (contract_id, seq)"))

    # Adapter id continuity: new contracts created via the LEGACY routes get an int id from this
    # sequence so ContractResponse.id stays honest. Never decreases on replay.
    bind.execute(text("CREATE SEQUENCE IF NOT EXISTS contracts_legacy_id_seq START 1000"))
    bind.execute(text("""
        SELECT setval('contracts_legacy_id_seq', GREATEST(
            (SELECT COALESCE(MAX(id),0)+1000 FROM refactoring_upgrade_contracts),
            (SELECT last_value FROM contracts_legacy_id_seq)))
    """))

    # New references write contract_ref (VARCHAR ctr id); legacy int columns stay untouched.
    bind.execute(text("ALTER TABLE a2a_payment_authorizations ADD COLUMN IF NOT EXISTS contract_ref VARCHAR(40)"))
    bind.execute(text("ALTER TABLE disputes ADD COLUMN IF NOT EXISTS contract_ref VARCHAR(40)"))

    # ── one-way RUC history migration (deterministic ids ⇒ replay-safe) ─────────────────────────
    ccy = (os.getenv("FRAME_CURRENCY", "AVT") or "AVT").strip().upper() or "AVT"
    bind.execute(text("""
        INSERT INTO contracts (id, legacy_ruc_id, contract_type, origin_surface, client_did,
                               provider_did, title, terms, currency, total_amount, fee_bps,
                               status, created_at, agreed_at, completed_at, updated_at)
        SELECT 'ctr_l' || lpad(r.id::text, 8, '0'),
               r.id, 'work_order', 'legacy', r.client_agent_did, r.upgrader_agent_did,
               left('RUC #' || r.id::text || ': ' || r.scope_description, 200),
               jsonb_build_object(
                   'scope_description', r.scope_description,
                   'repo_url', r.source_code_repo_url,
                   'branch', r.source_code_branch,
                   'acceptance_criteria', r.acceptance_criteria,
                   'pr_url', r.pr_url,
                   'access_credentials_id', r.access_credentials_id,
                   'legacy_payment_transaction_id', r.payment_transaction_id),
               :ccy, r.payment_amount, 0,
               CASE r.status WHEN 'PROPOSED' THEN 'offered'
                             WHEN 'ACCEPTED' THEN 'agreed'
                             WHEN 'IN_PROGRESS' THEN 'in_progress'
                             WHEN 'PENDING_MERGE' THEN 'in_progress'
                             WHEN 'COMPLETED' THEN 'completed'
                             WHEN 'FAILED' THEN 'cancelled'
                             WHEN 'DISPUTED' THEN 'disputed'
                             ELSE 'cancelled' END,
               r.created_at, r.accepted_at, r.completed_at, r.updated_at
        FROM refactoring_upgrade_contracts r
        ON CONFLICT (id) DO NOTHING
    """), {"ccy": ccy})
    bind.execute(text("""
        INSERT INTO contract_milestones (id, contract_id, seq, title, amount, status,
                                         deliverable, submitted_at, released_at)
        SELECT 'ctm_l' || lpad(r.id::text, 8, '0') || '_1',
               'ctr_l' || lpad(r.id::text, 8, '0'), 1, 'Full delivery', r.payment_amount,
               CASE r.status WHEN 'COMPLETED' THEN 'released'
                             WHEN 'PENDING_MERGE' THEN 'submitted'
                             WHEN 'FAILED' THEN 'cancelled'
                             WHEN 'DISPUTED' THEN 'rejected'
                             ELSE 'pending' END,
               CASE WHEN r.pr_url IS NOT NULL THEN jsonb_build_object('pr_url', r.pr_url) END,
               CASE WHEN r.status IN ('PENDING_MERGE','COMPLETED') THEN r.updated_at END,
               CASE WHEN r.status = 'COMPLETED' THEN r.completed_at END
        FROM refactoring_upgrade_contracts r
        ON CONFLICT (id) DO NOTHING
    """))


def downgrade() -> None:
    # Additive-only doctrine: tables stay on rollback (feedback_registry_rollback_alembic_downgrade_crash).
    pass
