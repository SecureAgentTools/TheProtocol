"""§REPATLANE-8 (V0610, 2026-10-13) — a kept answer outlives Redis: the durable copy of an Idempotency-Key's record.

His decision, left to agentvault2-45 2026-10-13 ("do your decision for the database copy"): the answers a money endpoint
keeps under its Idempotency-Key (V0606's kept attempts, services/idempotency/cache.py) lived only in Redis, and Redis runs
allkeys-lru (128 MB; EU used 75 MB, 56 of them tester history): a kept answer the cache evicted inside its 24 h window made
the same key run the payment AGAIN, because nothing else remembers it (the TEG does not dedup transfers by the client's key).
This table holds the same record beside Redis: the claim while the request runs, then its kept answer (a 2xx) or kept
error, or nothing once the key was given back. Redis stays the arbiter of concurrency and the fast path; the row is read
only when Redis has no record of the key, and puts it back.

ONE table, nothing else touched. The key is (scope, idem_key), one row per key on an endpoint family, as Redis's
`idempotency:<scope>:<key>`. Rows past expires_at are dead (an answer is kept 24 h, as in Redis) and the sweeper
(background_tasks/idempotency_kept_sweeper) deletes them; the index on expires_at is its whole question.

Rolling back past this is the two-step rule (downgrade first from an image that has it, then the older image). Dropping
the table loses nothing Redis does not also hold: the older image keeps its answers in Redis alone, as before.

Revision ID: 0191_idempotency_kept
Revises: 0190_forfeiture_owed
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0191_idempotency_kept"
down_revision = "0190_forfeiture_owed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "idempotency_kept",
        sa.Column("scope", sa.String(length=64), primary_key=True),
        sa.Column("idem_key", sa.String(length=255), primary_key=True),
        sa.Column("body_hash", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("owner", sa.String(length=32), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_idempotency_kept_expires_at", "idempotency_kept", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_idempotency_kept_expires_at", table_name="idempotency_kept")
    op.drop_table("idempotency_kept")
