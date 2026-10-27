"""Async cross-frame transfer tables + emission policies (2026-05-03).

Revision ID: 0027_cross_frame_transfers_async
Revises: 0026_bootstrap_token_hash

Adds two tables (sender side + receiver side) for the async cross-frame
transfer path (env-flag TEG_CROSS_FRAME_BACKEND=async). Idempotent (IF NOT
EXISTS / ON CONFLICT) so migration_bridge.py replays on every container boot
remain safe (per project_migration_idempotency.md).

Sender side `cross_frame_transfers`:
  - status='locked'     while waiting for Settled event from peer frame
  - status='settled'    when sender's reactor catches CrossFrameTransferSettled
  - status='refunded'   when saga timeout fires Refunded compensating event

Receiver side `cross_frame_transfers_inbound`:
  - status='credited'   when receiver's reactor settles + emits TokensTransferred
  - status='reversed'   when receiver's reactor catches CrossFrameTransferRefunded
                        (compensating reversal — only fires if previously credited)

Both tables: idempotency_key UNIQUE = "xfer-{transfer_id}" so receiver and
sender ON CONFLICT-absorb replays from EventStore backlog or SF-4 retry.

Also seeds 3 EventEmissionPolicy rows so emission goes through the f037 gate
properly (registry-only emission, audit-only for Initiated+Settled, balance
event for Refunded).
"""

from alembic import op
from sqlalchemy import text


revision = "0027_cross_frame_transfers_async"
down_revision = "0026_bootstrap_token_hash"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # Sender side ---------------------------------------------------------
    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS cross_frame_transfers (
            id VARCHAR(64) PRIMARY KEY,
            sender_did VARCHAR(255) NOT NULL,
            receiver_did VARCHAR(255) NOT NULL,
            target_frame VARCHAR(255) NOT NULL,
            amount NUMERIC(36, 18) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'locked',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            timeout_at TIMESTAMPTZ NOT NULL,
            settled_at TIMESTAMPTZ NULL,
            refunded_at TIMESTAMPTZ NULL,
            idempotency_key VARCHAR(255) NOT NULL UNIQUE
        )
    """))
    bind.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_cross_frame_transfers_status_timeout
        ON cross_frame_transfers (status, timeout_at)
    """))
    bind.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_cross_frame_transfers_sender_did
        ON cross_frame_transfers (sender_did)
    """))

    # Receiver side -------------------------------------------------------
    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS cross_frame_transfers_inbound (
            id VARCHAR(64) PRIMARY KEY,
            sender_did VARCHAR(255) NOT NULL,
            receiver_did VARCHAR(255) NOT NULL,
            source_frame VARCHAR(255) NOT NULL,
            amount NUMERIC(36, 18) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'credited',
            credited_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            reversed_at TIMESTAMPTZ NULL,
            idempotency_key VARCHAR(255) NOT NULL UNIQUE
        )
    """))
    bind.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_cross_frame_inbound_receiver_did
        ON cross_frame_transfers_inbound (receiver_did)
    """))

    # Emission policies (3 new event types) ------------------------------
    bind.execute(text("""
        INSERT INTO event_emission_policies
          (event_type, emit_from_teg, emit_from_registry, skip_in_projection,
           description, updated_at)
        VALUES
          ('CrossFrameTransferInitiated', false, true, true,
           'Async cross-frame transfer initiated on sender frame. Sender locked balance + INSERTed cross_frame_transfers row. Receiver-frame reactor catches via SF-4-replicated foreign_events + Pub/Sub bridge → credits recipient. Audit-only (skip_in_projection=true) — actual balance impact via TokensTransferred. Payload: transfer_id, sender_did, receiver_did, source_frame, target_frame, amount.',
           now()),
          ('CrossFrameTransferSettled', false, true, true,
           'Async cross-frame transfer settled by receiver. Receiver-frame reactor credited recipient + emitted TokensTransferred. Sender-frame reactor catches this via SF-4 + Pub/Sub bridge → clears pending_outgoing on sender row. Audit-only — balance already accounted via TokensTransferred. Payload: transfer_id, sender_did, receiver_did, source_frame, target_frame, amount, settled_at.',
           now()),
          ('CrossFrameTransferRefunded', false, true, false,
           'Async cross-frame transfer refunded — saga timeout fired on sender side. Sender restored balance + UPDATEd row to refunded. Receiver-frame reactor catches this and reverses any previously-credited inbound row (compensating action). Counted in projection because it produces a real TokensTransferred in the same transaction (escrow → sender restore). Payload: transfer_id, sender_did, receiver_did, source_frame, target_frame, amount, reason.',
           now())
        ON CONFLICT (event_type) DO NOTHING
    """))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("""
        DELETE FROM event_emission_policies
        WHERE event_type IN (
            'CrossFrameTransferInitiated',
            'CrossFrameTransferSettled',
            'CrossFrameTransferRefunded'
        )
    """))
    bind.execute(text("DROP TABLE IF EXISTS cross_frame_transfers_inbound"))
    bind.execute(text("DROP TABLE IF EXISTS cross_frame_transfers"))
