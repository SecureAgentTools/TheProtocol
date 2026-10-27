"""§MCPTEST30 (V0528, 2026-10-01) — an API key's scopes bound what it reaches through MCP.

AL-4 (2026-07-24) lets a developer mint a key narrower than `*`; §MCPSCOPE (2026-08-27) made the MCP bridge ask the
question the REST admin gate asks: a key without `mcp:admin` (or `*`) gets no admin surface even when its developer is
an admin, and a key without `keys:manage` mints no key. Nothing measured either through MCP since. The probe mints, as
the run's admin developer, throwaway keys over REST (the MCP createApiKey tool takes no scopes):
- `scope: narrowed key, admin surface`: a key scoped ["mcp:read"] reads its developer's profile (the control) and must
  be refused an admin read tool on /mcp/admin/rpc;
- `scope: narrowed key, key minting`: the same key must be refused createApiKey;
- `scope: mcp:admin key, admin surface`: a key scoped ["mcp:admin"] must be ANSWERED by the same admin read (the
  positive control: the gate is not "refuse every scoped key"), and the developer's own token answers it too.
Counts and kinds only, never a key. Every key the probe made is deleted again (and one a narrowed key could mint).
"""
from __future__ import annotations

import json
import secrets
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

PREFIX = "scope: "
ADMIN_READ = "theprotocol_getEventEmissionPolicies"   # an admin-only read: no state moves when it answers
NARROW = ["mcp:read"]


def verdict(case: str, control: Optional[bool], asked: Optional[bool], want_answer: bool
            ) -> Tuple[Optional[bool], Optional[str], Optional[str]]:
    """(healthy, fail, skip). `control` = the key worked where it should (None when not asked); `asked` = the scoped call
    answered."""
    if control is False:
        return None, None, f"NOT MEASURED: {case}: the key did not work where its scope allows (the control)"
    if asked is None:
        return None, None, f"NOT MEASURED: {case}: the scoped call could not be made"
    if want_answer and not asked:
        return False, (f"BUG-FIND: scope: {case}: a key carrying the scope was refused: the gate refuses scoped keys "
                       "it should admit"), None
    if not want_answer and asked:
        return False, (f"BUG-FIND: scope: {case}: a key WITHOUT the scope was answered: an API key's scopes do not "
                       "bound what it reaches through MCP"), None
    return True, None, None


async def run_scopes(rpc: Callable, parse: Callable, bag: Any, outcomes: Dict[str, dict], make_outcome: Callable,
                     answered: Callable, said: Callable) -> None:
    dev = getattr(bag, "developer_jwt", "") or ""
    http = getattr(bag, "http_in_target", None)
    raw = getattr(bag, "rpc_raw", None)
    cases = ("narrowed key, admin surface", "narrowed key, key minting", "mcp:admin key, admin surface")
    t0 = time.time()

    def row(case, healthy, fail, skip, ev):
        key = PREFIX + case
        outcomes[key] = make_outcome(key, "scope", bool(healthy), "0", int((time.time() - t0) * 1000),
                                     fail if healthy is False else None, {}, expect_status="any", skip_reason=skip)
        outcomes[key]["result_excerpt"] = ev

    if not dev or http is None or raw is None:
        for c in cases:
            row(c, None, None, "NOT MEASURED: the run has no developer token, in-target HTTP or raw transport", {})
        return

    async def call(tool, args, jwt):
        ok, body, code = await rpc(tool, args, jwt=jwt, timeout=30)
        inner = parse(body)
        return answered(ok, inner, code), inner

    async def admin_read(jwt) -> Optional[bool]:
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": ADMIN_READ, "arguments": {}}})
        code, parsed, _x = await raw(body, path="/mcp/admin/rpc", jwt=jwt, timeout=30)
        if not isinstance(parsed, dict) or not parsed:
            return None
        if parsed.get("error"):
            return False
        res = parsed.get("result") or {}
        return isinstance(res, dict) and not res.get("isError")

    tag = secrets.token_hex(5)
    made: List[Any] = []

    async def mint(scopes) -> Tuple[Optional[str], Any]:
        code, text = await http("POST", "/api/v1/auth/api-keys", bearer=dev, body=json.dumps(
            {"key_name": f"mcp-scope-{scopes[0].replace(':', '-')}-{tag}", "scopes": scopes, "expires_in_days": 1}).encode())
        try:
            j = json.loads(text) if code.startswith("2") else {}
        except ValueError:
            j = {}
        kid = (j.get("api_key_info") or {}).get("id") if isinstance(j, dict) else None
        if kid is not None:
            made.append(kid)
        return (j.get("plain_api_key") if isinstance(j, dict) else None), kid

    try:
        narrow, _nk = await mint(NARROW)
        admin, _ak = await mint(["mcp:admin"])
        ev: Dict[str, Any] = {"narrowed_minted": bool(narrow), "admin_minted": bool(admin)}
        if not narrow or not admin:
            for c in cases:
                row(c, None, None, "NOT MEASURED: the throwaway scoped keys could not be minted over REST", ev)
            return
        control, _ = await call("theprotocol_getMyDeveloperProfile", {}, narrow)
        withheld = await admin_read(narrow)
        h, f, s = verdict(cases[0], control, withheld, want_answer=False)
        row(cases[0], h, f, s, {**ev, "control_answered": control, "admin_read_answered": withheld})

        minted, inner = await call("theprotocol_createApiKey", {"key_name": f"mcp-scope-escalation-{tag}"}, narrow)
        if minted and isinstance(inner, dict):
            stray = (inner.get("api_key_info") or {}).get("id")
            if stray is not None:
                made.append(stray)
        h, f, s = verdict(cases[1], control, minted, want_answer=False)
        row(cases[1], h, f, s, {"control_answered": control, "minted": minted})

        full = await admin_read(dev)
        granted = await admin_read(admin)
        h, f, s = verdict(cases[2], full, granted, want_answer=True)
        row(cases[2], h, f, s, {"developer_token_answered": full, "mcp_admin_key_answered": granted})
    finally:
        narrow = admin = None
        for kid in made:
            await call("theprotocol_deleteMyApiKey", {"key_id": str(kid)}, dev)
