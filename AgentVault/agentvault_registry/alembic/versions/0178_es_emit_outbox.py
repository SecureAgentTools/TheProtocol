"""§SOVKIT K1 / V0372 (2026-09-14) — the registry's ledger emits get a DURABLE outbox.

K1 deleted the registry's Kafka producer (his word: Kafka is private to the event store). agentvault2-85 then measured
what the producer had been doing besides bypassing the store's checks: BUFFERING the registry's writes through a store
restart. Without it the emitter's three attempts (1 s, 2 s) lose every registry emit during a store outage longer than
~4 s: every store recreate, every store image roll, is a registry write gap. Money events log EMIT-LOST, the rest only
the failure line; the TEG has its durable outbox, the registry had none. The frame Redis holds nothing across a restart
(no AOF, no RDB, measured on orchard and the sandbox pair), so the outbox lives HERE, in the registry's own database.

ONE table, nothing else touched: no existing column, no data, no backfill. A row is the event as the emitter would have
POSTed it. `idempotency_key` is UNIQUE: the store dedups on it (409 = success), so a redelivery after a lost answer is
safe, and a second deferral of the same operation collapses onto the first row. `delivered_at` closes a row, `dead_at`
parks one past its attempt budget (kept, logged with type/aggregate/key for a re-emit by hand; never deleted). The
partial index is the drainer's whole question: what is due and still open.

Rolling back past this is the two-step rule (downgrade first from an image that has it, then the older image).

Revision ID: 0178_es_emit_outbox
Revises: 0177_bond_partial_release
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0178_es_emit_outbox"
down_revision = "0177_bond_partial_release"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "es_emit_outbox",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("aggregate_id", sa.String(length=512), nullable=False),
        sa.Column("aggregate_type", sa.String(length=64), nullable=False, server_default="Agent"),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dead_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("idempotency_key", name="uq_es_emit_outbox_idempotency_key"),
    )
    op.create_index(
        "ix_es_emit_outbox_due", "es_emit_outbox", ["next_attempt_at"],
        postgresql_where=sa.text("delivered_at IS NULL AND dead_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_es_emit_outbox_due", table_name="es_emit_outbox")
    op.drop_table("es_emit_outbox")
