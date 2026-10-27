"""Admin broadcasts: an optional single-developer target.

Revision ID: 0179_broadcast_target_dev
Revises: 0178_es_emit_outbox

`target_developer_id` scopes a broadcast to ONE developer of this registry. NULL keeps today's meaning
(everyone, or the members of `target_org_id`).

Deliberately NO foreign key. `ON DELETE SET NULL` would be the natural choice and the wrong one: NULL means
"everyone", so deleting the developer would publish their private notice to the whole registry. Developer ids
are never reused, so a dangling id is a notice nobody can see, which is the safe way to fail.
"""
from alembic import op

revision = "0179_broadcast_target_dev"
down_revision = "0178_es_emit_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE admin_broadcasts ADD COLUMN IF NOT EXISTS target_developer_id INTEGER;")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_admin_broadcasts_target_developer "
        "ON admin_broadcasts(target_developer_id, is_active) WHERE target_developer_id IS NOT NULL;"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_admin_broadcasts_target_developer;")
    op.execute("ALTER TABLE admin_broadcasts DROP COLUMN IF EXISTS target_developer_id;")
