"""§MCPTEST30 (V0528, 2026-10-01) — a credential stops working the moment it is revoked, on every worker.

The lifecycles that remove a credential read a LIST afterwards (getMyApiKeys shows the key revoked, getMyAgents shows
the agent revoked); none of them used the credential again, which is the only question its holder asks. A revocation
that is recorded but not enforced (a per-worker cache of resolved keys, a token path that checks a flag the delete
does not set) reads as perfectly revoked in every list. The registry runs several workers, so each credential is
asked several times on fresh connections: a cache would answer on the worker that warmed it.

Rows (counts and kinds only, never a credential):
- `revocation: revokeApiKey`: a throwaway API key reads the developer's own profile (the control), is revoked, then
  asks again on fresh connections. Every ask after the revoke must be refused.
- `revocation: deleteMyApiKey`: the same with the delete.
- `revocation: deleteMyAgentByDev`: a throwaway agent's token reads its own info (the control), the developer deletes
  the agent, then the token asks again and the agent's credentials ask for a new token. Every ask must be refused.
Right: the control answered and every ask after was refused. The finding: any ask after the removal answered.
NOT MEASURED: the control did not answer (nothing to revoke).
"""
from __future__ import annotations

import secrets
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

PREFIX = "revocation: "
CONTROL_ASKS = 3
AFTER_ASKS = 9   # on fresh connections: a per-worker cache answers on the worker one of the control asks warmed


def verdict(what: str, control: List[bool], after: List[bool]) -> Tuple[Optional[bool], Optional[str], Optional[str]]:
    """(healthy, fail, skip) for one credential: `control` = the asks before the removal answered, `after` = the asks
    after it answered."""
    if not control or not any(control):
        return None, None, f"NOT MEASURED: the {what} did not work before its removal (the control)"
    if not after:
        return None, None, f"NOT MEASURED: the {what} was not asked again after its removal"
    n = sum(1 for a in after if a)
    if n:
        return False, (f"BUG-FIND: revocation: the {what} still answered {n} of {len(after)} asks after its removal: "
                       "a removed credential must be refused at once, on every worker"), None
    return True, None, None


async def _asks(call: Callable, tool: str, args: Dict[str, Any], jwt: str, n: int) -> List[bool]:
    out = []
    for _ in range(n):
        ok, _inner, _code = await call(tool, args, jwt)
        out.append(bool(ok))
    return out


async def run_revocation(rpc: Callable, parse: Callable, bag: Any, outcomes: Dict[str, dict], make_outcome: Callable,
                         answered: Callable, said: Callable) -> None:
    dev = getattr(bag, "developer_jwt", "") or ""

    async def call(tool, args, jwt, timeout=30):
        ok, body, code = await rpc(tool, args, jwt=jwt, timeout=timeout)
        inner = parse(body)
        return answered(ok, inner, code), inner, code

    def row(name: str, t0: float, healthy, fail, skip, ev: Dict[str, Any]) -> None:
        key = PREFIX + name
        outcomes[key] = make_outcome(key, "revocation", bool(healthy), "0", int((time.time() - t0) * 1000),
                                     fail if healthy is False else None, {}, expect_status="any", skip_reason=skip)
        outcomes[key]["result_excerpt"] = ev

    if not dev:
        for name in ("revokeApiKey", "deleteMyApiKey", "deleteMyAgentByDev"):
            row(name, time.time(), None, None, "NOT MEASURED: the run has no developer token", {})
        return
    tag = secrets.token_hex(5)

    # the two API keys
    for remover in ("revokeApiKey", "deleteMyApiKey"):
        t0 = time.time()
        ev: Dict[str, Any] = {}
        ok, inner, code = await call("theprotocol_createApiKey", {"key_name": f"mcp-rev-{remover[:6]}-{tag}"}, dev)
        key = inner.get("plain_api_key") if ok and isinstance(inner, dict) else None
        kid = (inner.get("api_key_info") or {}).get("id") if ok and isinstance(inner, dict) else None
        if not key or not kid:
            row(remover, t0, None, None, f"NOT MEASURED: no throwaway API key could be made ({said(inner)[:90]})", ev)
            continue
        try:
            control = await _asks(call, "theprotocol_getMyDeveloperProfile", {}, key, CONTROL_ASKS)
            okr, ri, _c = await call(f"theprotocol_{remover}",
                                     {"key_id": kid if remover == "revokeApiKey" else str(kid)}, dev)
            ev.update({"control_answered": sum(control), "removed": bool(okr)})
            if not okr:
                row(remover, t0, None, None, f"NOT MEASURED: {remover} refused ({said(ri)[:90]})", ev)
                continue
            after = await _asks(call, "theprotocol_getMyDeveloperProfile", {}, key, AFTER_ASKS)
            ev["after_answered"] = sum(after)
            healthy, fail, skip = verdict("API key", control, after)
            row(remover, t0, healthy, fail, skip, ev)
        finally:
            key = None
            if remover == "revokeApiKey":   # a revoked key is still listed; the run removes it
                await call("theprotocol_deleteMyApiKey", {"key_id": str(kid)}, dev)

    # the agent
    t0 = time.time()
    ev = {}
    ok, inner, code = await call("theprotocol_createAgent", {
        "name": f"mcp-rev-{tag}", "description": "MCP tester revocation probe (throwaway, deleted by the probe)"}, dev)
    did = cid = sec = None
    if ok and isinstance(inner, dict):
        did, cid, sec = inner.get("agent_did") or inner.get("did"), inner.get("client_id"), inner.get("client_secret")
    if not (did and cid and sec):
        return row("deleteMyAgentByDev", t0, None, None,
                   f"NOT MEASURED: no throwaway agent could be made ({said(inner)[:90]})", ev)
    deleted = False
    try:
        okt, ti, _c = await call("theprotocol_getAgentToken", {"client_id": cid, "client_secret": sec}, dev)
        token = (ti.get("access_token") or ti.get("agent_jwt")) if okt and isinstance(ti, dict) else None
        if not token:
            return row("deleteMyAgentByDev", t0, None, None, "NOT MEASURED: the throwaway agent's token", ev)
        control = await _asks(call, "theprotocol_getMyAgentInfo", {"agent_jwt": token}, dev, CONTROL_ASKS)
        okd, di, _c = await call("theprotocol_deleteMyAgentByDev", {"agent_did": did}, dev)
        deleted = bool(okd)
        ev.update({"control_answered": sum(control), "removed": deleted})
        if not deleted:
            return row("deleteMyAgentByDev", t0, None, None, f"NOT MEASURED: the delete refused ({said(di)[:90]})", ev)
        after = await _asks(call, "theprotocol_getMyAgentInfo", {"agent_jwt": token}, dev, AFTER_ASKS)
        okn, _ni, _c = await call("theprotocol_getAgentToken", {"client_id": cid, "client_secret": sec}, dev)
        after.append(bool(okn))
        ev.update({"after_answered": sum(after[:-1]), "new_token_issued": bool(okn)})
        healthy, fail, skip = verdict("deleted agent's token or credentials", control, after)
        row("deleteMyAgentByDev", t0, healthy, fail, skip, ev)
    finally:
        sec = None
        if not deleted:
            await call("theprotocol_deleteMyAgentByDev", {"agent_did": did}, dev)
