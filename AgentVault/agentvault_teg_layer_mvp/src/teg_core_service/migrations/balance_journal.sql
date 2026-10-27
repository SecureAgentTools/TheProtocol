-- §pass73.3.19 L1 — Complete, bypass-proof balance-change journal (CQRS transactional outbox source).
-- Source of truth for an agent's balances = agent_teg_profiles.token_balance (liquid) + .locked_balance.
-- An AFTER INSERT/UPDATE trigger records EVERY change to those columns, so the journal is complete by
-- construction — no application path among the ~40 scattered balance-mutation call sites can bypass it.
-- L2 (outbox emitter) tails unemitted rows, groups by `txid` (= one atomic TEG transaction), and emits
-- exactly one counted ES `LedgerBalanceChanged` event per group; the ES projection conserves supply via
-- the per-txid net (net>0=issuance, net<0=destruction, net==0=transfer/stake/fee). See
-- sessionlogs2026/DESIGN_2026-05-29_AAA_BALANCE_INTEGRITY_CQRS_OUTBOX.md.
-- Idempotent: safe to re-run on every TEG startup (mirrors the EventStore materialized_balances.sql pattern).

CREATE TABLE IF NOT EXISTS balance_ledger_journal (
    id            BIGSERIAL PRIMARY KEY,
    agent_id      VARCHAR(255)   NOT NULL,
    -- txid_current() of the mutating transaction. Every agent_teg_profiles row changed inside one atomic
    -- TEG operation (e.g. transfer: sender + receiver + fee_collector) shares this txid → L2 groups by it.
    txid          BIGINT,
    changed_at    TIMESTAMPTZ    NOT NULL DEFAULT now(),
    -- Match agent_teg_profiles precision EXACTLY (NUMERIC(36,18)) so the journal — and therefore the
    -- ES projection fed by it — mirrors TEG with ZERO rounding drift (no designed-in tolerance).
    delta_liquid  NUMERIC(36, 18) NOT NULL DEFAULT 0,
    delta_locked  NUMERIC(36, 18) NOT NULL DEFAULT 0,
    new_liquid    NUMERIC(36, 18) NOT NULL,
    new_locked    NUMERIC(36, 18) NOT NULL DEFAULT 0,
    -- Best-effort semantic tag (audit/debug only — completeness + supply classification do NOT depend on it).
    entry_type    VARCHAR(48)    NOT NULL DEFAULT 'unknown',
    entry_ref     VARCHAR(160),
    counterparty  VARCHAR(255),
    -- L2 outbox marker: NULL until the emitter has projected this row's group into the ES read model.
    emitted_at    TIMESTAMPTZ
);

-- Forward-compat: add txid to a journal table created by the pre-txid version of this file.
ALTER TABLE balance_ledger_journal ADD COLUMN IF NOT EXISTS txid BIGINT;
-- Forward-compat: widen deltas from the original NUMERIC(30,6) to match TEG's NUMERIC(36,18) (idempotent).
ALTER TABLE balance_ledger_journal
    ALTER COLUMN delta_liquid TYPE NUMERIC(36, 18),
    ALTER COLUMN delta_locked TYPE NUMERIC(36, 18),
    ALTER COLUMN new_liquid   TYPE NUMERIC(36, 18),
    ALTER COLUMN new_locked   TYPE NUMERIC(36, 18);

CREATE INDEX IF NOT EXISTS ix_blj_agent      ON balance_ledger_journal(agent_id);
CREATE INDEX IF NOT EXISTS ix_blj_unemitted  ON balance_ledger_journal(id) WHERE emitted_at IS NULL;
CREATE INDEX IF NOT EXISTS ix_blj_changed    ON balance_ledger_journal(changed_at);
CREATE INDEX IF NOT EXISTS ix_blj_txid       ON balance_ledger_journal(txid);

CREATE OR REPLACE FUNCTION teg_journal_balance_change() RETURNS TRIGGER AS $$
DECLARE
    old_liquid NUMERIC(36, 18);
    old_locked NUMERIC(36, 18);
    dl NUMERIC(36, 18);
    dk NUMERIC(36, 18);
BEGIN
    IF TG_OP = 'INSERT' THEN
        old_liquid := 0;
        old_locked := 0;
    ELSE
        old_liquid := COALESCE(OLD.token_balance, 0);
        old_locked := COALESCE(OLD.locked_balance, 0);
    END IF;
    dl := COALESCE(NEW.token_balance, 0)  - old_liquid;
    dk := COALESCE(NEW.locked_balance, 0) - old_locked;
    -- Only journal real balance movements (skip reputation-only updates, zero-balance inserts, etc.).
    IF dl = 0 AND dk = 0 THEN
        RETURN NEW;
    END IF;
    INSERT INTO balance_ledger_journal
        (agent_id, txid, delta_liquid, delta_locked, new_liquid, new_locked, entry_type, entry_ref, counterparty)
    VALUES
        (NEW.agent_id, txid_current(), dl, dk,
         COALESCE(NEW.token_balance, 0), COALESCE(NEW.locked_balance, 0),
         COALESCE(NULLIF(current_setting('teg.entry_type', true), ''), 'unknown'),
         NULLIF(current_setting('teg.entry_ref', true), ''),
         NULLIF(current_setting('teg.counterparty', true), ''));
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- AFTER INSERT OR UPDATE: INSERT captures initial funding of a brand-new profile (OLD treated as 0).
-- No WHEN clause (it cannot reference OLD on INSERT); the dl=0 AND dk=0 short-circuit handles no-op updates.
DROP TRIGGER IF EXISTS trg_teg_journal_balance_change ON agent_teg_profiles;
CREATE TRIGGER trg_teg_journal_balance_change
    AFTER INSERT OR UPDATE ON agent_teg_profiles
    FOR EACH ROW
    EXECUTE FUNCTION teg_journal_balance_change();
