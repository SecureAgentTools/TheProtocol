"""§pass68 (2026-05-23) — Add MCP audit event types + indexes for per-tool audit logging.

Closes the gap surfaced by Luca King's email (2026-05-23): MCP tool calls
were landing only in container stdout, not in the immutable `security_audit_logs`
table. This migration adds three new enum values:

  - `mcp_tool_invoked`      — successful tool call (or auth-failure on a
                              specific tool — outcome=failure in that case)
  - `mcp_tool_failed`       — tool dispatch raised an unhandled exception
                              (outcome=error)
  - `admin_read_mcp_audit`  — written into the TARGET developer's audit log
                              every time an admin queries someone else's
                              MCP audit log (self-watching admin reads)

Plus two partial indexes on `security_audit_logs` for the typical query
patterns:

  - `idx_security_audit_target_id_ts` — keyed on (target_id, timestamp DESC)
    WHERE target_type = 'mcp_tool'  → "show me all calls to a specific tool"
  - `idx_security_audit_actor_id_ts` — keyed on (actor_id, timestamp DESC)
    WHERE event_type IN ('mcp_tool_invoked', 'mcp_tool_failed')
    → "show me a developer's own MCP audit log"

The PG enum is `public.security_event_type` (see 0001_squash_initial.py:40-54);
ALTER TYPE ADD VALUE IF NOT EXISTS is idempotent on PG ≥ 12. We COMMIT before
the ALTER because ADD VALUE cannot run inside a transaction on older PG paths,
matching the existing pattern in `0058_*` and `0067_*`.

Idempotent: re-running the migration is a no-op (IF NOT EXISTS on enum values
and indexes). Backfill: NONE — forward-only enum extension.
"""
from alembic import op
import sqlalchemy as sa


revision: str = "0082_mcp_audit_event_types"
down_revision: str = "0081_federation_shadow_flag"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """§pass68.1 — schema-aware: cloud-op registries ship a slim schema that
    does NOT include the `security_event_type` enum or `security_audit_logs`
    table (the OAuth/security audit infrastructure is mainframe-only today).
    Discovered during the 2026-05-23 fleet rollout: cloud-ops crash-looped with
    `type "public.security_event_type" does not exist`. The same image must
    work on both schema variants, so we detect the enum and gracefully no-op
    on cloud-ops. MCP_AUDIT_LOGGING_ENABLED=true on cloud-ops will then result
    in audit-write attempts that count as `mcp_audit_log_writes_total{outcome="write_error"}`
    in Prometheus — observable but harmless. A future migration may backport
    the full security_audit_logs schema to cloud-ops.
    """
    bind = op.get_bind()
    enum_exists = bind.execute(sa.text(
        "SELECT EXISTS(SELECT 1 FROM pg_type WHERE typname='security_event_type')"
    )).scalar()
    table_exists = bind.execute(sa.text(
        "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name='security_audit_logs')"
    )).scalar()

    if not enum_exists or not table_exists:
        # Slim cloud-op schema — skip silently. The MCP audit hook in
        # mcp/audit.py will fail-silent on the missing table; failures are
        # counted in Prometheus but don't propagate to the response path.
        return

    # ALTER TYPE ... ADD VALUE cannot run inside a transaction on older PG.
    # COMMIT first, then run each ADD as its own statement.
    op.execute("COMMIT")
    op.execute(
        "ALTER TYPE public.security_event_type "
        "ADD VALUE IF NOT EXISTS 'mcp_tool_invoked'"
    )
    op.execute(
        "ALTER TYPE public.security_event_type "
        "ADD VALUE IF NOT EXISTS 'mcp_tool_failed'"
    )
    op.execute(
        "ALTER TYPE public.security_event_type "
        "ADD VALUE IF NOT EXISTS 'admin_read_mcp_audit'"
    )

    # Partial index for "show me calls to a specific tool" — cheap because
    # `target_type = 'mcp_tool'` filters out everything else in the table.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_security_audit_target_id_ts
        ON public.security_audit_logs (target_id, "timestamp" DESC)
        WHERE target_type = 'mcp_tool'
        """
    )

    # Partial index for "show me a developer's own MCP audit log" — cheap
    # because event_type filter restricts to MCP rows only.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_security_audit_actor_id_ts
        ON public.security_audit_logs (actor_id, "timestamp" DESC)
        WHERE event_type IN ('mcp_tool_invoked', 'mcp_tool_failed', 'admin_read_mcp_audit')
        """
    )


def downgrade() -> None:
    # Enum values cannot be safely removed from a PG enum (would break any row
    # that already uses them). Indexes can be dropped cheaply.
    op.execute("DROP INDEX IF EXISTS idx_security_audit_actor_id_ts")
    op.execute("DROP INDEX IF EXISTS idx_security_audit_target_id_ts")
