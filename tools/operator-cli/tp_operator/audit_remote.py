"""Remote audit event emission — fire-and-forget POST to mainframe.

Per Operator_CLI_Strategy.md §6.4 + §14.Q7 (Commander-approved). Called from
the audit wrapper after each state-mutating command writes its local audit
entry. Best-effort: failures NEVER block the command, and a non-200 response
is silently swallowed (local audit is the source of truth).

v1.0 coverage: only commands that route through `_run_with_audit` emit remote
audit events. Today this covers ALL mutation commands (restart, start, stop,
backup, restore, update, license rotate, spire enroll, spire revoke) plus the
key diagnostic commands (status, health, doctor, license show, license verify).
Pure read-only commands (peers, sync, validate-config, version) intentionally
bypass — auditing every `--help` invocation would be noise. v1.1 will fold
`sync` into the audit wrapper (it does trigger a federation cycle).

Kill switch — TP_OPERATOR_REMOTE_AUDIT: defaults OFF (empty). Set to "true"
in CI/cron environments where Commander wants cross-operator visibility.

The mainframe endpoint POST /api/v1/federation/cli-audit is gated by its own
kill switch (OPERATOR_CLI_AUDIT_EMIT_ENABLED). When prod has it off (default),
the CLI gets 404 (route absent) or 503 (route present but disabled); either way
the local audit log is unaffected.
"""
from __future__ import annotations

import getpass
import os
import socket
from typing import Any, Dict, Optional

from . import __version__
from .config import OperatorContext


_AUDIT_ENABLED_ENV = "TP_OPERATOR_REMOTE_AUDIT"


def is_remote_audit_enabled() -> bool:
    return os.environ.get(_AUDIT_ENABLED_ENV, "").lower() in ("true", "1", "yes")


def emit_remote_audit(
    ctx: Optional[OperatorContext],
    action: str,
    exit_code: int,
    duration_ms: float,
    dry_run: bool = False,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Best-effort emit. Never raises, never blocks > 2s.

    Caller (audit.write_audit wrapper) should call this AFTER writing the
    local audit line, so even if the remote call fails, the local trail
    is preserved.
    """
    if not is_remote_audit_enabled():
        return
    if ctx is None or not ctx.federation_license:
        return

    # Import here to avoid circular import at module load.
    from .http_client import FederationClient

    body = {
        "action": action[:64],
        "cli_version": __version__,
        "actor_host": socket.gethostname()[:120],
        "actor_user": getpass.getuser()[:64],
        "dry_run": bool(dry_run),
        "exit_code": int(exit_code),
        "duration_ms": float(duration_ms),
    }
    if extra:
        # Defensive: never forward secret-looking keys
        safe: Dict[str, Any] = {}
        for k, v in extra.items():
            if any(s in k.lower() for s in ("secret", "password", "private")):
                continue
            if isinstance(v, str) and v.startswith("tp_fed_") and len(v) > 20:
                v = v[:12] + "..."
            safe[k] = v
        body["extra"] = safe

    try:
        with FederationClient(ctx.mainframe_url, ctx.federation_license, timeout=2.0) as fc:
            fc.post("/api/v1/federation/cli-audit", json=body)
    except Exception:
        # Best-effort — never disturb the user-visible flow.
        pass
