"""tp-operator entrypoint — typer app wiring.

Strategy: PRODUCTION_DOCS/ROADMAP/Operator_CLI_Strategy.md §3 (command surface).
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Optional

import typer

from . import __version__
from .audit import write_audit
from .audit_remote import emit_remote_audit
from .config import (
    AmbiguousOperator,
    OperatorContext,
    OperatorNotFound,
    resolve_all_contexts,
    resolve_context,
    frame_context,
    FrameNotFound,
)
from .http_client import SETTINGS as HTTP_SETTINGS
from .output import Output, detect_output_mode


app = typer.Typer(
    name="tp-operator",
    help=(
        "TheProtocol operator CLI — day-2 ops for federated/standalone registries.\n\n"
        "Authenticated via FEDERATION_LICENSE_KEY from .env.operator. "
        "See PRODUCTION_DOCS/09_DEVELOPER_GUIDES/Operator_CLI_Reference.md."
    ),
    no_args_is_help=True,
    add_completion=True,
)


# ── Global state shim (typer state-injection pattern) ──────────────
class _GlobalState:
    def __init__(self):
        self.json_mode = False
        self.quiet = False
        self.no_color = False
        self.verbose = 0
        self.yes = False
        self.dry_run = False
        self.timeout: Optional[int] = None   # --timeout; None keeps each call's own default
        self.config: Optional[Path] = None
        self.operator: Optional[str] = None
        self.all_operators = False
        self.frame: Optional[Path] = None   # §FRAMEKIT P3.2: a frame stack dir


STATE = _GlobalState()


# ── Audit wrapper for command callables ────────────────────────────
def _run_with_audit(cmd_name: str, ctx_name: Optional[str], fn, *args, **kwargs):
    """Run fn within an audit wrapper. Returns fn's result.

    exit_code in audit log is derived from raised exceptions (SystemExit/typer.Exit
    raised by the typer command AFTER this wrapper returns is NOT captured here —
    the per-command exit code lives at the command level). For audit purposes,
    `exit_code` here records whether fn ITSELF raised: 0 = clean, 130 = SIGINT,
    2 = unhandled exception. The result of fn is returned unchanged.
    """
    t0 = time.monotonic()
    exit_code = 0
    audit_exit: int = 0
    try:
        result = fn(*args, **kwargs)
        return result
    except SystemExit as e:
        audit_exit = int(e.code) if e.code is not None and isinstance(e.code, int) else 0
        exit_code = audit_exit
        raise
    except KeyboardInterrupt:
        audit_exit = 130
        exit_code = 130
        raise
    except Exception:
        audit_exit = 2
        exit_code = 2
        raise
    finally:
        duration_ms = (time.monotonic() - t0) * 1000.0
        write_audit(
            cmd=cmd_name,
            operator=ctx_name,
            exit_code=audit_exit,
            duration_ms=duration_ms,
            dry_run=STATE.dry_run,
        )
        # Best-effort remote emit — only fires when TP_OPERATOR_REMOTE_AUDIT=true.
        # Loads context lazily so non-operator commands (version, --help) skip it.
        if not STATE.dry_run:
            try:
                ctx_for_audit = None
                # Only attempt context resolution if STATE has enough info.
                if STATE.config or STATE.operator or os.environ.get("TP_OPERATOR_HOME"):
                    ctx_for_audit = resolve_context(STATE.config, STATE.operator)
                if ctx_for_audit is not None:
                    emit_remote_audit(
                        ctx_for_audit,
                        action=cmd_name,
                        exit_code=audit_exit,
                        duration_ms=duration_ms,
                        dry_run=STATE.dry_run,
                    )
            except Exception:
                pass  # never disturb the user flow


# ── Helper: load contexts honoring --operator / --all-operators / discovery ──
def _load_contexts() -> list[OperatorContext]:
    if STATE.frame is not None:
        try:
            return [frame_context(STATE.frame)]
        except FrameNotFound as e:
            out = Output(detect_output_mode(STATE.json_mode, STATE.quiet, STATE.no_color))
            out.error(str(e))
            raise typer.Exit(code=1)
    if STATE.all_operators:
        return resolve_all_contexts()
    try:
        return [resolve_context(STATE.config, STATE.operator)]
    except OperatorNotFound as e:
        out = Output(detect_output_mode(STATE.json_mode, STATE.quiet, STATE.no_color))
        out.error(str(e))
        raise typer.Exit(code=1)
    except AmbiguousOperator as e:
        out = Output(detect_output_mode(STATE.json_mode, STATE.quiet, STATE.no_color))
        out.error(str(e))
        raise typer.Exit(code=1)
    except FileNotFoundError as e:
        out = Output(detect_output_mode(STATE.json_mode, STATE.quiet, STATE.no_color))
        out.error(str(e))
        raise typer.Exit(code=1)


# ── Top-level callback (global flags) ──────────────────────────────
@app.callback()
def main_callback(
    ctx: typer.Context,
    config: Optional[Path] = typer.Option(None, "--config", help="Path to .env.operator"),
    operator: Optional[str] = typer.Option(None, "--operator", help="Operator name or directory"),
    frame: Optional[Path] = typer.Option(None, "--frame", help="A FRAME stack dir the standup driver built (.env.frame-test + docker-compose.frame-test.yml)"),
    all_operators: bool = typer.Option(False, "--all-operators", help="Apply across every discovered operator"),
    json_mode: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress all but errors (the exit code carries the verdict)"),
    no_color: bool = typer.Option(False, "--no-color", help="Disable rich formatting"),
    verbose: int = typer.Option(0, "--verbose", "-v", count=True,
                                help="Print each HTTP call (method, URL, status) on stderr"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip interactive confirmation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print intended action without executing"),
    timeout: Optional[int] = typer.Option(None, "--timeout",
                                          help="HTTP timeout in seconds for every call (unset: each call's own)"),
    version: bool = typer.Option(False, "--version", is_eager=True, help="Print version and exit"),
):
    """tp-operator — TheProtocol operator CLI."""
    if version:
        # Cheap fast path: no config load needed.
        print(f"tp-operator {__version__}")
        raise typer.Exit(code=0)
    STATE.config = config
    STATE.operator = operator
    STATE.frame = frame
    STATE.all_operators = all_operators
    STATE.json_mode = json_mode
    STATE.quiet = quiet
    STATE.no_color = no_color
    STATE.verbose = verbose
    STATE.yes = yes
    STATE.dry_run = dry_run
    STATE.timeout = timeout
    HTTP_SETTINGS.update(timeout=timeout, verbose=verbose)


# Register command groups
from .commands import (  # noqa: E402
    status as cmd_status,
    health as cmd_health,
    logs as cmd_logs,
    restart as cmd_restart,
    license as cmd_license,
    peers as cmd_peers,
    sync as cmd_sync,
    validate_config as cmd_validate,
    version as cmd_version,
    doctor as cmd_doctor,
    spire as cmd_spire,
    backup as cmd_backup,
    update as cmd_update,
    restore as cmd_restore,
    bundle as cmd_bundle,  # §pass51 P51
)

cmd_status.register(app, STATE, _load_contexts, _run_with_audit)
cmd_health.register(app, STATE, _load_contexts, _run_with_audit)
cmd_logs.register(app, STATE, _load_contexts, _run_with_audit)
cmd_restart.register(app, STATE, _load_contexts, _run_with_audit)
cmd_license.register(app, STATE, _load_contexts, _run_with_audit)
cmd_peers.register(app, STATE, _load_contexts, _run_with_audit)
cmd_sync.register(app, STATE, _load_contexts, _run_with_audit)
cmd_validate.register(app, STATE, _load_contexts, _run_with_audit)
cmd_version.register(app, STATE, _load_contexts, _run_with_audit)
cmd_doctor.register(app, STATE, _load_contexts, _run_with_audit)
cmd_spire.register(app, STATE, _load_contexts, _run_with_audit)
cmd_backup.register(app, STATE, _load_contexts, _run_with_audit)
cmd_update.register(app, STATE, _load_contexts, _run_with_audit)
cmd_restore.register(app, STATE, _load_contexts, _run_with_audit)
cmd_bundle.register(app, STATE, _load_contexts, _run_with_audit)  # §pass51 P51


if __name__ == "__main__":
    app()
