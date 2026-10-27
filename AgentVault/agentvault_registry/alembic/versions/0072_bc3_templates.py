"""§bc3 T3.6 — saved admin_broadcast_templates table.

Revision ID: 0072_bc3_templates
Revises: 0071_bc2_email_failed
Create Date: 2026-05-19

Admin compose UX wants saved templates beyond the 3 hardcoded ones. Each
admin saves their own templates (created_by FK). Templates carry the full
shape of a BroadcastCreate so the compose modal can populate every field
in one click. Idempotent.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0072_bc3_templates"
down_revision: Union[str, None] = "0071_bc2_email_failed"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS admin_broadcast_templates (
            id              BIGSERIAL PRIMARY KEY,
            created_by      INTEGER NOT NULL REFERENCES developers(id) ON DELETE CASCADE,
            label           VARCHAR(80)  NOT NULL,
            title_template  VARCHAR(200) NOT NULL,
            body_template   TEXT         NOT NULL,
            broadcast_type  VARCHAR(20)  NOT NULL DEFAULT 'info',
            send_email      BOOLEAN      NOT NULL DEFAULT FALSE,
            requires_ack    BOOLEAN      NOT NULL DEFAULT FALSE,
            cta_url         VARCHAR(500),
            cta_label       VARCHAR(50),
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            CONSTRAINT admin_broadcast_templates_label_unique_per_creator
                UNIQUE (created_by, label)
        );
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_broadcast_templates_creator
        ON admin_broadcast_templates(created_by, created_at DESC);
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_broadcast_templates_creator;")
    op.execute("DROP TABLE IF EXISTS admin_broadcast_templates;")
