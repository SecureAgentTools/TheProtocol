"""0133 — WEB PUSH: the Protocol app gets its own push channel (2026-07-25).

`device_push_registrations` already models "a place to notify this developer". Web Push is simply
a third rail alongside ntfy/fcm/apns: `rail='webpush'`, `target` = the browser-issued endpoint URL,
plus the two subscription keys the encryption needs (RFC 8291). No new device concept, so every
existing prefs/fan-out path applies unchanged.

`target` is widened because push endpoints are long URLs, well past the 255 the ntfy topics fit in.

IDEMPOTENT — replays every boot. Chains 0132.
"""
from alembic import op
from sqlalchemy import text

revision: str = "0133_webpush_subscriptions"
down_revision: str = "0132_liability_mandates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("ALTER TABLE device_push_registrations ADD COLUMN IF NOT EXISTS p256dh TEXT"))
    bind.execute(text("ALTER TABLE device_push_registrations ADD COLUMN IF NOT EXISTS auth TEXT"))
    # push endpoints are long URLs; the ntfy-era VARCHAR(255) would truncate them
    bind.execute(text("ALTER TABLE device_push_registrations ALTER COLUMN target TYPE TEXT"))


def downgrade() -> None:
    # Additive-only; never rolled down in prod.
    pass
