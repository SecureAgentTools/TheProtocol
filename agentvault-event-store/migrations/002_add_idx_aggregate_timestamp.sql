-- §FEDEVENTS follow-up (2026-08-04): composite index events(aggregate_id, timestamp).
--
-- WHY: the windowed chain/forensics rail (registry /admin/forensics/search,
-- shipped fleet-wide in the V0169 roll) queries events by aggregate within a
-- timestamp window. Without this index the planner walks idx_timestamp and
-- filters by aggregate — measured on frame-a (~97M rows): 10,690 ms / 2.09M
-- buffers / 888,586 rows discarded for a SPARSE window that returns 0 rows,
-- i.e. past the ES 9 s statement timeout. With it: 0.145 ms / 4 buffers
-- (measured on frame-c after the build) — both predicates in the Index Cond.
--
-- DRIFT NOTE: db_models.py has declared Index("idx_aggregate_timestamp", …)
-- for some time, but startup uses Base.metadata.create_all, which NEVER
-- retrofits indexes onto an existing table — so every pre-existing deployment
-- (frame-a/b/c AND hetzner) lacked it while fresh deployments get it free.
-- This file is the retrofit for existing DBs; new deployments need nothing.
--
-- Applied ONLINE (CREATE INDEX CONCURRENTLY — no table lock, ingestion keeps
-- running; the ES container is NOT restarted for this). Safe to re-run.
-- NOTE: CONCURRENTLY cannot run inside a transaction block — run with
-- autocommit (plain psql does this per-statement by default).
--
-- Applied 2026-08-04 to: frame-c (1m32s, 12.5M rows), frame-a (~97M),
-- frame-b (~102M), hetzner-frame (instant, 309 rows).

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_aggregate_timestamp
    ON events (aggregate_id, timestamp);

-- Verify (indisvalid must be 't' — an aborted CONCURRENTLY build leaves an
-- INVALID index that must be dropped and rebuilt):
SELECT indexrelid::regclass AS index, indisvalid
FROM pg_index
WHERE indexrelid::regclass::text = 'idx_aggregate_timestamp';
