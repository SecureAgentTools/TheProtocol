"""§MCPTEST30 (V0524, 2026-10-01) — an argument of the wrong JSON type is the caller's -32602, never the server's -32603.

Measured by hand on sbx-alpha (V0521) before this probe existed: every read-only tool asked once per typed argument with
a value of the wrong type answered, of 107 calls, 72 times -32603 "Internal error" (an integer sent as "abc" reached the
tool's own int() or max()), 20 times -32602, twice a crash inside the tool. V0524 checks tools/call arguments against
each tool's inputSchema in both dispatchers (mcp/arguments.py).

Every READ-ONLY tool (the server's own readOnlyHint) with a typed argument (integer, number, boolean, array, object) is
asked once per such argument with a value nothing can mean for it ("abc", "maybe", 5 for an array, a list for an
object); every other required argument gets a value of its own type. Through the raw JSON-RPC transport on the bridge
the tool lives on, so the error CODE is read, not a rendering of it. Right: -32602, or a refusal the route gave (4xx).
Findings: -32603 or another JSON-RPC error, a tool-side exception, a 5xx, or a call that ACCEPTED the value (its schema
cannot take it). Rows `types: <tool>`; they keep codes and kinds, never a value.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

PREFIX = "types: "
BAD: Dict[str, Any] = {"integer": "abc", "number": "abc", "boolean": "maybe", "array": 5, "object": ["not", "an", "object"]}
GOOD: Dict[str, Any] = {"integer": 1, "number": 1, "boolean": False, "array": [], "object": {}, "string": "mcp-probe"}
NEVER_SET = frozenset({"agent_jwt", "developer_jwt", "agent_token", "client_id", "client_secret", "token", "password"})
LEFT_OUT = frozenset({"theprotocol_getAgentToken", "theprotocol_oauthIntrospect", "theprotocol_compositeHealthCheck",
                      "theprotocol_getPublicShowcaseCall", "theprotocol_probeTopologyPeer"})
_STATUS = re.compile(r"\b(?:HTTP|returned)\s+(\d{3})\b")
_CRASH = re.compile(r"\b(TypeError|AttributeError|ValueError|KeyError|IndexError|InvalidOperation|UnboundLocalError|NameError)\b")

Target = Tuple[str, str, Dict[str, Any], List[Tuple[str, Any]]]


def _type(spec: Any) -> Optional[str]:
    t = spec.get("type") if isinstance(spec, dict) else None
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), None)
    return t if isinstance(t, str) else None


def targets(public_schemas: Iterable[dict], admin_schemas: Iterable[dict], tier2: Iterable[str],
            annotate: Callable[[str], Dict[str, bool]]) -> List[Target]:
    """(tool, tier: '1' public, '2' public with the sentinel agent, 'admin', the base arguments, and each typed
    argument with the value nothing can mean for its type)."""
    t2 = set(tier2)
    out: List[Target] = []
    seen = set()
    for surface, schemas in (("public", public_schemas), ("admin", admin_schemas)):
        for t in schemas:
            name = (t or {}).get("name") or ""
            if not name or name in seen:
                continue
            seen.add(name)
            if name in LEFT_OUT:
                continue
            try:
                if not annotate(name).get("readOnlyHint"):
                    continue
            except Exception:  # noqa: BLE001
                continue
            schema = t.get("inputSchema") or {}
            props = schema.get("properties") or {}
            required = set(schema.get("required") or [])
            base = {p: GOOD[_type(v)] for p, v in props.items()
                    if p in required and p not in NEVER_SET and _type(v) in GOOD}
            typed = sorted((p, BAD[_type(v)]) for p, v in props.items() if p not in NEVER_SET and _type(v) in BAD)
            if not typed:
                continue
            tier = "admin" if surface == "admin" else ("2" if name in t2 else "1")
            out.append((name, tier, base, typed))
    return out


def default_targets() -> List[Target]:
    from agentvault_registry.mcp import server as S
    from agentvault_registry.mcp import server_admin as SA
    from agentvault_registry.mcp.tool_metadata import derive_annotations
    return targets(S.ALL_TOOL_SCHEMAS, SA.ADMIN_TOOL_SCHEMAS, S.TIER2_TOOLS, derive_annotations)


def answer_kind(code: Any, parsed: Any) -> str:
    """invalid_params | refused | accepted | no_answer | unavailable | jsonrpc_error <code> | tool_crash <class> |
    server_error. `unavailable` = -32003, the registry could not check the credential (its database did not answer,
    §MCPTEST30 V0529): a busy registry, which measures nothing about the tool."""
    if not isinstance(parsed, dict) or not parsed:
        return "no_answer"
    err = parsed.get("error")
    if isinstance(err, dict):
        c = err.get("code")
        return "invalid_params" if c == -32602 else ("unavailable" if c == -32003 else f"jsonrpc_error {c}")
    res = parsed.get("result")
    if not isinstance(res, dict):
        return "no_answer"
    if not res.get("isError"):
        return "accepted"
    content = res.get("content") or []
    text = content[0].get("text", "") if content and isinstance(content[0], dict) else json.dumps(res, default=str)
    m = _STATUS.search(text)
    st = int(m.group(1)) if m else None
    if (st and st >= 500) or "Internal Server Error" in text:
        return "server_error"
    crash = _CRASH.search(text)
    if crash and not st:
        return f"tool_crash {crash.group(1)}"
    return "refused"


def verdict(kinds: Dict[str, str]) -> Tuple[Optional[bool], Optional[str], Dict[str, Any]]:
    ev: Dict[str, Any] = dict(kinds)
    bad = {p: k for p, k in kinds.items() if k not in ("invalid_params", "refused", "no_answer", "unavailable")}
    if bad:
        return False, ("BUG-FIND: types: an argument of the wrong JSON type was not refused as invalid params ("
                       + ", ".join(f"{p}: {k}" for p, k in sorted(bad.items())) + "): the dispatcher must check "
                       "tools/call arguments against the tool's inputSchema (-32602)"), ev
    if all(k in ("no_answer", "unavailable") for k in kinds.values()):
        return None, ("NOT MEASURED: no mistyped call came back over MCP"
                      + (" (the registry could not check credentials: -32003)" if "unavailable" in kinds.values() else "")), ev
    return True, None, ev


async def run_types(raw: Optional[Callable], bag: Any, outcomes: Dict[str, dict], make_outcome: Callable,
                    todo: Optional[List[Target]] = None) -> None:
    """One `types: <tool>` row per target, each typed argument mistyped once (read only), through the raw transport;
    targets a few at a time (api_tests/contracts/probe_pool.py, V0525)."""
    from agentvault_registry.api_tests.contracts import probe_pool

    async def one(target: Target) -> None:
        tool, tier, base, typed = target
        t0 = time.time()
        name = PREFIX + tool.replace("theprotocol_", "")
        if raw is None:
            outcomes[name] = make_outcome(name, "types", False, "0", 0, None, {}, expect_status="any",
                                          skip_reason="NOT MEASURED: the runner injected no raw JSON-RPC transport")
            return
        jwt = getattr(bag, "developer_jwt", "") or ""
        args0 = dict(base)
        if tier == "2":
            if not getattr(bag, "sentinel_jwt", None):
                outcomes[name] = make_outcome(name, "types", False, "0", 0, None, {}, expect_status="any",
                                              skip_reason="NOT MEASURED: no sentinel agent token")
                return
            args0["agent_jwt"] = bag.sentinel_jwt
        kinds: Dict[str, str] = {}
        last: Any = 0
        for p, bad in typed:
            args = dict(args0)
            args[p] = bad
            body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}})
            code, parsed, _x = await raw(body, path="/mcp/admin/rpc" if tier == "admin" else "/mcp/rpc", jwt=jwt, timeout=30)
            kinds[p], last = answer_kind(code, parsed), code
        healthy, sentence, ev = verdict(kinds)
        outcomes[name] = make_outcome(name, "types", bool(healthy), str(last or "0"), int((time.time() - t0) * 1000),
                                      sentence if healthy is False else None, {}, expect_status="any",
                                      skip_reason=sentence if healthy is None else None)
        outcomes[name]["result_excerpt"] = ev
    await probe_pool.each(todo if todo is not None else default_targets(), one)

