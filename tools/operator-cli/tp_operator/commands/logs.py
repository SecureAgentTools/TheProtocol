"""tp-operator logs — tail docker compose service logs."""
from __future__ import annotations

import typer

from ..docker_runner import KNOWN_SERVICES, compose_logs, docker_info_ok
from ..output import Output, detect_output_mode


def register(app, state, load_contexts, run_with_audit):
    @app.command(name="logs", help="Tail logs from one Docker Compose service.")
    def logs_cmd(
        service: str = typer.Argument(..., help=f"Service name. One of: {', '.join(KNOWN_SERVICES)}"),
        tail: int = typer.Option(100, "--tail", help="Lines to show before --follow"),
        follow: bool = typer.Option(False, "--follow", "-f", help="Stream new lines"),
        since: str = typer.Option(None, "--since", help="Show logs since duration / timestamp"),
    ):
        out = Output(detect_output_mode(state.json_mode, state.quiet, state.no_color))
        if not docker_info_ok():
            out.error("Docker daemon unreachable.")
            raise typer.Exit(code=5)

        contexts = load_contexts()
        if len(contexts) != 1:
            out.error("`logs` requires a single operator. Use --operator NAME.")
            raise typer.Exit(code=1)
        ctx = contexts[0]

        def _run():
            return compose_logs(ctx, service, tail=tail, follow=follow, since=since)

        try:
            rc = run_with_audit("logs", ctx.name, _run)
        except KeyboardInterrupt:
            raise typer.Exit(code=130)

        raise typer.Exit(code=rc if rc in (0, 130) else 1)
