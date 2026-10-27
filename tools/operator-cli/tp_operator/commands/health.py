"""tp-operator health: an active probe of the parent registry (/health, its federation info and its ledger)."""
from __future__ import annotations

import socket
from datetime import datetime, timezone
from typing import Any, Dict, List

import httpx
import typer

from .. import __schema_version__
from ..config import OperatorContext
from ..http_client import event_hooks, timeout_or
from ..output import Output, detect_output_mode


def _probe(url: str, timeout: float = 5.0) -> Dict[str, Any]:
    try:
        with httpx.Client(timeout=timeout_or(timeout), verify=False, event_hooks=event_hooks()) as c:
            r = c.get(url)
        return {"url": url, "status": r.status_code, "ok": 200 <= r.status_code < 300}
    except (httpx.RequestError, socket.error) as e:
        return {"url": url, "status": 0, "ok": False, "error": str(e)[:120]}


# CB-287: the ledger probe asked <parent>/api/v1/projections/supply-audit, an event-store path no registry serves (EU
# and ASIA answer 404), so --strict was red against every frame. The registry's public read of its own ledger is
# /api/v1/public/supply-invariant: always 200, with status OK, BREACH or UNKNOWN (its event store unreadable). Only OK
# is green: a 200 that says UNKNOWN measured nothing.
LEDGER_PATH = "/api/v1/public/supply-invariant"


def _probe_ledger(url: str, timeout: float = 5.0) -> Dict[str, Any]:
    try:
        with httpx.Client(timeout=timeout_or(timeout), verify=False, event_hooks=event_hooks()) as c:
            r = c.get(url)
    except (httpx.RequestError, socket.error) as e:
        return {"url": url, "status": 0, "ok": False, "error": str(e)[:120]}
    try:
        body = r.json() if r.status_code == 200 else {}
    except ValueError:
        body = {}
    ledger = str(body.get("status") or "UNKNOWN") if isinstance(body, dict) else "UNKNOWN"
    return {"url": url, "status": r.status_code, "ok": r.status_code == 200 and ledger == "OK", "ledger": ledger,
            "delta": body.get("delta") if isinstance(body, dict) else None}


def _build_health(ctx: OperatorContext, *, include_federation: bool, include_eventstore: bool) -> Dict[str, Any]:
    # Resolve local URLs based on the operator's compose mapping.
    # For sandbox-A: http://localhost:8002. For cloud operators: cloud_url
    # or via container DNS from inside compose. From the host we use 127.0.0.1
    # + the operator's published ports if visible.
    probes = []

    # Heuristic: REGISTRY_NAME → port mapping is internal-only. The most
    # reliable check is to use docker exec into the registry container and
    # curl localhost:8000/health. For v1.0 we read from the compose's published
    # port if available.
    # Simpler approach: rely on the registry's healthcheck in `tp-operator status`
    # and have `health` do mainframe-side connectivity.

    mainframe = ctx.mainframe_url
    probes.append(_probe(f"{mainframe}/health"))
    if include_federation:
        probes.append(_probe(f"{mainframe}/api/v1/federation/info"))
    if include_eventstore:
        probes.append(_probe_ledger(f"{mainframe}{LEDGER_PATH}"))

    all_ok = all(p["ok"] for p in probes)
    return {
        "schema_version": __schema_version__,
        "operator": {"name": ctx.name},
        "verdict": "green" if all_ok else "red",
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "probes": probes,
    }


def register(app, state, load_contexts, run_with_audit):
    @app.command(name="health", help="Active health probe of the parent registry: /health, optionally its federation info and its ledger.")
    def health_cmd(
        strict: bool = typer.Option(False, "--strict", help="Also probe the federation info and the ledger."),
        include_federation: bool = typer.Option(False, "--include-federation",
                                                help="Also probe /api/v1/federation/info."),
        include_eventstore: bool = typer.Option(False, "--include-eventstore",
                                                help="Also read the supply invariant the parent reads from its "
                                                     "ledger (/api/v1/public/supply-invariant); green only on OK."),
    ):
        out = Output(detect_output_mode(state.json_mode, state.quiet, state.no_color))
        if strict:
            include_federation = True
            include_eventstore = True

        contexts = load_contexts()
        results: List[Dict[str, Any]] = []
        for ctx in contexts:
            results.append(run_with_audit("health", ctx.name, _build_health, ctx,
                                          include_federation=include_federation,
                                          include_eventstore=include_eventstore))

        if out.mode == "json":
            out.emit_json(results[0] if len(results) == 1 else {"operators": results})
        else:
            for r in results:
                badge = "[bold green]GREEN[/]" if r["verdict"] == "green" else "[bold red]RED[/]"
                out.line(f"\nOperator: [bold]{r['operator']['name']}[/]  {badge}")
                rows = [[p["url"], str(p["status"]), ("ok" if p["ok"] else "fail")
                         + (f" ({p['ledger']})" if p.get("ledger") else "")] for p in r["probes"]]
                out.table("probes", ["URL", "HTTP", "OK"], rows)

        worst = "green"
        for r in results:
            if r["verdict"] == "red":
                worst = "red"
                break
        if worst == "red":
            raise typer.Exit(code=2)
        raise typer.Exit(code=0)
