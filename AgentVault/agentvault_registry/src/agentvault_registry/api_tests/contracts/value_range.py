"""§MCPTEST30 (V0525, 2026-10-01) — a value its type can carry but the database cannot is the caller's refusal, never a 5xx.

JSON and Python carry any integer; Postgres refuses an int4 column past 2^31-1 and an int8 past 2^63-1, and asyncpg
refuses to encode one ("invalid input for query argument $1: ... (value out of int32 range)"). A date-like string that
is no date (or an impossible one, or a five-digit year) reaches a parser or the database the same way. Measured by hand
on sbx-alpha (V0521) before this probe existed, 298 calls over every read-only tool: getProposalDetail answered 500 for
an id past int32 and past int64 and handed the caller the driver's own sentence; /teg/transactions forwarded offset=2^63
to the TEG, whose "bigint out of range" came back as 503 "Unable to fetch transaction history at this time". V0525 holds
both (errors.withheld_db_words, the TEG proxy's paging bounds).

Every READ-ONLY tool (the server's readOnlyHint) is asked once per integer argument with 2^31 and 2^63 (a page SIZE
argument with 2^63 only: 2^31 is a valid integer and an uncapped route would read a whole table for it, which
page_bounds already measures with 5000), once per number argument with 1e308, and once per date-like string argument
with a non-date, 30 February and the year 99999. Every other required argument gets a value of its own type. Through
the raw JSON-RPC transport, so the code is read. Right: -32602, a refusal (4xx), or an answer (the value used, capped or
matched nothing). Findings: -32603 or another JSON-RPC error, a tool-side exception, a 5xx, or an answer carrying a
database driver's own words. Rows `range: <tool>`; they keep kinds, never a value.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from agentvault_registry.api_tests.contracts.credential_exposure import DB_WORDS
from agentvault_registry.api_tests.contracts.type_confusion import GOOD, LEFT_OUT, NEVER_SET, _type

PREFIX = "range: "
INT_VALUES: Tuple[Tuple[str, int], ...] = (("int32+1", 2 ** 31), ("int64+1", 2 ** 63))
SIZE_VALUES: Tuple[Tuple[str, int], ...] = (("int64+1", 2 ** 63),)
NUMBER_VALUES: Tuple[Tuple[str, float], ...] = (("1e308", 1e308),)
DATE_VALUES: Tuple[Tuple[str, str], ...] = (("not-a-date", "not-a-date"), ("feb30", "2026-02-30T00:00:00Z"),
                                            ("year99999", "99999-01-01T00:00:00Z"))
# a page SIZE: an uncapped route would read a whole table for 2^31 (page_bounds measures caps with 5000)
SIZE_NAMES = frozenset({"limit", "page_size", "per_page", "size", "max_results", "max_items", "count", "top", "n",
                        "batch_size", "max_rows"})
_DATE_NAME = re.compile(r"(^|_)(since|until|before|after|from|to|start|end|date|time|day|at|expires|created|updated)($|_)")
_STATUS = re.compile(r"\b(?:HTTP|returned)\s+(\d{3})\b")
_CRASH = re.compile(r"\b(TypeError|AttributeError|ValueError|KeyError|IndexError|InvalidOperation|OverflowError|"
                    r"UnboundLocalError|NameError)\b")

Target = Tuple[str, str, Dict[str, Any], List[Tuple[str, str, Any]]]


def values_for(param: str, spec: Any) -> Tuple[Tuple[str, Any], ...]:
    """The out-of-range values one argument is asked with (none for an argument this probe does not measure)."""
    ty = _type(spec)
    if ty == "integer":
        return SIZE_VALUES if param in SIZE_NAMES else INT_VALUES
    if ty == "number":
        return NUMBER_VALUES
    if ty == "string" and isinstance(spec, dict) and not spec.get("enum") and (
            spec.get("format") in ("date", "date-time") or _DATE_NAME.search(param)):
        return DATE_VALUES
    return ()


def targets(public_schemas: Iterable[dict], admin_schemas: Iterable[dict], tier2: Iterable[str],
            annotate: Callable[[str], Dict[str, bool]]) -> List[Target]:
    """(tool, tier: '1' public, '2' public with the sentinel agent, 'admin', base arguments, [(param, label, value)])."""
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
            cases = [(p, label, value) for p, v in sorted(props.items()) if p not in NEVER_SET
                     for label, value in values_for(p, v)]
            if not cases:
                continue
            tier = "admin" if surface == "admin" else ("2" if name in t2 else "1")
            out.append((name, tier, base, cases))
    return out


def default_targets() -> List[Target]:
    from agentvault_registry.mcp import server as S
    from agentvault_registry.mcp import server_admin as SA
    from agentvault_registry.mcp.tool_metadata import derive_annotations
    return targets(S.ALL_TOOL_SCHEMAS, SA.ADMIN_TOOL_SCHEMAS, S.TIER2_TOOLS, derive_annotations)


def answer_kind(code: Any, parsed: Any) -> str:
    """invalid_params | refused | answered | no_answer | jsonrpc_error <code> | tool_crash <class> | server_error |
    db_words (any answer, refusal or not, that carries a database driver's own words)."""
    if not isinstance(parsed, dict) or not parsed:
        return "no_answer"
    if DB_WORDS.search(json.dumps(parsed, default=str)):
        return "db_words"
    err = parsed.get("error")
    if isinstance(err, dict):   # §MCPTEST30 V0529: -32003 = the registry could not check the credential (busy)
        c = err.get("code")
        return "invalid_params" if c == -32602 else ("unavailable" if c == -32003 else f"jsonrpc_error {c}")
    res = parsed.get("result")
    if not isinstance(res, dict):
        return "no_answer"
    if not res.get("isError"):
        return "answered"
    content = res.get("content") or []
    text = content[0].get("text", "") if content and isinstance(content[0], dict) else json.dumps(res, default=str)
    m = _STATUS.search(text)
    st = int(m.group(1)) if m else None
    if (st and st >= 500) or "Internal Server Error" in text:
        return f"server_error {st}" if st else "server_error"
    crash = _CRASH.search(text)
    if crash and not st:
        return f"tool_crash {crash.group(1)}"
    return "refused"


_FINE = ("invalid_params", "refused", "answered", "no_answer", "unavailable")


def verdict(kinds: Dict[str, str]) -> Tuple[Optional[bool], Optional[str], Dict[str, Any]]:
    ev: Dict[str, Any] = dict(kinds)
    bad = {p: k for p, k in kinds.items() if not k.startswith(_FINE)}
    if bad:
        return False, ("BUG-FIND: range: a value its JSON type carries but the database cannot was not refused ("
                       + ", ".join(f"{p}: {k}" for p, k in sorted(bad.items())) + "): a route must refuse it (4xx) "
                       "before its SQL does, and never answer with the driver's words"), ev
    if all(k in ("no_answer", "unavailable") for k in kinds.values()):
        return None, ("NOT MEASURED: no out-of-range call came back over MCP"
                      + (" (the registry could not check credentials: -32003)" if "unavailable" in kinds.values() else "")), ev
    return True, None, ev


async def run_range(raw: Optional[Callable], bag: Any, outcomes: Dict[str, dict], make_outcome: Callable,
                    todo: Optional[List[Target]] = None) -> None:
    """One `range: <tool>` row per target, each argument asked once per out-of-range value (read only); targets a few
    at a time (api_tests/contracts/probe_pool.py)."""
    from agentvault_registry.api_tests.contracts import probe_pool

    async def one(target: Target) -> None:
        tool, tier, base, cases = target
        t0 = time.time()
        name = PREFIX + tool.replace("theprotocol_", "")
        if raw is None:
            outcomes[name] = make_outcome(name, "range", False, "0", 0, None, {}, expect_status="any",
                                          skip_reason="NOT MEASURED: the runner injected no raw JSON-RPC transport")
            return
        jwt = getattr(bag, "developer_jwt", "") or ""
        args0 = dict(base)
        if tier == "2":
            if not getattr(bag, "sentinel_jwt", None):
                outcomes[name] = make_outcome(name, "range", False, "0", 0, None, {}, expect_status="any",
                                              skip_reason="NOT MEASURED: no sentinel agent token")
                return
            args0["agent_jwt"] = bag.sentinel_jwt
        kinds: Dict[str, str] = {}
        last: Any = 0
        for p, label, value in cases:
            args = dict(args0)
            args[p] = value
            body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}})
            code, parsed, _x = await raw(body, path="/mcp/admin/rpc" if tier == "admin" else "/mcp/rpc", jwt=jwt, timeout=30)
            kinds[f"{p}={label}"], last = answer_kind(code, parsed), code
        healthy, sentence, ev = verdict(kinds)
        outcomes[name] = make_outcome(name, "range", bool(healthy), str(last or "0"), int((time.time() - t0) * 1000),
                                      sentence if healthy is False else None, {}, expect_status="any",
                                      skip_reason=sentence if healthy is None else None)
        outcomes[name]["result_excerpt"] = ev
    await probe_pool.each(todo if todo is not None else default_targets(), one)
