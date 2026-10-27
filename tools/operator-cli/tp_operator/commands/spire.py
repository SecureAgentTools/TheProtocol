"""tp-operator spire: enroll / revoke agents via the IRONHAND proxy, and list the parent's revoked identities.

SEC-08 (2026-10-17): `enroll` and `revoke` POSTed the licence from the host to the parent's /api/v1/admin/ironhand
proxies. A frame's public console clears X-Federation-License (every template frame, EU and ASIA among them), so the
parent answered 401 and no entry was made or deleted. They now ask the way the operator's registry does when one of its
agents enrols (parent_call, as `license verify` and `sync` do): through the operator's registry, on the parent's
federation lane, where the parent serves the same proxies under /api/v1/federation/ironhand to the operator's
certificate; the console path stays the fallback when the lane is unknown. Any answer but 200 exits 3 with the
parent's reason.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import typer

from .. import __schema_version__
from ..config import OperatorContext
from ..http_client import FederationClient, timeout_or
from ..output import Output, detect_output_mode

# (console path, federation lane path) of the parent's two IRONHAND proxies
ENROLL = ("/api/v1/admin/ironhand/register-agent-proxy", "/api/v1/federation/ironhand/register-agent-proxy")
REVOKE = ("/api/v1/admin/ironhand/delete-agent-proxy", "/api/v1/federation/ironhand/delete-agent-proxy")


def ask_parent(ctx: OperatorContext, paths: Tuple[str, str], body: Dict[str, Any]) -> Dict[str, Any]:
    """One IRONHAND proxy call to the parent, through this operator's registry (parent_call)."""
    from ..parent_call import call_parent

    console_path, lane_path = paths
    return call_parent(ctx, "POST", console_path, lane_path, json_body=body, timeout=timeout_or(30.0))


def refusal(answer: Dict[str, Any]) -> Optional[str]:
    """None when the parent answered 200; else why not, in one line (the parent's own reason when it gave one)."""
    from ..parent_call import answer_detail

    if answer.get("error"):
        return f"{answer['error']}: {answer.get('detail') or ''}".strip()[:300]
    status = int(answer.get("status") or 0)
    if status != 200:
        return f"HTTP {status}: {answer_detail(answer)}"[:300]
    return None


