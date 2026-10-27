"""Frame requests: the kit download window of an approved self-hosted request.

Revision ID: 0180_frame_request_kit
Revises: 0179_broadcast_target_dev

§HELLOFRAME (his word 2026-09-19: "build it behind the flag, off by default"). A self-hosted frame request that the
admin approves may download the frame kit (the open-source export) from the applicant's own page, within a window:

  kit_approved_at       when the admin approved it (the window starts here; approving again starts a new window)
  kit_download_count    downloads started in the current window (the limit is FRAME_KIT_MAX_DOWNLOADS)
  kit_last_download_at  the last download started

All three are inert while FRAME_KIT_ENABLED is off. Rolling back past this revision is two steps: downgrade first.
"""
from alembic import op

revision = "0180_frame_request_kit"
down_revision = "0179_broadcast_target_dev"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE frame_requests ADD COLUMN IF NOT EXISTS kit_approved_at TIMESTAMPTZ;")
    op.execute("ALTER TABLE frame_requests ADD COLUMN IF NOT EXISTS kit_download_count INTEGER NOT NULL DEFAULT 0;")
    op.execute("ALTER TABLE frame_requests ADD COLUMN IF NOT EXISTS kit_last_download_at TIMESTAMPTZ;")


def downgrade() -> None:
    op.execute("ALTER TABLE frame_requests DROP COLUMN IF EXISTS kit_last_download_at;")
    op.execute("ALTER TABLE frame_requests DROP COLUMN IF EXISTS kit_download_count;")
    op.execute("ALTER TABLE frame_requests DROP COLUMN IF EXISTS kit_approved_at;")
