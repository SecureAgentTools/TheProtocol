"""§MCPTEST30 (V0548) — does each MCP tool say so when its request fails? (helper, not a test file)

Run in a fresh process (the gate does this): it imports tests/mcp_request_survey.py (which imports the app and records
every request), then answers every request this registry receives with 503 and an RFC 7807 body, calls every tool the
way its dispatcher does with only the arguments its schema requires, and reads the result. A tool that made a request
and answers WITHOUT a trace of the failure (no error, upstream_error or status_code of 400 and above, no Error text,
no success:false) swallowed it: its caller reads a failed read as a real answer. Measured on V0546, ten tools answered
an empty list for a request that failed (getMyAgentLogs, getMyDeveloperActivity, getProposalVotes,
getPublicEventStoreRecent, listDeveloperApikeysMe, listDeveloperWebhooks, listFederationRegistries and the three peer
feeds); 702 said the failure.

    python mcp_failure_census.py [--json OUT]
"""
from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, Dict

_argv = list(sys.argv)
sys.argv = [sys.argv[0]]
import httpx  # noqa: E402
import mcp_request_survey as S  # noqa: E402  (imports the app; its 200 recorder is replaced below)

sys.argv = _argv

BODY = {"type": "about:blank", "title": "Service Unavailable", "status": 503, "detail": "phase6: the route is down"}


async def _refused(self, request, *a, **k):
    await request.aread()
    S.CAPTURED.append(request)
    return httpx.Response(503, json=BODY, request=request)


def _refused_sync(self, request, *a, **k):
    request.read()
    S.CAPTURED.append(request)
    return httpx.Response(503, json=BODY, request=request)


httpx.AsyncClient.send = _refused  # type: ignore[assignment]
httpx.Client.send = _refused_sync  # type: ignore[assignment]


def says_failure(value: Any) -> bool:
    """Whether a tool's result carries the failure (the dispatcher renders `error` as a failed call, the B6 envelope
    carries status_code and upstream_error, an older wrapper's text says Error)."""
    if isinstance(value, dict):
        if value.get("error") or value.get("upstream_error"):
            return True
        sc = value.get("status_code")
        if isinstance(sc, int) and sc >= 400:
            return True
        text = value.get("_text")
        if isinstance(text, str) and ("Error" in text or "HTTP 5" in text):
            return True
        if value.get("success") is False or value.get("ok") is False:
            return True
        return any(says_failure(v) for v in value.values() if isinstance(v, dict))
    if isinstance(value, str):
        return "Error" in value or "503" in value or "unavailable" in value.lower()
    return False


async def census() -> Dict[str, Any]:
    from agentvault_registry.mcp import tools_admin
    from agentvault_registry.mcp.auth_bridge import MCPAuthContext
    self_host = S.urlsplit(tools_admin.REGISTRY_SELF_URL).netloc
    agent = MCPAuthContext(auth_type="agent", agent_did="did:theprotocol:phase6-self", agent_id=1, raw_token=S.AGENT_TOKEN)
    out: Dict[str, Any] = {"tools": 0, "said": 0, "no_request": 0, "raised": 0, "swallowed": {}}
    for surface in ("admin", "public"):
        if surface == "admin":
            from agentvault_registry.mcp import server_admin as s
            dispatch, schemas, noauth, tier2 = s.ADMIN_TOOL_DISPATCH, s.ADMIN_TOOL_SCHEMAS, set(s.ADMIN_NO_AUTH_TOOLS), set()
        else:
            from agentvault_registry.mcp import server as s
            dispatch, schemas = s.TOOL_DISPATCH, s.ALL_TOOL_SCHEMAS
            noauth, tier2 = set(dispatch) - set(s.AUTH_REQUIRED_TOOLS), set(s.TIER2_TOOLS)
        auth = MCPAuthContext(auth_type="developer", developer_id=1, is_admin=(surface == "admin"), raw_token=S.DEV_TOKEN)
        by = {sc["name"]: sc for sc in schemas if isinstance(sc, dict) and "name" in sc}
        for name, fn in sorted(dispatch.items()):
            sc = by.get(name)
            if sc is None or name.endswith(S.GATEWAY_TOOLS):
                continue
            out["tools"] += 1
            S.CAPTURED.clear()
            try:
                a = S.args_for(sc, False)
                if name in noauth:
                    result = await asyncio.wait_for(fn(**a), 8)
                elif name in tier2:
                    result = await asyncio.wait_for(fn(agent, **a), 8)
                else:
                    result = await asyncio.wait_for(fn(auth, **a), 8)
            except Exception:  # noqa: BLE001 — a raise reaches the dispatcher, which answers it as a failure
                out["raised"] += 1
                continue
            own = [rq for rq in S.CAPTURED
                   if (rq.url.netloc.decode() if isinstance(rq.url.netloc, bytes) else rq.url.netloc) == self_host]
            if not own:
                out["no_request"] += 1
            elif says_failure(result):
                out["said"] += 1
            else:
                out["swallowed"][f"{surface}:{name}"] = json.dumps(result, default=str)[:200]
    return out


if __name__ == "__main__":
    res = asyncio.run(census())
    if "--json" in sys.argv:
        with open(sys.argv[sys.argv.index("--json") + 1], "w") as fh:
            json.dump(res, fh, indent=1, sort_keys=True)
    print(f"tools {res['tools']} · said the failure {res['said']} · no request {res['no_request']} · raised {res['raised']} · "
          f"SWALLOWED {len(res['swallowed'])}")
    for t, r in sorted(res["swallowed"].items()):
        print(f"  {t}: {r}")
