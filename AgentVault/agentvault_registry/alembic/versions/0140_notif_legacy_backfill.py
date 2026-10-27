"""backfill the legacy broadcast/cicd mutes into v2 preference rows (additive, idempotent)

§9: the 6 `legacy_managed` types (broadcast.* x4, cicd.* x2) move onto the v2 resolver now that
`notify()` serves the inapp and email rails (mig 0139). Their stated preferences lived in
`developers.notification_prefs` as legacy keys; this carries them across so that flipping
`legacy_managed` off cannot silently re-enable something a developer had switched off.

Only rows that DISAGREE with the catalog default are written — the catalog defaults these
channels to enabled, so we insert exactly the explicit OFFs and the table stays sparse
(same discipline as 0137).

Mapping, taken from the effective-prefs branch this replaces:
    broadcast.<sev>  inapp  = delivery_in_app AND NOT mute_<sev>
    broadcast.<sev>  email  = delivery_email  AND NOT mute_<sev>
    cicd.*           inapp  = NOT mute_cicd_my_agents
`broadcast.critical` is mandatory — the resolver short-circuits it, so it has no row and cannot
be muted, which is the point of marking it mandatory in the first place.

Revision ID: 0140_notif_legacy_backfill (<=32 chars)
Revises: 0139_notification_feed
"""
from alembic import op
from sqlalchemy import text

revision = "0140_notif_legacy_backfill"
down_revision = "0139_notification_feed"
branch_labels = None
depends_on = None

# (type_key, channel, SQL predicate that means "this developer had it OFF")
_OFF_WHEN = [
    ("broadcast.info", "inapp", "p->>'delivery_in_app' = 'false' OR p->>'mute_info' = 'true'"),
    ("broadcast.info", "email", "p->>'delivery_email' = 'false' OR p->>'mute_info' = 'true'"),
    ("broadcast.warning", "inapp", "p->>'delivery_in_app' = 'false' OR p->>'mute_warning' = 'true'"),
    ("broadcast.warning", "email", "p->>'delivery_email' = 'false' OR p->>'mute_warning' = 'true'"),
    ("broadcast.maintenance", "inapp", "p->>'delivery_in_app' = 'false' OR p->>'mute_maintenance' = 'true'"),
    ("broadcast.maintenance", "email", "p->>'delivery_email' = 'false' OR p->>'mute_maintenance' = 'true'"),
    ("cicd.deploy_completed", "inapp", "p->>'mute_cicd_my_agents' = 'true'"),
    ("cicd.deploy_failed", "inapp", "p->>'mute_cicd_my_agents' = 'true'"),
]


def upgrade():
    bind = op.get_bind()
    for type_key, channel, predicate in _OFF_WHEN:
        # ON CONFLICT DO NOTHING: a developer who already stated a v2 preference for this
        # (type, channel) has said something more recent than the legacy blob — never overwrite it.
        bind.execute(text(f"""
            INSERT INTO developer_notification_prefs
                (developer_id, type_key, channel, enabled, threshold_num, updated_at)
            SELECT d.id, :tk, :ch, FALSE, NULL, now()
            FROM (
                SELECT id, notification_prefs::jsonb AS p
                FROM developers
                WHERE notification_prefs IS NOT NULL
            ) d
            WHERE {predicate}
            ON CONFLICT (developer_id, type_key, channel) DO NOTHING
        """), {"tk": type_key, "ch": channel})


def downgrade():
    # Deliberate no-op: these rows now ARE the developer's stated preference. Rolling the image
    # back must not delete them (feedback_registry_rollback_alembic_downgrade_crash).
    pass
