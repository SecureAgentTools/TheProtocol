-- TITANIUM VAULT D1: Add idempotency_key column to events table
-- Run this BEFORE restarting the EventStore container after code changes.
-- This adds the column to the existing table. New deployments get it via create_all().
--
-- Safe to run multiple times (IF NOT EXISTS on index).

ALTER TABLE events ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(255) NULL;

-- Unique index: prevents duplicate events with the same idempotency key.
-- NULL values are excluded from uniqueness (multiple events without keys are fine).
CREATE UNIQUE INDEX IF NOT EXISTS ix_events_idempotency_key 
    ON events (idempotency_key) 
    WHERE idempotency_key IS NOT NULL;

-- Verify
SELECT column_name, data_type, is_nullable 
FROM information_schema.columns 
WHERE table_name = 'events' AND column_name = 'idempotency_key';
