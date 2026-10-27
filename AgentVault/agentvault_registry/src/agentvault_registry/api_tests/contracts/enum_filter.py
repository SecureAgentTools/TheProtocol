"""§MCPTEST30 (2026-10-01) — every value a tool's enum filter advertises is one its route applies.

The dispatcher enforces a tool's inputSchema (V0524), so an enum IS the vocabulary a client may speak. When it differs from
the route's, the filter fails in one of three ways, each measured by hand on sbx-alpha (V0526) before this probe existed:
- the route REFUSES the advertised value: getRecentWebhookDeliveries offered `failure`, its route accepts `failed` (400
  "Invalid status: failure");
- the route IGNORES it and answers everything: getInviteCodes offered `revoked` (revoking a code deletes it, so no code is
  ever revoked) and the route answered 100 rows, every one `active`;
- the value matches NOTHING though the data carries it: getMyPaymentAuthorizations offered `SETTLED`, the column holds `settled`
  and the route compared exactly.
Each read-only tool with an optional enum filter (by NAME: a status, a severity, an actor type, ...; a mode such as a
candle timeframe is not one) is asked once unfiltered (the control) and once per advertised value ("all" excepted).
Findings: a value refused for being invalid; rows whose field holds another value; a value the control's rows carry that
returns no rows. A busy registry (-32003) or an empty, unreadable control measures nothing. Read only. Rows `enum: <tool>`;
they keep counts and value names, never data.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from agentvault_registry.api_tests.contracts.pagination_partition import rows_of
from agentvault_registry.api_tests.contracts.type_confusion import GOOD, LEFT_OUT, NEVER_SET, _type

PREFIX = "enum: "
FILTER_NAMES = frozenset({"status", "status_filter", "ticket_status", "severity", "actor_type", "kind", "type", "category",
                          "event_type", "level"})
NO_FILTER = frozenset({"all", "any", "*"})
_REFUSED_VALUE = re.compile(r"invalid|unknown|must be one of|not a valid|not one of|unsupported", re.I)

Target = Tuple[str, str, Dict[str, Any], str, List[str]]   # (tool, tier, base args, filter param, advertised values)


def field_for(param: str) -> str:
    """The row field a filter argument selects on (status_filter / ticket_status -> status)."""
    if param in ("status_filter", "ticket_status"):
        return "status"
    return param


def targets(public_schemas: Iterable[dict], admin_schemas: Iterable[dict], tier2: Iterable[str],
            annotate: Callable[[str], Dict[str, bool]]) -> List[Target]:
    t2 = set(tier2)
    out: List[Target] = []
    seen = set()
    for surface, schemas in (("public", public_schemas), ("admin", admin_schemas)):
        for t in schemas:
            name = (t or {}).get("name") or ""
            if not name or name in seen or name in LEFT_OUT:
                continue
            seen.add(name)
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
            tier = "admin" if surface == "admin" else ("2" if name in t2 else "1")
            for p, v in sorted(props.items()):
                if (p in FILTER_NAMES and p not in required and isinstance(v, dict) and v.get("enum")
                        and _type(v) == "string"):
                    values = [str(x) for x in v["enum"] if str(x).lower() not in NO_FILTER]
                    if values:
                        out.append((name, tier, base, p, values))
    return out


def default_targets() -> List[Target]:
    from agentvault_registry.mcp import server as S
    from agentvault_registry.mcp import server_admin as SA
    from agentvault_registry.mcp.tool_metadata import derive_annotations
    return targets(S.ALL_TOOL_SCHEMAS, SA.ADMIN_TOOL_SCHEMAS, S.TIER2_TOOLS, derive_annotations)


def read(parsed: Any) -> Tuple[str, Optional[List[Dict[str, Any]]], str]:
    """(kind, rows, text): kind is `rows`, `refused`, `unavailable` (-32003: the registry could not check the caller) or
    `no_answer`; text is the refusal's own words (for telling a refused VALUE from any other refusal)."""
    if not isinstance(parsed, dict) or not parsed:
        return "no_answer", None, ""
    err = parsed.get("error")
    if isinstance(err, dict):
        if err.get("code") == -32003:
            return "unavailable", None, ""
        return "refused", None, str(err.get("message") or "")
    res = parsed.get("result")
    if not isinstance(res, dict):
        return "no_answer", None, ""
    content = res.get("content") or []
    text = content[0].get("text", "") if content and isinstance(content[0], dict) else ""
    data = res.get("structuredContent")
    if data is None:
        try:
            data = json.loads(text)
        except Exception:  # noqa: BLE001
            data = None
    if res.get("isError") or (isinstance(data, dict) and (data.get("error") or data.get("upstream_error"))):
        return "refused", None, text or json.dumps(data, default=str)[:300]
    rows = rows_of(data)
    return ("rows", rows, "") if rows is not None else ("no_answer", None, "")


