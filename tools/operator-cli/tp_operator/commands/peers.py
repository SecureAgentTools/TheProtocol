"""tp-operator peers — federation network observability."""
from __future__ import annotations

import typer

from .. import __schema_version__
from ..http_client import FederationClient, timeout_or
from ..output import Output, detect_output_mode


def register(app, state, load_contexts, run_with_audit):
    @app.command(name="peers", help="Show federation peers + network stats.")
    def peers_cmd():
        out = Output(detect_output_mode(state.json_mode, state.quiet, state.no_color))
        contexts = load_contexts()
        results = []
        for ctx in contexts:
            with FederationClient(ctx.mainframe_url, ctx.federation_license, timeout=timeout_or(10.0)) as fc:
                try:
                    r = fc.get("/api/v1/federation/network-stats")
                    data = r.json() if r.status_code == 200 else {"error": r.text[:200]}
                except Exception as e:
                    data = {"error": str(e)[:200]}
            results.append({
                "schema_version": __schema_version__,
                "operator": ctx.name,
                "mainframe_url": ctx.mainframe_url,
                "stats": data,
            })

        if out.mode == "json":
            out.emit_json(results[0] if len(results) == 1 else {"operators": results})
        else:
            for r in results:
                out.line(f"\nOperator: [bold]{r['operator']}[/]")
                stats = r.get("stats", {})
                if "error" in stats:
                    out.error(stats["error"])
                else:
                    out.emit_json(stats)
        raise typer.Exit(code=0)
