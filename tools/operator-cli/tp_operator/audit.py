"""Local audit log — JSON-line, rotating at 16 MB, 4 generations kept.

Every state-mutating command writes one line. Never logs secrets — only
license_key prefix (first 12 chars: `tp_fed_<hex8>`).
"""
from __future__ import annotations

import datetime
import getpass
import json
import os
import platform
import socket
from pathlib import Path
from typing import Any, Dict, Optional

from . import __version__

AUDIT_DIR_NAME = ".tp-operator"
AUDIT_FILE_NAME = "audit.log"
MAX_BYTES = 16 * 1024 * 1024  # 16 MB
KEEP_ROTATIONS = 4


def audit_dir() -> Path:
    home = Path.home()
    d = home / AUDIT_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _rotate_if_needed(p: Path) -> None:
    if not p.exists():
        return
    try:
        size = p.stat().st_size
    except OSError:
        return
    if size < MAX_BYTES:
        return
    # Rotate
    for i in range(KEEP_ROTATIONS, 0, -1):
        prev = p.with_suffix(f".log.{i}")
        if i == KEEP_ROTATIONS and prev.exists():
            prev.unlink(missing_ok=True)
        nxt = p.with_suffix(f".log.{i+1}") if i < KEEP_ROTATIONS else None
        if nxt and prev.exists():
            prev.rename(nxt)
    p.rename(p.with_suffix(".log.1"))


def write_audit(
    cmd: str,
    operator: Optional[str],
    exit_code: int,
    duration_ms: float,
    dry_run: bool = False,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Append one JSON-line entry to ~/.tp-operator/audit.log.

    No secrets ever land here. License keys are prefix-only (first 12 chars).
    """
    p = audit_dir() / AUDIT_FILE_NAME
    _rotate_if_needed(p)
    # invocation_source distinguishes MCP-triggered vs direct-CLI invocations.
    # The MCP server (tp mcp serve) sets TP_OPERATOR_INVOCATION_SOURCE=mcp before
    # subprocessing the CLI; absent that env var, default to "cli".
    invocation_source = os.environ.get("TP_OPERATOR_INVOCATION_SOURCE", "cli")
    if invocation_source not in ("cli", "mcp"):
        invocation_source = "cli"  # whitelist — don't let arbitrary values land

    entry: Dict[str, Any] = {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "cli_version": __version__,
        "host": socket.gethostname(),
        "user": getpass.getuser(),
        "platform": platform.system().lower(),
        "operator": operator or "(none)",
        "cmd": cmd,
        "exit_code": exit_code,
        "duration_ms": round(duration_ms, 1),
        "dry_run": dry_run,
        "invocation_source": invocation_source,
    }
    if extra:
        # Strip any keys that look like secrets defensively.
        for k, v in extra.items():
            if any(s in k.lower() for s in ("secret", "password", "private")):
                continue
            if isinstance(v, str) and v.startswith("tp_fed_") and len(v) > 20:
                v = v[:12] + "..."  # mask
            entry[k] = v
    try:
        with p.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        # Audit log must never block the command itself.
        pass
