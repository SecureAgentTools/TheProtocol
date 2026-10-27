"""notification_feed — the generic in-app rail the catalog has always declared (additive)

Why a NEW table rather than reusing `admin_broadcasts`: the existing bell reads
`admin_broadcasts` minus `developer_notification_reads`, and that table is broadcast-SHAPED —
`target_org_id`, `is_active`, `broadcast_type`, a 90-day horizon, and it drives the admin
broadcast list. Writing one row per `contract.offered` into it would pollute an admin surface and
give every generic notification org-targeting semantics it has no business having.

This is the "P6 feed table + read-state" the catalog docstring anticipated. With it, `notify()`
can finally serve the `inapp` channel that `default_enabled` has declared since day one — the
resolver was already channel-generic (`decide(entry, channel, ...)`), only DELIVERY was
push-only.

`read_at IS NULL` is the unread predicate; the partial index is what keeps the bell's query an
index scan as the table grows. Retention rides the same pruner as notification_log.

Revision ID: 0139_notification_feed (≤32 chars — alembic_version.version_num is VARCHAR(32))
Revises: 0138_notification_log
"""
from alembic import op
from sqlalchemy import text

revision = "0139_notification_feed"
down_revision = "0138_notification_log"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS notification_feed (
            id           BIGSERIAL PRIMARY KEY,
            developer_id INTEGER      NOT NULL REFERENCES developers(id) ON DELETE CASCADE,
            type_key     VARCHAR(80)  NOT NULL,
            category     VARCHAR(32)  NOT NULL DEFAULT '',
            severity     VARCHAR(16)  NOT NULL DEFAULT 'info',
            title        TEXT         NOT NULL,
            body         TEXT,
            click        VARCHAR(500),
            created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
            read_at      TIMESTAMPTZ
        )
    """))
    # The bell asks exactly one question: "my unread, newest first".
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_notification_feed_unread "
        "ON notification_feed (developer_id, created_at DESC) WHERE read_at IS NULL"
    ))
    # Full history read + the retention prune.
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_notification_feed_dev_time "
        "ON notification_feed (developer_id, created_at DESC)"
    ))


def downgrade():
    # Deliberate no-op, same rule as 0137/0138: an image rollback must never drop
    # operator-visible state (feedback_registry_rollback_alembic_downgrade_crash).
    pass
