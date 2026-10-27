"""tp-operator restart / start / stop — service lifecycle."""
from __future__ import annotations

from typing import Optional

import typer

from ..config import OperatorContext
from ..docker_runner import (
    compose_down,
    compose_restart,
    compose_up,
    docker_info_ok,
    wait_healthy,
)
from ..output import Output, detect_output_mode
from ..pidlock import LockAcquireError, acquire_lock

RESTART_HEALTH_WAIT_S = 120   # the registry's healthcheck: 30 s start period, then every 30 s


def _confirm(out: Output, state, what: str) -> bool:
    if state.yes or state.dry_run:
        return True
    if not state.no_color:
        out.line(f"[yellow]About to: {what}[/yellow]")
    else:
        out.line(f"About to: {what}")
    answer = typer.prompt("Type 'yes' to proceed", default="no", show_default=False)
    return answer.strip().lower() in ("y", "yes")


def register(app, state, load_contexts, run_with_audit):
    @app.command(name="restart", help="Restart one or all services.")
    def restart_cmd(
        service: Optional[str] = typer.Argument(None, help="Service to restart. Omit to restart entire stack."),
        apply_env_changes: bool = typer.Option(False, "--apply-env-changes", help="Force recreate to pick up env changes."),
        no_wait: bool = typer.Option(False, "--no-wait", help="Don't poll for healthy after restart."),
    ):
        out = Output(detect_output_mode(state.json_mode, state.quiet, state.no_color))
        if not docker_info_ok():
            out.error("Docker daemon unreachable.")
            raise typer.Exit(code=5)

        contexts = load_contexts()

        for ctx in contexts:
            action = f"restart {service or 'all services'} on {ctx.name}"
            if apply_env_changes:
                action += " (force-recreate)"
            if not _confirm(out, state, action):
                out.warn("Aborted by user.")
                continue
            if state.dry_run:
                out.line(f"[dim]DRY-RUN[/dim] would: {action}")
                continue
            try:
                with acquire_lock(ctx.name):
                    def _do():
                        rc, output = compose_restart(ctx, service, force_recreate=apply_env_changes)
                        if rc != 0:
                            out.error(f"Restart failed on {ctx.name}: {output[:300]}")
                            return rc
                        if no_wait:
                            out.success(f"Restart OK on {ctx.name} (not waited for healthy: --no-wait).")
                            return 0
                        # CB-286: --no-wait was accepted while nothing waited; the restart now reports the service
                        # healthy, or fails when it is not within the window
                        if not wait_healthy(ctx, service, timeout_s=RESTART_HEALTH_WAIT_S):
                            out.error(f"{service or 'the stack'} on {ctx.name} restarted but is not healthy after "
                                      f"{RESTART_HEALTH_WAIT_S} s (tp-operator status shows which service)")
                            return 1
                        out.success(f"Restart OK on {ctx.name}: {service or 'every service'} healthy.")
                        return 0
                    rc = run_with_audit("restart", ctx.name, _do)
                    if rc != 0:
                        raise typer.Exit(code=1)
            except LockAcquireError as e:
                out.error(str(e))
                raise typer.Exit(code=1)

    @app.command(name="start", help="Bring the stack up (docker compose up -d).")
    def start_cmd():
        out = Output(detect_output_mode(state.json_mode, state.quiet, state.no_color))
        if not docker_info_ok():
            out.error("Docker daemon unreachable.")
            raise typer.Exit(code=5)
        for ctx in load_contexts():
            if not _confirm(out, state, f"start operator stack {ctx.name}"):
                continue
            if state.dry_run:
                out.line(f"[dim]DRY-RUN[/dim] would: start {ctx.name}")
                continue
            try:
                with acquire_lock(ctx.name):
                    def _do(c=ctx):
                        rc, output = compose_up(c)
                        if rc == 0:
                            out.success(f"Stack up on {c.name}.")
                        else:
                            out.error(f"start failed: {output[:300]}")
                        return rc
                    rc = run_with_audit("start", ctx.name, _do)
                    if rc != 0:
                        raise typer.Exit(code=1)
            except LockAcquireError as e:
                out.error(str(e))
                raise typer.Exit(code=1)

    @app.command(name="stop", help="Bring the stack down (docker compose down).")
    def stop_cmd():
        out = Output(detect_output_mode(state.json_mode, state.quiet, state.no_color))
        if not docker_info_ok():
            out.error("Docker daemon unreachable.")
            raise typer.Exit(code=5)
        for ctx in load_contexts():
            if not _confirm(out, state, f"stop operator stack {ctx.name}"):
                continue
            if state.dry_run:
                out.line(f"[dim]DRY-RUN[/dim] would: stop {ctx.name}")
                continue
            try:
                with acquire_lock(ctx.name):
                    def _do(c=ctx):
                        rc, output = compose_down(c)
                        if rc == 0:
                            out.success(f"Stack down on {c.name}.")
                        else:
                            out.error(f"stop failed: {output[:300]}")
                        return rc
                    rc = run_with_audit("stop", ctx.name, _do)
                    if rc != 0:
                        raise typer.Exit(code=1)
            except LockAcquireError as e:
                out.error(str(e))
                raise typer.Exit(code=1)