def register(app, state, load_contexts, run_with_audit):
    sub = typer.Typer(help="IRONHAND mTLS: enroll or revoke an agent's SPIRE entry; list the parent's revoked identities.")
    app.add_typer(sub, name="spire")

    @sub.command(name="list", help="List the SPIFFE IDs the parent registry has revoked (its public list for SDK "
                                   "polling, /api/v1/agent/revoked-identities). It lists no enrollments.")
    def spire_list():
        # CB-292: this said "List this operator's enrolled agents" while it reads the parent's public list of REVOKED
        # SPIFFE IDs (the one the SDK polls); no route lists an operator's enrollments to a licence holder.
        out = Output(detect_output_mode(state.json_mode, state.quiet, state.no_color))
        contexts = load_contexts()
        results = []
        for ctx in contexts:
            with FederationClient(ctx.mainframe_url, ctx.federation_license, timeout=timeout_or(15.0)) as fc:
                try:
                    r = fc.get("/api/v1/agent/revoked-identities")
                    data = r.json() if r.status_code == 200 else {"error": r.text[:200]}
                except Exception as e:
                    data = {"error": str(e)[:200]}
            results.append({"operator": ctx.name, "data": data})

        if out.mode == "json":
            out.emit_json(results[0] if len(results) == 1 else {"operators": results})
        else:
            for r in results:
                out.line(f"\nOperator: [bold]{r['operator']}[/]")
                if "error" in r["data"]:
                    out.error(r["data"]["error"])
                else:
                    out.emit_json(r["data"])
        raise typer.Exit(code=0)

    @sub.command(name="enroll", help="Ask the parent frame to create an agent's SPIRE entry under this operator's SPIRE "
                                     "agent (through this operator's registry, on the parent's federation lane); exit 3 "
                                     "when the parent refuses.")
    def spire_enroll(
        agent_did: str = typer.Argument(..., help="Agent DID, e.g. did:theprotocol:..."),
        parent_fingerprint: str = typer.Option(None, "--parent-fingerprint",
                                                help="Override OPERATOR_SPIRE_AGENT_FINGERPRINT from .env.operator"),
    ):
        out = Output(detect_output_mode(state.json_mode, state.quiet, state.no_color))
        contexts = load_contexts()
        if len(contexts) != 1:
            out.error("`spire enroll` operates on a single operator.")
            raise typer.Exit(code=1)
        ctx = contexts[0]
        if ctx.is_frame:
            out.error("`spire enroll` is an operator's command: a frame has no parent frame to ask.")
            raise typer.Exit(code=1)
        fp = parent_fingerprint or ctx.env.get("OPERATOR_SPIRE_AGENT_FINGERPRINT", "")
        if not fp:
            out.error("Missing parent fingerprint — provide --parent-fingerprint or set OPERATOR_SPIRE_AGENT_FINGERPRINT.")
            raise typer.Exit(code=1)

        if state.dry_run:
            out.line(f"[dim]DRY-RUN[/dim] would ask {ctx.name}'s parent frame to create the SPIRE entry of {agent_did} "
                     f"({ENROLL[1]}, through this operator's registry, on the parent's federation lane)")
            raise typer.Exit(code=0)

        def _do():
            answer = ask_parent(ctx, ENROLL, {"agent_did": agent_did, "parent_fingerprint": fp, "dns_sans": []})
            why = refusal(answer)
            if why:
                out.error(f"Enrollment failed: {why}")
                return 3
            data = answer.get("body") if isinstance(answer.get("body"), dict) else {}
            if out.mode == "json":
                out.emit_json({"operator": ctx.name, "spiffe_id": data.get("spiffe_id"), "agent_did": agent_did,
                               "lane": answer.get("lane")})
            else:
                out.success(f"Enrolled {agent_did} → {data.get('spiffe_id')} (via the {answer.get('lane')})")
            return 0

        rc = run_with_audit("spire enroll", ctx.name, _do)
        raise typer.Exit(code=rc)

    @sub.command(name="revoke", help="Ask the parent frame to delete an agent's SPIRE entry (through this operator's "
                                     "registry, on the parent's federation lane); exit 3 when the parent refuses.")
    def spire_revoke(
        agent_did: str = typer.Argument(..., help="Agent DID"),
    ):
        out = Output(detect_output_mode(state.json_mode, state.quiet, state.no_color))
        contexts = load_contexts()
        if len(contexts) != 1:
            out.error("`spire revoke` operates on a single operator.")
            raise typer.Exit(code=1)
        ctx = contexts[0]
        if ctx.is_frame:
            out.error("`spire revoke` is an operator's command: a frame has no parent frame to ask.")
            raise typer.Exit(code=1)

        if not state.yes and not state.dry_run:
            answer = typer.prompt(f"Revoke SPIRE entry for {agent_did}? Type yes", default="no")
            if answer.strip().lower() not in ("y", "yes"):
                raise typer.Exit(code=2)

        if state.dry_run:
            out.line(f"[dim]DRY-RUN[/dim] would ask {ctx.name}'s parent frame to delete the SPIRE entry of {agent_did} "
                     f"({REVOKE[1]}, through this operator's registry, on the parent's federation lane)")
            raise typer.Exit(code=0)

        def _do():
            answer = ask_parent(ctx, REVOKE, {"agent_did": agent_did})
            why = refusal(answer)
            if why:
                out.error(f"Revoke failed: {why}")
                return 3
            data = answer.get("body") if isinstance(answer.get("body"), dict) else {}
            if out.mode == "json":
                out.emit_json({"operator": ctx.name, "agent_did": agent_did, "deleted": data.get("deleted"),
                               "lane": answer.get("lane")})
            else:
                out.success(f"Revoked {agent_did} (deleted={data.get('deleted')}, via the {answer.get('lane')})")
            return 0

        rc = run_with_audit("spire revoke", ctx.name, _do)
        raise typer.Exit(code=rc)
