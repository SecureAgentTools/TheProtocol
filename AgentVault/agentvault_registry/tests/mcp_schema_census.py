"""§MCPTEST30 (V0548) — does each MCP tool's inputSchema state what its route enforces? (helper, not a test file)

Run in a fresh process (the gate does this): it imports tests/mcp_request_survey.py, which replaces httpx's send with a
recorder, calls every tool with every argument its schema declares, and reads the route each request reaches in the
registry's own OpenAPI. For each argument the tool sends under the same name, the constraints the route states (enum,
pattern, minLength, maxLength, minimum, maximum, exclusiveMinimum, exclusiveMaximum, format, an array's item type) are
compared with the tool's advertised schema, which is what an MCP caller reads. Measured on V0546: 168 arguments of 85
tools carried a constraint their route enforces and their schema did not state (placeAgoraOrder's side buy|sell,
bulkSuspendAgents' reason of at least 10 characters, pauseAgentPayouts' duration_days up to 365): a caller that followed
the schema met a 422 the schema never warned about.

    python mcp_schema_census.py [--json OUT] [--write PATH]

--write renders src/agentvault_registry/mcp/route_constraints.py's table from what the routes state (mcp/route_constraints
applies it to the advertised schemas at import). Classes: MISSING (the route states it, the schema does not) · CONFLICT
(both state it, differently: a schema that names a wrong bound is worse than none) · STALE (the table states something the
route no longer does). A string constraint is carried only to a string argument and a numeric one only to a number:
a constraint on another type would describe a value the tool does not take. The rules live in mcp_schema_rules.py (a test
reads them there: importing this module patches httpx in the importing process).
"""
from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, Dict, Tuple

_argv = list(sys.argv)
sys.argv = [sys.argv[0]]
import mcp_request_survey as S  # noqa: E402  (patches httpx, imports the app with every optional router)

sys.argv = _argv

from agentvault_registry.main import app  # noqa: E402
from agentvault_registry.mcp import route_constraints as RC  # noqa: E402
from mcp_schema_rules import compatible, kind, looser, route_constraints as _rules_constraints  # noqa: E402

SPEC = app.openapi()
COMPONENTS = (SPEC.get("components") or {}).get("schemas") or {}
def deref(sc: Any, depth: int = 0) -> Dict[str, Any]:
    if not isinstance(sc, dict) or depth > 8:
        return {}
    if "$ref" in sc:
        return deref(COMPONENTS.get(sc["$ref"].rsplit("/", 1)[-1], {}), depth + 1)
    for k in ("anyOf", "oneOf", "allOf"):
        if k in sc:
            opts = [deref(x, depth + 1) for x in sc[k]]
            opts = [o for o in opts if o and o.get("type") != "null"]
            if len(opts) == 1:
                merged = dict(opts[0])
                merged.update({kk: v for kk, v in sc.items() if kk != k})
                return merged
            return {}
    return sc


def _operation(method: str, path: str):
    route, _child, miss = S.find_route(method, path)
    if miss or route is None or getattr(route, "dependant", None) is None:
        return None
    tmpl = getattr(route, "path_format", None) or getattr(route, "path", None)
    return (SPEC.get("paths", {}).get(tmpl) or {}).get(method.lower())


def _fields(op: Dict[str, Any]) -> Dict[str, Tuple[str, Dict[str, Any]]]:
    out: Dict[str, Tuple[str, Dict[str, Any]]] = {}
    for prm in op.get("parameters") or []:
        if prm.get("in") == "query":
            out[prm["name"]] = _rules_constraints(prm.get("schema") or {}, deref)
    body = (((op.get("requestBody") or {}).get("content") or {}).get("application/json") or {}).get("schema")
    if body:
        for name, fsc in (deref(body).get("properties") or {}).items():
            out[name] = _rules_constraints(fsc, deref)
    return out