def verdict(param: str, control: Tuple[str, Optional[List[dict]], str],
            asked: Dict[str, Tuple[str, Optional[List[dict]], str]]) -> Tuple[Optional[bool], Optional[str], Dict[str, Any]]:
    field = field_for(param)
    c_kind, c_rows, _ = control
    carried = {str(r.get(field)).lower() for r in (c_rows or []) if isinstance(r, dict) and r.get(field) is not None}
    ev: Dict[str, Any] = {"control": f"{len(c_rows)} rows" if c_rows is not None else c_kind}
    refused, dropped, unmatched = [], [], []
    for v, (kind, rows, text) in asked.items():
        ev[v] = f"{len(rows)} rows" if rows is not None else kind
        if kind == "refused" and (v in text or _REFUSED_VALUE.search(text or "")):
            refused.append(v)
        elif kind == "rows":
            others = {str(r.get(field)).lower() for r in rows if isinstance(r, dict) and r.get(field) is not None} - {v.lower()}
            if others:
                dropped.append(f"{v} (rows hold {', '.join(sorted(others)[:3])})")
            elif not rows and v.lower() in carried:
                unmatched.append(v)
    bad = ([f"refused its own advertised value {', '.join(refused)}"] if refused else []) + \
          ([f"answered other values for {'; '.join(dropped)}"] if dropped else []) + \
          ([f"matched nothing for {', '.join(unmatched)} though the unfiltered rows hold it"] if unmatched else [])
    if bad:
        return False, (f"BUG-FIND: enum: the filter `{param}` does not speak its route's vocabulary: " + "; ".join(bad) +
                       ": an advertised value must be one the route applies"), ev
    if not any(kind == "rows" for kind, _r, _t in asked.values()) and c_kind != "rows":
        return None, "NOT MEASURED: neither the unfiltered list nor any filtered call came back", ev
    return True, None, ev


async def run_enums(raw: Optional[Callable], bag: Any, outcomes: Dict[str, dict], make_outcome: Callable,
                    todo: Optional[List[Target]] = None) -> None:
    """One `enum: <tool>` row per target (read only), targets a few at a time (probe_pool)."""
    from agentvault_registry.api_tests.contracts import probe_pool

    async def one(target: Target) -> None:
        tool, tier, base, param, values = target
        t0 = time.time()
        name = PREFIX + tool.replace("theprotocol_", "")
        if raw is None:
            outcomes[name] = make_outcome(name, "enum", False, "0", 0, None, {}, expect_status="any",
                                          skip_reason="NOT MEASURED: the runner injected no raw JSON-RPC transport")
            return
        args0 = dict(base)
        if tier == "2":
            if not getattr(bag, "sentinel_jwt", None):
                outcomes[name] = make_outcome(name, "enum", False, "0", 0, None, {}, expect_status="any",
                                              skip_reason="NOT MEASURED: no sentinel agent token")
                return
            args0["agent_jwt"] = bag.sentinel_jwt
        path = "/mcp/admin/rpc" if tier == "admin" else "/mcp/rpc"
        jwt = getattr(bag, "developer_jwt", "") or ""

        async def ask(args: Dict[str, Any]):
            body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}})
            _code, parsed, _x = await raw(body, path=path, jwt=jwt, timeout=30)
            return read(parsed)

        control = await ask(dict(args0))
        asked = {v: await ask({**args0, param: v}) for v in values}
        healthy, sentence, ev = verdict(param, control, asked)
        outcomes[name] = make_outcome(name, "enum", bool(healthy), "0", int((time.time() - t0) * 1000),
                                      sentence if healthy is False else None, {}, expect_status="any",
                                      skip_reason=sentence if healthy is None else None)
        outcomes[name]["result_excerpt"] = ev
    await probe_pool.each(todo if todo is not None else default_targets(), one)
