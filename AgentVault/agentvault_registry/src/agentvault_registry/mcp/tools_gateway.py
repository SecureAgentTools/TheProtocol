"""Gateway meta-tools (L1 of the 2026-07-14 MCP tool-loading work).

With ~700 tools across the two servers, a client that loads every schema burns
~30k tokens before its first call (STRATEGY_2026-07-14_MCP_TOOL_LOADING.md).
Gateway mode (?mode=gateway) lists only the core tools plus these four
meta-tools; everything else is discovered on demand:

    listToolsets  -> bucket names + counts
    searchTools   -> ranked name/category/description matches for a query
    describeTools -> full input schemas for chosen tools (as DATA, not context)
    invokeTool    -> execute any tool by name (unwrapped by the server BEFORE
                     dispatch, so the inner tool keeps its own tier auth and
                     its own audit row — this module never bypasses either)

The implementations are pure functions over a schema list so server.py (public)
and server_admin.py (admin) share them. Categories come from tool_categories
and are LISTING metadata only — never an authorization boundary.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional, Set

from .tool_categories import (
    ADMIN_BUCKETS,
    PUBLIC_BUCKETS,
    PUBLIC_OVERLAY_BUCKETS,
    bare_name,
    get_category,
)

INVOKE_TOOL = "theprotocol_invokeTool"
SEARCH_TOOL = "theprotocol_searchTools"
DESCRIBE_TOOL = "theprotocol_describeTools"
LIST_TOOLSETS_TOOL = "theprotocol_listToolsets"
ENABLE_TOOLSET_TOOL = "theprotocol_enableToolset"
DISABLE_TOOLSET_TOOL = "theprotocol_disableToolset"
GATEWAY_TOOL_NAMES = frozenset({
    INVOKE_TOOL, SEARCH_TOOL, DESCRIBE_TOOL, LIST_TOOLSETS_TOOL,
    ENABLE_TOOLSET_TOOL, DISABLE_TOOLSET_TOOL,
})

GATEWAY_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "name": LIST_TOOLSETS_TOOL,
        "description": (
            "List the tool buckets (toolsets) this server offers, with tool counts and "
            "descriptions. Start here in gateway mode, then searchTools within a bucket."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": SEARCH_TOOL,
        "description": (
            "Search the full tool catalog by keywords (matches tool names, categories and "
            "descriptions). Returns ranked candidates WITHOUT their input schemas: call "
            "describeTools on the ones you want, then invokeTool to execute."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keywords, e.g. 'transfer' or 'guild bid'"},
                "toolsets": {
                    "type": "string",
                    "description": "Optional comma-separated bucket filter (see listToolsets)",
                },
                "limit": {"type": "integer", "description": "Max results (default 10, max 25)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": DESCRIBE_TOOL,
        "description": (
            "Return the full definitions (description + input schema + category) for up to "
            "10 named tools, so you can call them via invokeTool."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tool names from searchTools (with or without the theprotocol_ prefix)",
                }
            },
            "required": ["names"],
        },
    },
    {
        "name": INVOKE_TOOL,
        "description": (
            "Execute any tool on this server by name with a JSON arguments object. "
            "Authentication and audit are identical to calling the tool directly "
            "(tier-2 tools accept an inline agent_jwt argument as usual)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Target tool name (from searchTools)"},
                "arguments": {
                    "type": "object",
                    "description": "Arguments object for the target tool (see describeTools)",
                },
            },
            "required": ["name"],
        },
    },
    # L2 — dynamic toolsets (2026-07-14 reference-grade pass). Per-session
    # bucket selection persisted server-side (keyed by your credential), so
    # subsequent tools/list calls reflect it. Listing preference ONLY — never
    # an auth boundary; re-run tools/list after changing.
    {
        "name": ENABLE_TOOLSET_TOOL,
        "description": (
            "Enable one or more toolsets (buckets) for THIS session: subsequent tools/list "
            "responses include their tools. Persisted against your credential for 24h. "
            "Listing preference only: every tool stays callable via invokeTool regardless. "
            "Re-fetch tools/list after calling."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "toolsets": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Bucket names to enable (see listToolsets)",
                }
            },
            "required": ["toolsets"],
        },
    },
    {
        "name": DISABLE_TOOLSET_TOOL,
        "description": (
            "Disable toolsets previously enabled for this session (or pass an empty array "
            "to clear the whole session selection and return to the default listing). "
            "Re-fetch tools/list after calling."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "toolsets": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Bucket names to disable; [] clears the session selection",
                }
            },
            "required": ["toolsets"],
        },
    },
]

# ---------------------------------------------------------------------------
# L2 session-toolset storage (Redis-shared across workers; 24h TTL)
# ---------------------------------------------------------------------------

_SESSION_TTL_S = 24 * 3600
_local_sessions: Dict[str, Set[str]] = {}  # no-Redis dev fallback


async def _redis():
    try:
        from agentvault_registry.background_tasks.leader import get_redis
        return await get_redis()
    except Exception:
        return None


def _session_key(ctx: str, is_admin: bool) -> str:
    return f"mcp:toolsel:{'admin' if is_admin else 'public'}:{ctx}"


async def get_session_selection(ctx: str, *, is_admin: bool) -> Optional[Set[str]]:
    """The session's enabled buckets (plus the implicit 'core' — same invariant
    as parse_toolsets: the daily drivers stay reachable whenever any filtering
    is active), or None when no selection is stored."""
    r = await _redis()
    if r is not None:
        raw = await r.get(_session_key(ctx, is_admin))
        if not raw:
            return None
        names = {n for n in (raw.decode() if isinstance(raw, bytes) else raw).split(",") if n}
        return (names | {"core"}) if names else None
    stored = _local_sessions.get(_session_key(ctx, is_admin))
    return (stored | {"core"}) if stored else None


async def _put_session_selection(ctx: str, sel: Optional[Set[str]], *, is_admin: bool) -> None:
    key = _session_key(ctx, is_admin)
    r = await _redis()
    if r is not None:
        if sel:
            await r.set(key, ",".join(sorted(sel)), ex=_SESSION_TTL_S)
        else:
            await r.delete(key)
    else:
        if sel:
            _local_sessions[key] = sel
        else:
            _local_sessions.pop(key, None)


async def modify_session_toolsets(
    ctx: str, names: Any, *, is_admin: bool, enable: bool
) -> Dict[str, Any]:
    """enableToolset / disableToolset implementation (shared)."""
    buckets = ADMIN_BUCKETS if is_admin else PUBLIC_BUCKETS
    known = set(buckets) if is_admin else (set(buckets) | set(PUBLIC_OVERLAY_BUCKETS))
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        return {"error": "toolsets must be an array of bucket-name strings"}
    unknown = [n for n in names if n not in known]
    if unknown:
        return {"error": f"Unknown toolsets {unknown}; valid: {sorted(known)}"}
    current = await get_session_selection(ctx, is_admin=is_admin) or set()
    if enable:
        current |= set(names)
    elif names:
        current -= set(names)
    else:
        current = set()  # disable([]) clears the session
    await _put_session_selection(ctx, current or None, is_admin=is_admin)
    return {
        "enabled_toolsets": sorted(current) if current else [],
        "session_scope": "24h, keyed to your credential",
        "note": "Re-run tools/list to see the updated listing ('core' is always included). "
                "Explicit ?toolsets=/X-MCP-Toolsets on a request overrides the session selection.",
    }

# D6-725 (2026-10-16): both servers advertise `tools.listChanged: true` because enableToolset/disableToolset change the
# caller's listing, yet no notification was ever sent. Where an answer travels as an event stream (POST /mcp or
# /mcp/admin with Accept: text/event-stream, and POST /mcp/sse or /mcp/admin/sse), MCP lets the server send
# notifications that belong to the request before the answer: a successful selection change now carries
# notifications/tools/list_changed there. A plain JSON answer has no room for one; such a client re-runs tools/list.
LIST_CHANGED_NOTIFICATION = {"jsonrpc": "2.0", "method": "notifications/tools/list_changed"}


def changed_the_listing(request_body: Any, response_body: str) -> bool:
    """A tools/call of enableToolset or disableToolset that succeeded (the stored selection was written)."""
    if not isinstance(request_body, dict) or request_body.get("method") != "tools/call":
        return False
    params = request_body.get("params")
    if not isinstance(params, dict) or params.get("name") not in (ENABLE_TOOLSET_TOOL, DISABLE_TOOLSET_TOOL):
        return False
    try:
        result = json.loads(response_body).get("result")
    except (ValueError, AttributeError):
        return False
    return isinstance(result, dict) and result.get("isError") is False


def sse_answer(request_body: Any, response_body: str) -> str:
    """The answer as server-sent events: the list_changed notification first when the call changed the listing."""
    events = f"event: message\ndata: {response_body}\n\n"
    if changed_the_listing(request_body, response_body):
        events = f"event: message\ndata: {json.dumps(LIST_CHANGED_NOTIFICATION)}\n\n" + events
    return events


_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_SPLIT_RE = re.compile(r"[^a-z0-9]+")


def _tokens(text: str) -> List[str]:
    return [t for t in _SPLIT_RE.split(_CAMEL_RE.sub(" ", text).lower()) if t]


def _resolve_wire_name(raw: str, schema_names: Set[str]) -> Optional[str]:
    # §AGORAWORDS (V0419): invokeTool and describeTools accept a renamed tool's old name (mcp/tool_aliases.py).
    from .tool_aliases import resolve_alias
    raw = resolve_alias(raw)
    if raw in schema_names:
        return raw
    prefixed = f"theprotocol_{raw}"
    return prefixed if prefixed in schema_names else None


async def search_tools(
    all_schemas: List[Dict[str, Any]],
    *,
    is_admin: bool,
    query: str,
    toolsets: Optional[str] = None,
    limit: int = 10,
) -> Dict[str, Any]:
    """Rank tools for a keyword query. Name-token hits dominate; description
    hits break ties. Deterministic (score desc, name asc)."""
    from .tool_categories import parse_toolsets  # local import: avoid cycle at module load

    limit = max(1, min(int(limit or 10), 25))
    selected, unknown = parse_toolsets(toolsets, is_admin=is_admin)
    if unknown:
        valid = sorted((ADMIN_BUCKETS if is_admin else PUBLIC_BUCKETS).keys())
        return {"error": f"Unknown toolsets {unknown}; valid: {valid}"}

    q_tokens = _tokens(query)
    if not q_tokens:
        return {"error": "query must contain at least one word"}

    results = []
    for schema in all_schemas:
        name = schema.get("name", "")
        if name in GATEWAY_TOOL_NAMES:
            continue
        category = get_category(name, is_admin=is_admin)
        if selected is not None and category not in selected:
            continue
        name_tokens = set(_tokens(bare_name(name)))
        desc = schema.get("description", "")
        desc_tokens = set(_tokens(desc))
        score = 0
        for qt in q_tokens:
            if qt in name_tokens:
                score += 12
            elif any(qt in nt for nt in name_tokens):
                score += 6
            if qt == category or qt in _tokens(category):
                score += 8
            if qt in desc_tokens:
                score += 2
        if bare_name(name).lower() == "".join(q_tokens):
            score += 100
        if score > 0:
            results.append({
                "name": name,
                "category": category,
                "score": score,
                "description": desc.split(". ")[0][:160],
            })

    results.sort(key=lambda r: (-r["score"], r["name"]))
    return {
        "query": query,
        "total_matches": len(results),
        "results": results[:limit],
        "next_step": f"Call {DESCRIBE_TOOL} with the names you want, then {INVOKE_TOOL}.",
    }


async def describe_tools(
    all_schemas: List[Dict[str, Any]],
    *,
    is_admin: bool,
    names: List[str],
) -> Dict[str, Any]:
    """Full definitions for up to 10 named tools, returned as data."""
    if not isinstance(names, list) or not names:
        return {"error": "names must be a non-empty array of tool names"}
    by_name = {s.get("name", ""): s for s in all_schemas}
    schema_names = set(by_name.keys())
    found, missing = [], []
    for raw in names[:10]:
        wire = _resolve_wire_name(str(raw), schema_names)
        if wire is None:
            missing.append(raw)
            continue
        entry = dict(by_name[wire])
        entry["category"] = get_category(wire, is_admin=is_admin)
        found.append(entry)
    out: Dict[str, Any] = {"tools": found}
    if missing:
        out["not_found"] = missing
    if len(names) > 10:
        out["truncated_to"] = 10
    return out


async def list_toolsets(
    all_schemas: List[Dict[str, Any]],
    *,
    is_admin: bool,
    selected: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """Bucket inventory with live tool counts (counts drift with the catalog)."""
    buckets = ADMIN_BUCKETS if is_admin else PUBLIC_BUCKETS
    counts: Dict[str, int] = {}
    for schema in all_schemas:
        cat = get_category(schema.get("name", ""), is_admin=is_admin)
        counts[cat] = counts.get(cat, 0) + 1
    listing = [
        {
            "name": b,
            "tools": counts.get(b, 0),
            "description": desc,
            **({"enabled": (b in selected)} if selected is not None else {}),
        }
        for b, desc in buckets.items()
    ]
    if not is_admin:
        # §POCKETBRIDGE3: overlay buckets — curated cross-cuts (a tool keeps its
        # primary bucket; an overlay adds a selectable named set).
        all_bare = {schema.get("name", "")[12:] if schema.get("name", "").startswith("theprotocol_")
                    else schema.get("name", "") for schema in all_schemas}
        for oname, (odesc, omembers) in PUBLIC_OVERLAY_BUCKETS.items():
            listing.append({
                "name": oname,
                "tools": len(omembers & all_bare),
                "description": odesc,
                "overlay": True,
                **({"enabled": (oname in selected)} if selected is not None else {}),
            })
    # 'misc' only exists if the category map has drifted behind the catalog —
    # surface it so the gap is visible instead of silently unlistable.
    if counts.get("misc"):
        listing.append({"name": "misc", "tools": counts["misc"],
                        "description": "Uncategorized (the category map has drifted behind the catalog: file a fix)"})
    return {
        "toolsets": listing,
        "usage": "Filter listings with ?toolsets=a,b (or X-MCP-Toolsets header); 'core' is always included.",
    }


def unwrap_invoke(arguments: Dict[str, Any], dispatch: Dict[str, Any]) -> tuple:
    """Rewrite an invokeTool call into (inner_name, inner_arguments).

    Runs BEFORE dispatch so the inner tool's tier auth + audit apply untouched.
    Raises ValueError with a client-facing message on bad input.
    """
    raw = arguments.get("name")
    if not raw or not isinstance(raw, str):
        raise ValueError("invokeTool requires 'name' (string) — find tools via searchTools")
    inner = _resolve_wire_name(raw, set(dispatch.keys()))
    if inner is None:
        raise ValueError(f"invokeTool: unknown tool '{raw}' — find valid names via searchTools")
    if inner == INVOKE_TOOL:
        raise ValueError("invokeTool cannot invoke itself")
    inner_args = arguments.get("arguments") or {}
    if not isinstance(inner_args, dict):
        raise ValueError("invokeTool 'arguments' must be an object")
    return inner, inner_args


async def _invoke_stub(**_kwargs: Any) -> Dict[str, Any]:
    """Defensive: invokeTool is unwrapped before dispatch; reaching this means a
    call path skipped the unwrap step."""
    return {"error": "invokeTool must be called via tools/call (server unwraps it before dispatch)"}
