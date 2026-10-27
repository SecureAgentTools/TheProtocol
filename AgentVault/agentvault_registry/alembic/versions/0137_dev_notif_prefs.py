"""developer_notification_prefs — sparse per-row notification preferences (§NOTIFV2, additive)

One row = one deliberate choice: (developer, catalog type OR '*' wildcard, channel) →
enabled(+optional threshold). ABSENCE of a row means "catalog default", which is why the table
stays small and why the fan-out question — "who wants contract.disputed on push_mobile?" — is
one indexed lookup instead of a scan of every developer's JSON blob. Explicitly NOT a widened
`developers.notification_prefs`: two devices patching one blob is a read-modify-write race, and
per-row upserts are not.

No FK on type_key: the catalog lives in code (ships with the image, versions with the senders);
the resolver simply ignores rows whose key has left the catalog.

Revision ID: 0137_dev_notif_prefs (kept ≤32 chars — alembic_version.version_num is VARCHAR(32); the long id crash-looped the frame-c canary)
Revises: 0136_contract_replicas
"""
from alembic import op
from sqlalchemy import text

revision = "0137_dev_notif_prefs"
down_revision = "0136_contract_replicas"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    bind.execute(text("""
        CREATE TABLE IF NOT EXISTS developer_notification_prefs (
            developer_id  INTEGER NOT NULL REFERENCES developers(id) ON DELETE CASCADE,
            type_key      VARCHAR(80)  NOT NULL,
            channel       VARCHAR(16)  NOT NULL,
            enabled       BOOLEAN      NOT NULL,
            threshold_num DOUBLE PRECISION,
            updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
            PRIMARY KEY (developer_id, type_key, channel)
        )
    """))
    bind.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_dev_notif_prefs_type_channel "
        "ON developer_notification_prefs (type_key, channel)"
    ))


def downgrade():
    # Deliberate no-op: rolling an image back must never delete a developer's stated
    # preferences (feedback_registry_rollback_alembic_downgrade_crash — additive migs stay).
    pass