async def census() -> Dict[str, Any]:
    from agentvault_registry.mcp.auth_bridge import MCPAuthContext
    stated: Dict[str, Dict[str, Dict[str, Any]]] = {}       # what the routes state, for arguments the tools send
    native: Dict[str, Dict[str, Dict[str, Any]]] = {}       # the tool schema's own keys (the table's additions removed)
    from agentvault_registry.mcp import tools_admin
    self_host = S.urlsplit(tools_admin.REGISTRY_SELF_URL).netloc
    agent = MCPAuthContext(auth_type="agent", agent_did="did:theprotocol:phase6-self", agent_id=1, raw_token=S.AGENT_TOKEN)
    tools = 0
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
            tools += 1
            props = (sc.get("inputSchema") or {}).get("properties") or {}
            S.CAPTURED.clear()
            try:
                a = S.args_for(sc, True)
                if name in noauth:
                    await asyncio.wait_for(fn(**a), 8)
                elif name in tier2:
                    await asyncio.wait_for(fn(agent, **a), 8)
                else:
                    await asyncio.wait_for(fn(auth, **a), 8)
            except Exception:  # noqa: BLE001 — a census records what was sent, it does not stop
                pass
            added = RC.APPLIED.get(name, {})
            for rq in list(S.CAPTURED):
                netloc = rq.url.netloc.decode() if isinstance(rq.url.netloc, bytes) else rq.url.netloc
                if netloc != self_host:
                    continue
                op = _operation(rq.method, rq.url.path)
                if not op:
                    continue
                for field, (route_t, cons) in _fields(op).items():
                    prop = props.get(field)
                    if not cons or not isinstance(prop, dict) or not compatible(route_t, kind(prop)):
                        continue
                    stated.setdefault(name, {}).setdefault(field, {}).update(cons)
                    own = {k: v for k, v in prop.items() if k not in added.get(field, [])}
                    if "items" in own and "items" in added.get(field, []):
                        own.pop("items")
                    native.setdefault(name, {})[field] = own
    missing: Dict[str, Dict[str, Dict[str, Any]]] = {}
    conflict: Dict[str, Dict[str, Dict[str, Any]]] = {}
    table: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for name, fields in stated.items():
        for field, cons in fields.items():
            own = native.get(name, {}).get(field, {})
            for k, v in cons.items():
                if k == "items":
                    if not (isinstance(own.get("items"), dict) and own["items"].get("type")):
                        table.setdefault(name, {}).setdefault(field, {})[k] = v
                    continue
                if k not in own:
                    table.setdefault(name, {}).setdefault(field, {})[k] = v
                elif looser(k, own[k], v):
                    conflict.setdefault(name, {}).setdefault(field, {})[k] = {"route": v, "schema": own[k]}
    for name, fields in table.items():
        for field, cons in fields.items():
            got = RC.ROUTE_CONSTRAINTS.get(name, {}).get(field, {})
            gone = {k: v for k, v in cons.items() if got.get(k) != v}
            if gone:
                missing.setdefault(name, {})[field] = gone
    stale: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for name, fields in RC.ROUTE_CONSTRAINTS.items():
        for field, cons in fields.items():
            want = table.get(name, {}).get(field, {})
            extra = {k: v for k, v in cons.items() if want.get(k) != v}
            if extra:
                stale.setdefault(name, {})[field] = extra
    return {"tools": tools, "stated_fields": sum(len(v) for v in stated.values()), "table": table,
            "missing": missing, "conflict": conflict, "stale": stale}


def render(table: Dict[str, Dict[str, Dict[str, Any]]]) -> str:
    lines = ["ROUTE_CONSTRAINTS: Dict[str, Dict[str, Dict[str, Any]]] = {"]
    for name in sorted(table):
        lines.append(f"    {name!r}: {{")
        for field in sorted(table[name]):
            lines.append(f"        {field!r}: {json.dumps(table[name][field], sort_keys=True)},")
        lines.append("    },")
    lines.append("}")
    return "\n".join(lines).replace(": true", ": True").replace(": false", ": False").replace(": null", ": None")


if __name__ == "__main__":
    result = asyncio.run(census())
    if "--json" in sys.argv:
        with open(sys.argv[sys.argv.index("--json") + 1], "w") as fh:
            json.dump(result, fh, indent=1, sort_keys=True)
    if "--write" in sys.argv:
        path = sys.argv[sys.argv.index("--write") + 1]
        src = open(path).read()
        start = src.index("ROUTE_CONSTRAINTS: Dict[str, Dict[str, Dict[str, Any]]] = {")
        end = src.index("\n}\n", start) + 2
        with open(path, "w") as fh:
            fh.write(src[:start] + render(result["table"]) + src[end:])
    print(f"tools {result['tools']} · arguments whose route states a constraint {result['stated_fields']} · "
          f"in the table {sum(len(v) for v in result['table'].values())} · missing "
          f"{sum(len(v) for v in result['missing'].values())} · conflict {sum(len(v) for v in result['conflict'].values())} · "
          f"stale {sum(len(v) for v in result['stale'].values())}")
    for cls in ("missing", "conflict", "stale"):
        for name, fields in sorted(result[cls].items()):
            print(f"  {cls.upper()} {name}: {json.dumps(fields, sort_keys=True)[:300]}")
