"""0087 — allow backend='smartsend' on canary_paths (f060 smart-send canaries).

Widens the canary_paths_backend_check CHECK constraint to include 'smartsend'
so canary paths can exercise the unified /api/v1/teg/send dispatcher (the
runner gained the matching fire arm the same day). Idempotent both ways.

Revision ID: 0087_smartsend_backend
Revises: 0086_canary_cockpit
Create Date: 2026-06-12
"""
from alembic import op

revision: str = "0087_smartsend_backend"
down_revision: str = "0086_canary_cockpit"
branch_labels = None
depends_on = None

_TABLE = "canary_paths"
_CON = "canary_paths_backend_check"


def upgrade() -> None:
    op.execute(f"ALTER TABLE {_TABLE} DROP CONSTRAINT IF EXISTS {_CON}")
    op.execute(
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT {_CON} "
        f"CHECK (backend IN ('async', '2pc', 'intra', 'smartsend'))"
    )


def downgrade() -> None:
    # Remove any smartsend rows first so the narrower constraint can re-apply.
    op.execute(f"DELETE FROM {_TABLE} WHERE backend = 'smartsend'")
    op.execute(f"ALTER TABLE {_TABLE} DROP CONSTRAINT IF EXISTS {_CON}")
    op.execute(
        f"ALTER TABLE {_TABLE} ADD CONSTRAINT {_CON} "
        f"CHECK (backend IN ('async', '2pc', 'intra'))"
    )
