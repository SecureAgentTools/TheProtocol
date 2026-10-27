"""Developer admin management: suspended/deleted columns + admin-action event policies.

Adds five columns to developers for admin lifecycle management:
  - is_suspended       BOOLEAN NOT NULL DEFAULT FALSE (indexed)
  - suspended_at       TIMESTAMPTZ NULL
  - suspended_by       INTEGER NULL (FK developers.id)
  - suspended_reason   VARCHAR(500) NULL
  - deleted_at         TIMESTAMPTZ NULL

Seeds event_emission_policies for 10 admin-action event types used by the new
/api/v1/admin/developers/* and /api/v1/admin/agents/* routers. All emit from
registry only, skip_in_projection=true (audit trail, no balance impact).

Idempotent via IF NOT EXISTS / ON CONFLICT DO NOTHING.

Revision ID: 0009_developer_admin_mgmt
Revises: 0007_consul_enforcement_mode
"""

from alembic import op
from sqlalchemy import text


revision = "0009_developer_admin_mgmt"
down_revision = "0007_consul_enforcement_mode"
branch_labels = None
depends_on = None


_EVENT_POLICIES = (
    # Developer admin actions
    (
        "DeveloperSuspended",
        "Admin suspended a developer account. Contains actor, target_id, reason.",
    ),
    (
        "DeveloperReinstated",
        "Admin reinstated a previously suspended developer.",
    ),
    (
        "DeveloperForcePasswordReset",
        "Admin triggered a password reset email for a developer.",
    ),
    (
        "DeveloperDisable2FA",
        "Admin disabled 2FA on a developer account (emergency unlock).",
    ),
    (
        "DeveloperForceEmailVerify",
        "Admin manually marked a developer email as verified.",
    ),
    (
        "DeveloperRevokeApiKeys",
        "Admin revoked all programmatic API keys for a developer.",
    ),
    (
        "DeveloperDeleted",
        "Admin soft-deleted a developer account (PII scrubbed, row retained).",
    ),
    # Agent admin actions
    (
        "AgentOwnershipTransferred",
        "Admin reassigned an agent to a different creator developer.",
    ),
    (
        "AgentCredentialsRotated",
        "Admin rotated an agent's client_secret (new secret returned once).",
    ),
    (
        "AgentHardDeleted",
        "Admin hard-deleted an agent (row removed; final audit event).",
    ),
    (
        "AgentSuspended",
        "Admin (or bulk) suspended an agent without a prior enforcement-queue proposal.",
    ),
)


def upgrade() -> None:
    bind = op.get_bind()

    # Column additions (idempotent)
    bind.execute(text("""
        ALTER TABLE developers
        ADD COLUMN IF NOT EXISTS is_suspended BOOLEAN NOT NULL DEFAULT FALSE
    """))
    bind.execute(text("""
        ALTER TABLE developers
        ADD COLUMN IF NOT EXISTS suspended_at TIMESTAMPTZ NULL
    """))
    bind.execute(text("""
        ALTER TABLE developers
        ADD COLUMN IF NOT EXISTS suspended_by INTEGER NULL REFERENCES developers(id)
    """))
    bind.execute(text("""
        ALTER TABLE developers
        ADD COLUMN IF NOT EXISTS suspended_reason VARCHAR(500) NULL
    """))
    bind.execute(text("""
        ALTER TABLE developers
        ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ NULL
    """))

    # Index on is_suspended for fast filter queries in /admin/developers list
    bind.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_developers_is_suspended
        ON developers(is_suspended)
    """))

    # Seed the 10 admin-action event policies
    for event_type, description in _EVENT_POLICIES:
        bind.execute(
            text("""
                INSERT INTO event_emission_policies
                  (event_type, emit_from_teg, emit_from_registry, skip_in_projection, description, updated_at)
                VALUES
                  (:event_type, false, true, true, :description, now())
                ON CONFLICT (event_type) DO NOTHING
            """),
            {"event_type": event_type, "description": description},
        )


def downgrade() -> None:
    bind = op.get_bind()

    bind.execute(text("DROP INDEX IF EXISTS ix_developers_is_suspended"))
    bind.execute(text("ALTER TABLE developers DROP COLUMN IF EXISTS deleted_at"))
    bind.execute(text("ALTER TABLE developers DROP COLUMN IF EXISTS suspended_reason"))
    bind.execute(text("ALTER TABLE developers DROP COLUMN IF EXISTS suspended_by"))
    bind.execute(text("ALTER TABLE developers DROP COLUMN IF EXISTS suspended_at"))
    bind.execute(text("ALTER TABLE developers DROP COLUMN IF EXISTS is_suspended"))

    for event_type, _ in _EVENT_POLICIES:
        bind.execute(
            text("DELETE FROM event_emission_policies WHERE event_type = :event_type"),
            {"event_type": event_type},
        )
