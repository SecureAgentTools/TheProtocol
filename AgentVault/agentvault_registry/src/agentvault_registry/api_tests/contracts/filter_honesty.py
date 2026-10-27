"""§MCPTEST30 (2026-10-01) — a list tool's filter is applied, never dropped.

CLAUDE.md §DIRFEED: a server that ignores a query parameter answers 200 with the WHOLE list, and nothing in the answer
says the filter was dropped. An MCP wrapper can drop it the same way: a tool that declares `agent_did` in its schema and
never forwards it answers exactly like a correct one on a quiet frame. Every read-only tool with an optional filter
argument (its NAME says filter: a status, a type, an owner DID, a listing, a search query) is asked once WITHOUT the
filter (the control: it must return rows, or the filter cannot be judged) and once per filter with a random nonce that
matches nothing. Right: no rows, or a refusal of the unknown value. The finding: rows come back. Measured by hand on
sbx-alpha (V0526) before the probe existed: ten tools, fourteen filters, every one applied (three controls empty).
Read only. Rows `filter: <tool>`; they keep counts, never a value.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from agentvault_registry.api_tests.contracts.pagination_partition import rows_of
from agentvault_registry.api_tests.contracts.type_confusion import GOOD, LEFT_OUT, NEVER_SET, _type

PREFIX = "filter: "
# argument names that filter a list by equality or containment (a selection, a sort or a credential is not one)
FILTER_NAMES = frozenset({
    "q", "query", "search", "keyword", "keywords", "name", "tag", "tags", "capability", "capabilities", "category",
    "label", "term", "prefix", "contains", "status", "status_filter", "dispute_status", "state", "event_type", "type",
    "kind", "agent_did", "defendant_did", "complainant_did", "owner_did", "sender_did", "receiver_did", "provider_did",
    "client_did", "circuit_id", "listing", "symbol", "org_id", "organization_id", "currency", "role"})

Target = Tuple[str, str, Dict[str, Any], List[str]]   # (tool, tier: '1' | '2' | 'admin', base args, filter args)


def nonce_for(param: str) -> str:
    """A value no row can carry, in the shape of the argument (a DID-shaped one for a DID filter)."""
    u = uuid.uuid4()
    return f"did:theprotocol:{u}" if param.endswith("_did") else f"zz-mcp-filter-{u.hex[:12]}"


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
            filters = sorted(p for p, v in props.items() if p in FILTER_NAMES and p not in required and isinstance(v, dict)
                             and _type(v) == "string" and not v.get("enum"))
            if not filters:
                continue
            base = {p: GOOD[_type(v)] for p, v in props.items()
                    if p in required and p not in NEVER_SET and _type(v) in GOOD}
            tier = "admin" if surface == "admin" else ("2" if name in t2 else "1")
            out.append((name, tier, base, filters))
    return out


def default_targets() -> List[Target]:
    from agentvault_registry.mcp import server as S
    from agentvault_registry.mcp import server_admin as SA
    from agentvault_registry.mcp.tool_metadata import derive_annotations
    return targets(S.ALL_TOOL_SCHEMAS, SA.ADMIN_TOOL_SCHEMAS, S.TIER2_TOOLS, derive_annotations)


def read(parsed: Any) -> Tuple[str, Optional[int]]:
    """(kind, rows): `rows` with the row count, `refused` (a JSON-RPC error or a tool error), `no_answer`."""
    if not isinstance(parsed, dict) or not parsed:
        return "no_answer", None
    if isinstance(parsed.get("error"), dict):
        return "refused", None
    res = parsed.get("result")
    if not isinstance(res, dict):
        return "no_answer", None
    if res.get("isError"):
        return "refused", None
    data = res.get("structuredContent")
    if data is None:
        content = res.get("content") or []
        try:
            data = json.loads(content[0].get("text", "")) if content and isinstance(content[0], dict) else None
        except Exception:  # noqa: BLE001
            data = None
    if isinstance(data, dict) and data.get("error"):
        return "refused", None
    rows = rows_of(data)
    return ("rows", len(rows)) if rows is not None else ("no_answer", None)


def verdict(control: Tuple[str, Optional[int]], asked: Dict[str, Tuple[str, Optional[int]]]
            ) -> Tuple[Optional[bool], Optional[str], Dict[str, Any]]:
    ev: Dict[str, Any] = {"control": f"{control[0]} {control[1]}" if control[1] is not None else control[0]}
    ev.update({p: (f"{k} {n}" if n is not None else k) for p, (k, n) in asked.items()})
    if control[0] != "rows" or not control[1]:
        return None, "NOT MEASURED: the unfiltered list is empty or unreadable, so no filter can be judged", ev
    dropped = sorted(p for p, (k, n) in asked.items() if k == "rows" and n)
    if dropped:
        return False, (f"BUG-FIND: filter: a value that matches nothing still returned rows for {', '.join(dropped)}: the "
                       "filter was dropped (by the tool or its route), so the caller got the whole list"), ev
    if not any(k in ("rows", "refused") for k, _n in asked.values()):
        return None, "NOT MEASURED: no filtered call came back", ev
    return True, None, ev


async def run_filters(raw: Optional[Callable], bag: Any, outcomes: Dict[str, dict], make_outcome: Callable,
                      todo: Optional[List[Target]] = None) -> None:
    """One `filter: <tool>` row per target (read only), targets a few at a time (probe_pool)."""
    from agentvault_registry.api_tests.contracts import probe_pool

    async def one(target: Target) -> None:
        tool, tier, base, filters = target
        t0 = time.time()
        name = PREFIX + tool.replace("theprotocol_", "")
        if raw is None:
            outcomes[name] = make_outcome(name, "filter", False, "0", 0, None, {}, expect_status="any",
                                          skip_reason="NOT MEASURED: the runner injected no raw JSON-RPC transport")
            return
        args0 = dict(base)
        if tier == "2":
            if not getattr(bag, "sentinel_jwt", None):
                outcomes[name] = make_outcome(name, "filter", False, "0", 0, None, {}, expect_status="any",
                                              skip_reason="NOT MEASURED: no sentinel agent token")
                return
            args0["agent_jwt"] = bag.sentinel_jwt
        path = "/mcp/admin/rpc" if tier == "admin" else "/mcp/rpc"
        jwt = getattr(bag, "developer_jwt", "") or ""

        async def ask(args: Dict[str, Any]) -> Tuple[str, Optional[int]]:
            body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}})
            _code, parsed, _x = await raw(body, path=path, jwt=jwt, timeout=30)
            return read(parsed)

        control = await ask(dict(args0))
        asked = {p: await ask({**args0, p: nonce_for(p)}) for p in filters}
        healthy, sentence, ev = verdict(control, asked)
        outcomes[name] = make_outcome(name, "filter", bool(healthy), "0", int((time.time() - t0) * 1000),
                                      sentence if healthy is False else None, {}, expect_status="any",
                                      skip_reason=sentence if healthy is None else None)
        outcomes[name]["result_excerpt"] = ev
    await probe_pool.each(todo if todo is not None else default_targets(), one)
