"""tp-operator status — aggregate stack health snapshot."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

import typer

from .. import __schema_version__
from ..config import OperatorContext
from ..docker_runner import compose_ps_json, container_details, docker_info_ok
from ..output import Output, detect_output_mode


def _service_verdict(svc: Dict[str, str]) -> str:
    state = (svc.get("State") or "").lower()
    health = (svc.get("Health") or "").lower()
    if state != "running":
        return "red"
    if health == "unhealthy":
        return "red"
    if health == "starting":
        return "yellow"
    return "green"


def _build_status(ctx: OperatorContext, detail: bool = False) -> Dict[str, Any]:
    services = compose_ps_json(ctx)
    # --detail: when each container started and how often docker restarted it (CB-286: the flag was accepted and unused)
    details = container_details([s["Name"] for s in services if s.get("Name")]) if detail else {}
    rows = []
    verdict_counts = {"green": 0, "yellow": 0, "red": 0}
    for svc in services:
        v = _service_verdict(svc)
        verdict_counts[v] += 1
        row = {
            "name": svc.get("Service", svc.get("Name", "?")),
            "state": svc.get("State", "?"),
            "health": svc.get("Health", "none"),
            "image": svc.get("Image", "?"),
            "verdict": v,
        }
        if detail:
            d = details.get(svc.get("Name") or "", {})
            row["started_at"] = d.get("started_at", "?")
            row["restart_count"] = d.get("restart_count", "?")
        rows.append(row)

    if verdict_counts["red"] >= 1:
        agg = "red"
    elif verdict_counts["yellow"] >= 1:
        agg = "yellow"
    elif not services:
        agg = "red"  # no services at all
    else:
        agg = "green"

    return {
        "schema_version": __schema_version__,
        "operator": {"name": ctx.name, "dir": str(ctx.dir), "is_standalone": ctx.is_standalone},
        "verdict": agg,
        "service_count": len(services),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "services": rows,
    }


def register(app, state, load_contexts, run_with_audit):
    @app.command(name="status", help="Aggregate stack health snapshot (Docker compose ps + verdict).")
    def status_cmd(
        detail: bool = typer.Option(False, "--detail", help="Show extra columns (started_at, restart count)."),
    ):
        out = Output(detect_output_mode(state.json_mode, state.quiet, state.no_color))

        if not docker_info_ok():
            out.error("Docker daemon unreachable. Try `systemctl status docker`.")
            raise typer.Exit(code=5)

        contexts = load_contexts()
        results: List[Dict[str, Any]] = []

        for ctx in contexts:
            results.append(run_with_audit("status", ctx.name, _build_status, ctx, detail))

        # ── Output ─────────────────────────────────────────
        if out.mode == "json":
            payload = results[0] if len(results) == 1 else {"operators": results}
            out.emit_json(payload)
        else:
            for r in results:
                badge = {"green": "[bold green]GREEN[/]", "yellow": "[bold yellow]YELLOW[/]", "red": "[bold red]RED[/]"}[r["verdict"]]
                out.line(f"\nOperator: [bold]{r['operator']['name']}[/]  {badge}  ({r['service_count']} services)")
                rows = [
                    [s["name"], s["state"], s["health"], s["image"][:50], s["verdict"].upper()]
                    + ([s["started_at"], s["restart_count"]] if detail else [])
                    for s in r["services"]
                ]
                out.table("services", ["NAME", "STATE", "HEALTH", "IMAGE", "VERDICT"]
                          + (["STARTED", "RESTARTS"] if detail else []), rows)

        # Exit code derived from worst verdict across all operators
        worst = "green"
        for r in results:
            if r["verdict"] == "red":
                worst = "red"
                break
            if r["verdict"] == "yellow" and worst != "red":
                worst = "yellow"

        if worst == "red":
            raise typer.Exit(code=2)
        if worst == "yellow":
            raise typer.Exit(code=1)
        raise typer.Exit(code=0)
