-- Materialized Balance Table — Phase 1 Scaling
-- Updated by trigger on every event INSERT, providing O(1) balance lookups
-- Idempotent: safe to re-run on every startup (IF NOT EXISTS, ON CONFLICT DO NOTHING)

CREATE TABLE IF NOT EXISTS materialized_balances (
    agent_did VARCHAR(255) PRIMARY KEY,
    -- §pass73.3.19: match TEG agent_teg_profiles precision (NUMERIC(36,18)) so the projection mirrors
    -- TEG with ZERO rounding drift — eliminates the designed-in 6-vs-18 decimal tolerance.
    liquid_balance NUMERIC(36, 18) NOT NULL DEFAULT 0,
    staked_balance NUMERIC(36, 18) NOT NULL DEFAULT 0,
    event_count INTEGER NOT NULL DEFAULT 0,
    last_event_id UUID,
    last_event_timestamp TIMESTAMPTZ,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Supply tracking table (singleton row)
CREATE TABLE IF NOT EXISTS supply_summary (
    id INTEGER PRIMARY KEY DEFAULT 1,
    tokens_issued NUMERIC(36, 18) NOT NULL DEFAULT 0,
    tokens_destroyed NUMERIC(36, 18) NOT NULL DEFAULT 0,
    tokens_fees_collected NUMERIC(36, 18) NOT NULL DEFAULT 0,
    tokens_minted_compensation NUMERIC(36, 18) NOT NULL DEFAULT 0,
    total_events INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CHECK (id = 1)
);

-- Initialize supply summary singleton
INSERT INTO supply_summary (id) VALUES (1) ON CONFLICT DO NOTHING;

-- §pass73.3.19 — single-writer cutover flag (CQRS outbox). When single_writer=true, LedgerBalanceChanged
-- (emitted by the TEG L2 balance outbox) is the SOLE balance writer; legacy typed balance events become
-- audit-only (recorded, not projected) so they can't double-count. Flip per-frame as a reversible data
-- change WITH the re-baseline + outbox enable. Default false = legacy behavior (no-op until cutover).
CREATE TABLE IF NOT EXISTS projection_config (
    id INTEGER PRIMARY KEY DEFAULT 1,
    single_writer BOOLEAN NOT NULL DEFAULT false,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CHECK (id = 1)
);
INSERT INTO projection_config (id, single_writer) VALUES (1, false) ON CONFLICT DO NOTHING;

-- §LEDGERGATE E (2026-10-11): an agent whose PROJECTED balance is below zero, said instead of hidden. The TEG cannot
-- persist a negative (row locks, the sufficiency check, its CHECK constraints), and the projection still applies every
-- event (the ledger is append-only), so under one writer a negative here means an earlier balance change of that agent
-- has not landed yet: the agent is BEHIND, or (if the TEG has nothing left to send for it) the projection broke.
--   materialized_balances.negative_since  set by the same upsert that applies the delta (it cannot fail on its own,
--                                         so it can never stop an event from being stored); NULL again when the
--                                         balance is back at or above zero
--   projection_negative_log               one row when an agent GOES below zero (never per event while it stays
--                                         there), written in its own guarded block: a failure logs a warning
-- The auditor reads both and asks the TEG whether rows for the agent are still waiting (behind) or not (a breach);
-- the metrics exporter counts them. Δ-NEUTRAL: nothing here changes a balance or the supply summary.
ALTER TABLE materialized_balances ADD COLUMN IF NOT EXISTS negative_since TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS ix_materialized_balances_negative
    ON materialized_balances(negative_since) WHERE negative_since IS NOT NULL;
CREATE TABLE IF NOT EXISTS projection_negative_log (
    id BIGSERIAL PRIMARY KEY,
    agent_did VARCHAR(255) NOT NULL,
    frame VARCHAR(128),
    event_id UUID,
    liquid_after NUMERIC(36, 18),
    staked_after NUMERIC(36, 18),
    at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_projection_negative_log_at ON projection_negative_log(at DESC);

-- §pass73.3.19 — widen existing tables from NUMERIC(30,6) to (36,18) to match TEG precision (idempotent).
ALTER TABLE materialized_balances
    ALTER COLUMN liquid_balance TYPE NUMERIC(36, 18),
    ALTER COLUMN staked_balance TYPE NUMERIC(36, 18);
ALTER TABLE supply_summary
    ALTER COLUMN tokens_issued TYPE NUMERIC(36, 18),
    ALTER COLUMN tokens_destroyed TYPE NUMERIC(36, 18),
    ALTER COLUMN tokens_fees_collected TYPE NUMERIC(36, 18),
    ALTER COLUMN tokens_minted_compensation TYPE NUMERIC(36, 18);

-- §B (2026-05-30): transit_net — signed accumulator for the NON-supply portion of each
-- LedgerBalanceChanged net (transfers, stakes, fees, and cross-frame / cross-TEG legs whose
-- debit and credit settle in separate txids → separate single-sided events). It lets
-- tokens_issued / tokens_destroyed track REAL mint / burn only, while the per-frame supply
-- invariant stays true by construction:
--   tokens_issued − tokens_destroyed + transit_net = Σ(liquid + staked)
-- transit_net ≈ 0 for purely intra-frame activity (debit & credit legs cancel) and equals the
-- net cross-frame flow otherwise. Idempotent add; default 0 = pre-§B behavior until re-baseline.
ALTER TABLE supply_summary ADD COLUMN IF NOT EXISTS transit_net NUMERIC(36, 18) NOT NULL DEFAULT 0;

-- Index for fast lookups by update time
CREATE INDEX IF NOT EXISTS idx_materialized_balances_updated
    ON materialized_balances(updated_at DESC);

-- Trigger function that processes each new event and updates balances
-- Handles: TokensIssued, TokensTransferred, TokensStaked, TokensUnstaked,
--          RewardsAutoCompounded, TransactionFeeCollected, DisputeSlash,
--          DisputeCompensationMinted, BalanceCorrected
-- Skipped: RewardsDistributed, CrossRegistryTransferCompleted (skip_in_projection)
CREATE OR REPLACE FUNCTION update_materialized_balances() RETURNS TRIGGER AS $$
DECLARE
    evt_type TEXT;
    evt_data JSONB;
    agent_id TEXT;
    amount NUMERIC(36, 18);
    from_agent TEXT;
    to_agent TEXT;
    fee_amount NUMERIC(36, 18);
    lock_did TEXT;
    -- Namespace 42002 is reserved for this trigger's per-agent advisory locks.
    -- 42001 is held by main.py's DDL serialisation path. Do not collide.
    lock_ns CONSTANT INTEGER := 42002;
    -- §pass73.3.19 — single-writer cutover + LedgerBalanceChanged (L2 CQRS outbox) locals
    sw BOOLEAN;
    led_entry JSONB;
    led_did TEXT;
    led_dl NUMERIC(36, 18);
    led_ds NUMERIC(36, 18);
    led_net NUMERIC(36, 18) := 0;
    led_kind TEXT;  -- §B: transaction kind from the L2 outbox (mint/dispute_comp/slash/...) → supply classification
    -- §LEDGERGATE E: the row after the delta (a projection below zero is marked, never refused)
    nb_l NUMERIC(36, 18);
    nb_s NUMERIC(36, 18);
    nb_since TIMESTAMPTZ;
BEGIN
    evt_type := NEW.event_type;
    evt_data := NEW.data;
    agent_id := NEW.aggregate_id;

    -- §pass73.3.19 — LedgerBalanceChanged is the SINGLE balance writer (TEG L2 outbox). Its `entries`
    -- carry per-agent (delta_liquid, delta_staked) for one atomic TEG transaction (one txid). Supply is
    -- conserved by the per-txid net: net>0 → issuance, net<0 → destruction, net==0 → transfer/stake/fee.
    -- This branch is always active (the event only exists post-cutover); it never double-counts because
    -- the legacy typed events are gated off below when single_writer=true.
    IF evt_type = 'LedgerBalanceChanged' THEN
        FOR led_entry IN SELECT * FROM jsonb_array_elements(COALESCE(evt_data->'entries', '[]'::jsonb))
        LOOP
            led_did := led_entry->>'agent_did';
            IF led_did IS NULL THEN CONTINUE; END IF;
            -- §MONEY-NS (2026-09-04): SYSTEM accounts are PER-TEG SINGLETONS, not global
            -- identities. This EventStore is fed by the balance outbox of SIX TEGs (this
            -- frame plus its cloud operators, which have no EventStore of their own), and
            -- every one of them emits `teg:system:fee_collector` and
            -- `did:theprotocol:teg_system_treasury` as the SAME literal — so six accounts
            -- collapsed into one projected row. Agent DIDs are global and MUST keep
            -- aggregating (an agent's frame-wide holdings across TEGs is the right answer);
            -- only system singletons are keyed per emitter.
            --
            -- The emitter is already in the event: balance_outbox stamps "frame": TEG_ID.
            -- No producer change was needed for this.
            --
            -- ⚠ Δ-NEUTRAL: this only changes WHICH row a delta lands in, never the amount,
            -- so SUM(liquid+staked) — and therefore total_circulating and delta — is
            -- untouched. ⚠ And it is only HALF the fix: without the one-off seeded split
            -- (scripts/es_namespace_system_accounts.py) the six new rows start at ZERO and
            -- are delta-only again, which is precisely the condition that produced 74
            -- negative balances by 2026-09-04.
            IF left(led_did, 11) = 'teg:system:'
               OR left(led_did, 27) = 'did:theprotocol:teg_system_' THEN
                led_did := led_did || '@' || COALESCE(NULLIF(evt_data->>'frame', ''), 'unknown-frame');
            END IF;
            led_dl := COALESCE((led_entry->>'delta_liquid')::numeric, 0);
            led_ds := COALESCE((led_entry->>'delta_staked')::numeric, 0);
            PERFORM pg_advisory_xact_lock(lock_ns, hashtext(led_did));
            INSERT INTO materialized_balances (agent_did, liquid_balance, staked_balance, event_count, last_event_id, last_event_timestamp, updated_at, negative_since)
            VALUES (led_did, led_dl, led_ds, 1, NEW.id, NEW.timestamp, NOW(),
                    CASE WHEN led_dl < 0 OR led_ds < 0 THEN NOW() END)
            ON CONFLICT (agent_did) DO UPDATE SET
                liquid_balance = materialized_balances.liquid_balance + led_dl,
                staked_balance = materialized_balances.staked_balance + led_ds,
                event_count = materialized_balances.event_count + 1,
                last_event_id = NEW.id,
                last_event_timestamp = NEW.timestamp,
                updated_at = NOW(),
                -- §LEDGERGATE E: below zero after this delta → since when (kept while it stays there); else NULL
                negative_since = CASE
                    WHEN materialized_balances.liquid_balance + led_dl < 0
                      OR materialized_balances.staked_balance + led_ds < 0
                    THEN COALESCE(materialized_balances.negative_since, NOW())
                    ELSE NULL END
            RETURNING liquid_balance, staked_balance, negative_since INTO nb_l, nb_s, nb_since;
            -- §LEDGERGATE E: the moment an agent GOES below zero (its mark was set by this very statement), logged once
            IF nb_since IS NOT NULL AND nb_since = NOW() THEN
                BEGIN
                    INSERT INTO projection_negative_log (agent_did, frame, event_id, liquid_after, staked_after)
                    VALUES (left(led_did, 255), left(NULLIF(evt_data->>'frame', ''), 128), NEW.id, nb_l, nb_s);
                EXCEPTION WHEN OTHERS THEN
                    RAISE WARNING 'projection_negative_log: % (the event is stored, only this note is lost)', SQLERRM;
                END;
            END IF;
            led_net := led_net + led_dl + led_ds;
        END LOOP;
        -- §B (2026-05-30): classify by transaction KIND (emitted by the L2 outbox from the
        -- journal entry_type) so tokens_issued/tokens_destroyed track REAL mint/burn only.
        -- A transfer whose debit and credit settle in separate txids arrives as two
        -- single-sided events; pre-§B the debit half was booked "destroyed" and the credit
        -- half "issued", inflating both with transfer volume. Now only genuine mint/burn move
        -- those counters; everything else (transfers, stakes, fees, cross-frame legs, and any
        -- untagged 'unknown') accumulates in transit_net. Invariant holds by construction:
        --   tokens_issued − tokens_destroyed + transit_net = Σ(liquid+staked)  →  Δ = 0.
        led_kind := COALESCE(evt_data->>'kind', 'unknown');
        IF led_kind IN ('mint', 'dispute_comp') THEN
            UPDATE supply_summary SET tokens_issued = tokens_issued + led_net, updated_at = NOW() WHERE id = 1;
        ELSIF led_kind IN ('slash', 'burn') THEN
            UPDATE supply_summary SET tokens_destroyed = tokens_destroyed + ABS(led_net), updated_at = NOW() WHERE id = 1;
        ELSE
            UPDATE supply_summary SET transit_net = transit_net + led_net, updated_at = NOW() WHERE id = 1;
        END IF;
        RETURN NEW;
    END IF;

    -- Single-writer cutover gate: when flipped (projection_config.single_writer=true), legacy balance
    -- events are audit-only (recorded, not projected) → no double-count with the L2 outbox.
    -- Default false → the legacy CASE below runs exactly as before (safe additive deploy).
    SELECT single_writer INTO sw FROM projection_config WHERE id = 1;
    IF sw THEN
        RETURN NEW;
    END IF;

    CASE evt_type
        WHEN 'TokensIssued' THEN
            amount := COALESCE((evt_data->>'amount')::numeric, 0);
            PERFORM pg_advisory_xact_lock(lock_ns, hashtext(agent_id));
            INSERT INTO materialized_balances (agent_did, liquid_balance, event_count, last_event_id, last_event_timestamp, updated_at)
            VALUES (agent_id, amount, 1, NEW.id, NEW.timestamp, NOW())
            ON CONFLICT (agent_did) DO UPDATE SET
                liquid_balance = materialized_balances.liquid_balance + amount,
                event_count = materialized_balances.event_count + 1,
                last_event_id = NEW.id,
                last_event_timestamp = NEW.timestamp,
                updated_at = NOW();
            -- Supply invariant: only TokensIssued updates tokens_issued (0.004% of events)
            UPDATE supply_summary SET
                tokens_issued = tokens_issued + amount,
                updated_at = NOW()
            WHERE id = 1;

        WHEN 'TokensTransferred' THEN
            amount := COALESCE((evt_data->>'amount')::numeric, 0);
            from_agent := evt_data->>'from';
            to_agent := evt_data->>'to';

            -- Acquire advisory locks on (from_agent, to_agent) in sorted order.
            -- Prevents the alice→bob vs bob→alice deadlock cycle.
            FOR lock_did IN
                SELECT d FROM unnest(ARRAY[from_agent, to_agent]) d
                WHERE d IS NOT NULL ORDER BY d
            LOOP
                PERFORM pg_advisory_xact_lock(lock_ns, hashtext(lock_did));
            END LOOP;

            -- Debit sender
            IF from_agent IS NOT NULL THEN
                INSERT INTO materialized_balances (agent_did, liquid_balance, event_count, last_event_id, last_event_timestamp, updated_at)
                VALUES (from_agent, -amount, 1, NEW.id, NEW.timestamp, NOW())
                ON CONFLICT (agent_did) DO UPDATE SET
                    liquid_balance = materialized_balances.liquid_balance - amount,
                    event_count = materialized_balances.event_count + 1,
                    last_event_id = NEW.id,
                    last_event_timestamp = NEW.timestamp,
                    updated_at = NOW();
            END IF;

            -- Credit receiver
            IF to_agent IS NOT NULL THEN
                INSERT INTO materialized_balances (agent_did, liquid_balance, event_count, last_event_id, last_event_timestamp, updated_at)
                VALUES (to_agent, amount, 1, NEW.id, NEW.timestamp, NOW())
                ON CONFLICT (agent_did) DO UPDATE SET
                    liquid_balance = materialized_balances.liquid_balance + amount,
                    event_count = materialized_balances.event_count + 1,
                    last_event_id = NEW.id,
                    last_event_timestamp = NEW.timestamp,
                    updated_at = NOW();
            END IF;

            -- No supply_summary update: transfers are zero-sum

        WHEN 'TokensStaked' THEN
            amount := COALESCE((evt_data->>'amount')::numeric, 0);
            PERFORM pg_advisory_xact_lock(lock_ns, hashtext(agent_id));
            INSERT INTO materialized_balances (agent_did, liquid_balance, staked_balance, event_count, last_event_id, last_event_timestamp, updated_at)
            VALUES (agent_id, -amount, amount, 1, NEW.id, NEW.timestamp, NOW())
            ON CONFLICT (agent_did) DO UPDATE SET
                liquid_balance = materialized_balances.liquid_balance - amount,
                staked_balance = materialized_balances.staked_balance + amount,
                event_count = materialized_balances.event_count + 1,
                last_event_id = NEW.id,
                last_event_timestamp = NEW.timestamp,
                updated_at = NOW();

        WHEN 'TokensUnstaked' THEN
            amount := COALESCE((evt_data->>'amount')::numeric, 0);
            PERFORM pg_advisory_xact_lock(lock_ns, hashtext(agent_id));
            INSERT INTO materialized_balances (agent_did, liquid_balance, staked_balance, event_count, last_event_id, last_event_timestamp, updated_at)
            VALUES (agent_id, amount, -amount, 1, NEW.id, NEW.timestamp, NOW())
            ON CONFLICT (agent_did) DO UPDATE SET
                liquid_balance = materialized_balances.liquid_balance + amount,
                staked_balance = materialized_balances.staked_balance - amount,
                event_count = materialized_balances.event_count + 1,
                last_event_id = NEW.id,
                last_event_timestamp = NEW.timestamp,
                updated_at = NOW();

        WHEN 'RewardsAutoCompounded' THEN
            amount := COALESCE((evt_data->>'amount')::numeric, 0);
            PERFORM pg_advisory_xact_lock(lock_ns, hashtext(agent_id));
            -- f037 fix: the preceding TokensIssued event already added `amount` to liquid_balance.
            -- Auto-compound MOVES that amount from liquid to staked, so we subtract from liquid.
            -- Net effect: total_circulating += amount (matches tokens_issued increment). Delta stays 0.
            INSERT INTO materialized_balances (agent_did, liquid_balance, staked_balance, event_count, last_event_id, last_event_timestamp, updated_at)
            VALUES (agent_id, -amount, amount, 1, NEW.id, NEW.timestamp, NOW())
            ON CONFLICT (agent_did) DO UPDATE SET
                liquid_balance = materialized_balances.liquid_balance - amount,
                staked_balance = materialized_balances.staked_balance + amount,
                event_count = materialized_balances.event_count + 1,
                last_event_id = NEW.id,
                last_event_timestamp = NEW.timestamp,
                updated_at = NOW();

        WHEN 'TransactionFeeCollected' THEN
            fee_amount := COALESCE((evt_data->>'fee_amount')::numeric, (evt_data->>'amount')::numeric, 0);

            -- Lock-free path (2026-05-02): rely on ON CONFLICT DO UPDATE
            -- row-level locking. Both INSERTs target distinct rows (sender
            -- vs fee_collector) in deterministic order — no deadlock cycle
            -- possible. Removing the advisory_xact_lock acquisition eliminates
            -- the universal contention on hashtext('teg:system:fee_collector')
            -- that had been the cluster TX/s ceiling under saturation.

            -- Debit fee from the aggregate (sender) — already reflected in TokensTransferred
            -- but the fee itself goes to fee_collector as liquid balance
            INSERT INTO materialized_balances (agent_did, liquid_balance, event_count, last_event_id, last_event_timestamp, updated_at)
            VALUES (agent_id, -fee_amount, 1, NEW.id, NEW.timestamp, NOW())
            ON CONFLICT (agent_did) DO UPDATE SET
                liquid_balance = materialized_balances.liquid_balance - fee_amount,
                event_count = materialized_balances.event_count + 1,
                last_event_id = NEW.id,
                last_event_timestamp = NEW.timestamp,
                updated_at = NOW();
            -- Credit fee collector
            INSERT INTO materialized_balances (agent_did, liquid_balance, event_count, last_event_id, last_event_timestamp, updated_at)
            VALUES ('teg:system:fee_collector', fee_amount, 1, NEW.id, NEW.timestamp, NOW())
            ON CONFLICT (agent_did) DO UPDATE SET
                liquid_balance = materialized_balances.liquid_balance + fee_amount,
                event_count = materialized_balances.event_count + 1,
                last_event_id = NEW.id,
                last_event_timestamp = NEW.timestamp,
                updated_at = NOW();
            -- fees are zero-sum (deducted from sender, credited to fee_collector)
            -- tokens_fees_collected tracked lazily, not in hot path

        WHEN 'DisputeSlash' THEN
            amount := COALESCE((evt_data->>'amount')::numeric, 0);
            PERFORM pg_advisory_xact_lock(lock_ns, hashtext(agent_id));
            INSERT INTO materialized_balances (agent_did, liquid_balance, event_count, last_event_id, last_event_timestamp, updated_at)
            VALUES (agent_id, -amount, 1, NEW.id, NEW.timestamp, NOW())
            ON CONFLICT (agent_did) DO UPDATE SET
                liquid_balance = materialized_balances.liquid_balance - amount,
                event_count = materialized_balances.event_count + 1,
                last_event_id = NEW.id,
                last_event_timestamp = NEW.timestamp,
                updated_at = NOW();
            UPDATE supply_summary SET
                tokens_destroyed = tokens_destroyed + amount,
                updated_at = NOW()
            WHERE id = 1;

        WHEN 'DisputeCompensationMinted' THEN
            amount := COALESCE((evt_data->>'amount')::numeric, 0);
            PERFORM pg_advisory_xact_lock(lock_ns, hashtext(agent_id));
            INSERT INTO materialized_balances (agent_did, liquid_balance, event_count, last_event_id, last_event_timestamp, updated_at)
            VALUES (agent_id, amount, 1, NEW.id, NEW.timestamp, NOW())
            ON CONFLICT (agent_did) DO UPDATE SET
                liquid_balance = materialized_balances.liquid_balance + amount,
                event_count = materialized_balances.event_count + 1,
                last_event_id = NEW.id,
                last_event_timestamp = NEW.timestamp,
                updated_at = NOW();
            UPDATE supply_summary SET
                tokens_minted_compensation = tokens_minted_compensation + amount,
                updated_at = NOW()
            WHERE id = 1;

        WHEN 'BalanceCorrected' THEN
            amount := COALESCE((evt_data->>'adjustment')::numeric, (evt_data->>'amount')::numeric, 0);
            PERFORM pg_advisory_xact_lock(lock_ns, hashtext(agent_id));
            INSERT INTO materialized_balances (agent_did, liquid_balance, event_count, last_event_id, last_event_timestamp, updated_at)
            VALUES (agent_id, amount, 1, NEW.id, NEW.timestamp, NOW())
            ON CONFLICT (agent_did) DO UPDATE SET
                liquid_balance = materialized_balances.liquid_balance + amount,
                event_count = materialized_balances.event_count + 1,
                last_event_id = NEW.id,
                last_event_timestamp = NEW.timestamp,
                updated_at = NOW();
            -- Positive corrections count as issued; negative as destroyed
            IF amount > 0 THEN
                UPDATE supply_summary SET tokens_issued = tokens_issued + amount, updated_at = NOW() WHERE id = 1;
            ELSE
                UPDATE supply_summary SET tokens_destroyed = tokens_destroyed + ABS(amount), updated_at = NOW() WHERE id = 1;
            END IF;

        ELSE
            -- Other event types (A2APayment*, CrossRegistryTransferCompleted, RewardsDistributed,
            -- ReputationChanged, etc.): no balance or supply impact — skip entirely
            NULL;
    END CASE;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Attach trigger to events table (AFTER INSERT, row-level)
DROP TRIGGER IF EXISTS trg_update_materialized_balances ON events;
CREATE TRIGGER trg_update_materialized_balances
    AFTER INSERT ON events
    FOR EACH ROW
    EXECUTE FUNCTION update_materialized_balances();
