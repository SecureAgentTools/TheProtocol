"""notification_log — one row per notification DECISION, not just per delivery (additive)

Why this exists: `notify()` already computes, per device, a decision and a *reason*
(`notification_prefs.decide()` returns e.g. "default_off" / "quiet" / "threshold" / "narrowed"),
then throws that reason away into a Prometheus label. Prometheus answers "how many were
suppressed"; it cannot answer "why did I not get THAT one". Debugging a quiet-by-default
notification system without a per-event record is guesswork, so we keep the record.

Rows are written for delivered, failed AND suppressed outcomes: a suppression is the single
most useful row in the table (measured on registry-a at adoption: 0 delivered/hr vs ~222
suppressed/hr, every one `default_off`). Logging only successes would hide exactly the thing
you go looking for.

`device_id` deliberately carries NO foreign key: deleting a phone must not erase the history of
what that phone was or was not sent. Same reasoning as `type_key` in 0137 — the catalog lives in
code, so no FK there either.

Retention is enforced by the pruner (NOTIFICATION_LOG_RETENTION_DAYS, default 14); the
`created_at` index exists to make that prune an index scan rather than a seq scan on a table
that grows ~5k rows/day per active developer.

Revision ID: 0138_notification_log (≤32 chars — alembic_version.version_num is VARCHAR(32))
Revises: 0137_dev_notif_prefs
"""
from alembic import op
from sqlalchemy import text

revision = "0138_notification_log"
down_revision = "0137_dev_notif_prefs"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS notification_log (
            id            BIGSERIAL PRIMARY KEY,
            developer_id  INTEGER      NOT NULL REFERENCES developers(id) ON DELETE CASCADE,
            type_key      VARCHAR(80)  NOT NULL,
            category      VARCHAR(32)  NOT NULL DEFAULT '',
            severity      VARCHAR(16)  NOT NULL DEFAULT 'info',
            channel       VARCHAR(16)  NOT NULL,
            outcome       VARCHAR(16)  NOT NULL,
            reason        VARCHAR(32),
            mode          VARCHAR(8)   NOT NULL DEFAULT 'on',
            device_id     INTEGER,
            title         TEXT,
            message       TEXT,
            created_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
        )
    """))
    # The read path is always "this developer, newest first".
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_notification_log_dev_time "
        "ON notification_log (developer_id, created_at DESC)"
    ))
    # The prune path is "everything older than X", across all developers.
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_notification_log_created "
        "ON notification_log (created_at)"
    ))


def downgrade():
    # Deliberate no-op, same rule as 0137: an image rollback must never drop operator-visible
    # history (feedback_registry_rollback_alembic_downgrade_crash — additive migs stay).
    pass
