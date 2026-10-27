"""tp-operator sync — ask the parent frame to run a federation sync cycle now.

State-mutating: routed through run_with_audit so local + remote audit fire.

CB-289 (2026-10-16): this POSTed the federation licence to the parent's /api/v1/federation/sync/trigger, which never
accepts a licence (it takes a peer registry's certificate, the internal lane, or an admin developer token): the parent
answered 401, nothing ran, and the command exited 0 with the 401 printed as if it were an answer. It now makes the call
the way the operator's registry calls its parent (parent_call): on the parent's federation lane with the operator's
certificate, which the trigger accepts as a peer registry. The parent then runs its sync cycle (it pulls this
operator's agent cards, and every other peer's; it runs at most one every 30 seconds). Any answer but 200 is a refusal:
reported with the parent's reason, exit 3.
"""
from __future__ import annotations

from typing import Any, Dict

import typer

from ..config import OperatorContext
from ..http_client import timeout_or
from ..output import Output, detect_output_mode

TRIGGER = "/api/v1/federation/sync/trigger"


def sync_result(name: str, answer: Dict[str, Any]) -> Dict[str, Any]:
    """The parent's answer to the trigger, as `sync` reports it: triggered only on its 200."""
    from ..parent_call import answer_detail

    if answer.get("error"):
        return {"operator": name, "triggered": False, "status_code": 0, "lane": None,
                "reason": f"{answer['error']}: {answer.get('detail') or ''}".strip()[:300]}
    status = int(answer.get("status") or 0)
    out = {"operator": name, "status_code": status, "lane": answer.get("lane")}
    if status == 200:
        return {**out, "triggered": True, "reason": "the parent ran a sync cycle", "body": answer.get("body")}
    return {**out, "triggered": False, "reason": f"the parent refused (HTTP {status}): {answer_detail(answer)}"[:300]}


def _do_sync(ctx: OperatorContext) -> Dict[str, Any]:
    if ctx.is_frame:
        return {"operator": ctx.name, "triggered": False, "status_code": 0, "lane": None,
                "reason": "a frame has no parent frame to ask: sync is an operator's command"}
    from ..parent_call import call_parent

    # SEC-17: the global --timeout, else the trigger's own 60 s (the parent runs its whole sync cycle before it answers)
    return sync_result(ctx.name, call_parent(ctx, "POST", TRIGGER, TRIGGER, json_body={"cascade": False},
                                             timeout=timeout_or(60.0)))


def register(app, state, load_contexts, run_with_audit):
    @app.command(name="sync", help="Ask the parent frame to run a federation sync cycle now (through this operator's "
                                   "registry, on the parent's federation lane); exit 3 when it refuses.")
    def sync_cmd():
        out = Output(detect_output_mode(state.json_mode, state.quiet, state.no_color))
        contexts = load_contexts()
        results = []
        for ctx in contexts:
            if state.dry_run:
                out.line(f"[dim]DRY-RUN[/dim] would ask {ctx.name}'s parent frame to run a sync cycle ({TRIGGER})")
                continue
            results.append(run_with_audit("sync", ctx.name, _do_sync, ctx))

        if out.mode == "json":
            out.emit_json(results[0] if len(results) == 1 else {"operators": results})
        else:
            for r in results:
                badge = "[green]TRIGGERED[/]" if r["triggered"] else "[red]REFUSED[/]"
                via = f" via the {r['lane']}" if r.get("lane") else ""
                out.line(f"\nOperator: [bold]{r['operator']}[/] {badge}{via}  ({r.get('reason', '')[:200]})")
        raise typer.Exit(code=3 if any(not r["triggered"] for r in results) else 0)
