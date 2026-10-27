"""§MCPSWEEP 2026-09-27 — does each MCP tool's HTTP request pass its own route's validation? (helper, not a test file)

Run in a fresh process (the test does this): it replaces httpx's send with a recorder that answers 200 {}, so nothing
leaves the process, mounts every optional router a frame can serve, and calls each tool the way its dispatcher does,
twice: with only the arguments its inputSchema requires, then with every argument it declares (truthy, type-shaped
dummies). Each captured request to this registry is matched to its route and put through FastAPI's own path, query
and body validation, the step that answers 422 before any handler runs.

    python mcp_request_survey.py all --json OUT

Classes per tool: NO_ROUTE (no route serves the path) · METHOD (the path exists, not with that method) ·
MISSING_ALWAYS (a field the route requires is absent even with every declared argument: the tool can never succeed) ·
MISSING_OPTIONAL (absent when a caller sends only what the schema marks required) · BOUND (a page size the schema
allows and the route refuses: the dummy is the schema's own maximum) · TYPE (a value its route cannot
parse; the dummy may be at fault, so this class is reported, not gated) · PASSTHROUGH (the whole body is an
object the caller supplies, so what the route finds missing is the caller's to send; reported, not gated) ·
RAISED · NO_REQUEST · EXTERNAL · BODY_UNREAD (since V0550: a key the tool sends in an untyped dict body that the
handler never reads, read from the handler's source by tests/mcp_handler_headers.py) · PEER_ROUTE (since V0547: the route authenticates only a federation peer, so no MCP
caller can succeed; since V0549 also a route whose handler refuses a request without a federation licence header
the tool never sends, read by tests/mcp_handler_headers.py; reported, and test_mcp_tool_requests_meet_their_routes.py
holds its census to a list that may only shrink).
The controls run the same validator on hand-built requests and must come out the way they are built to.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from typing import Any, Dict, List, Tuple
from urllib.parse import parse_qsl, urlsplit

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
os.environ.setdefault("API_KEY_SECRET", "dummy")
# every optional router a frame can serve (a settings flag; the ENABLE_SANDBOX_PROVISIONER_TEST routers are retired)
os.environ["OAUTH_TOKEN_EXCHANGE_ENABLED"] = "true"

import httpx  # noqa: E402

CAPTURED: List[httpx.Request] = []


async def _fake_send(self, request, *a, **k):
    await request.aread()
    CAPTURED.append(request)
    return httpx.Response(200, json={}, request=request)


def _fake_send_sync(self, request, *a, **k):
    request.read()
    CAPTURED.append(request)
    return httpx.Response(200, json={}, request=request)


httpx.AsyncClient.send = _fake_send  # type: ignore[assignment]
httpx.Client.send = _fake_send_sync  # type: ignore[assignment]

import inspect  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import fastapi.dependencies.utils as _du  # noqa: E402
from fastapi.dependencies.utils import request_body_to_args, request_params_to_args  # noqa: E402
from starlette.requests import Request  # noqa: E402
from starlette.routing import Match  # noqa: E402

# §DEPS (2026-09-27): FastAPI 0.14x removed get_flat_dependant, gave request_body_to_args an embed_body_fields argument,
# and keeps an included router as ONE lazily resolved entry in app.routes. The survey reads both generations.
_get_flat_dependant = getattr(_du, "get_flat_dependant", None)
_BODY_TAKES_EMBED = "embed_body_fields" in inspect.signature(request_body_to_args).parameters

from agentvault_registry.main import app  # noqa: E402

# §MCPTEST30 (V0549): the headers a handler checks itself (pure ast; the survey's own directory, so the sealed child
# the live tester starts finds it as the CI gate does)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mcp_handler_headers as _HH  # noqa: E402
from agentvault_registry.mcp.auth_bridge import MCPAuthContext  # noqa: E402

UUID0 = "00000000-0000-4000-8000-000000000000"
# the dummy for an object argument; a request whose whole JSON body IS this object came from a PASS-THROUGH tool (the
# caller supplies the body), so what its route finds missing is the caller's to supply, not a defect of the tool
OBJECT_DUMMY = {"phase6": "phase6"}
NUMERIC_WORDS = ("amount", "price", "budget", "stake", "quantity", "fee", "bid")
_BOUND = re.compile(r"\[query -> (limit|depth|page_size|per_page)\] Input should be less than or equal to")
GATEWAY_TOOLS = ("searchTools", "describeTools", "invokeTool", "listToolsets", "enableToolset", "disableToolset")
DISPATCHER_KEYS = ("agent_jwt", "capability_token")  # the public dispatcher pops these before it calls a tool
# §MCPTEST30 (V0538): the two credentials the survey hands a tool, told apart in the request it makes
AGENT_TOKEN, DEV_TOKEN = "phase6-agent-token", "phase6-token"
DEV_AUTH = {"get_current_developer", "get_current_admin_developer"}
AGENT_AUTH = {"get_current_agent"}
# §MCPTEST30 (V0547): a federation PEER's identity (core/federation_auth: mTLS, the internal secret or a federation
# licence), which no MCP caller holds
PEER_AUTH = {"get_federation_identity", "require_peer_registry_identity"}
# §MCPTEST30 (V0549): the same credentials as headers a handler reads and refuses without (a federation licence, the
# internal secret). A tool that never sends one can never succeed; one that takes it as an argument
# (rotateFederationLicenseSelf) sends it and is not in the class. Lower case: request headers are compared that way.
PEER_HEADERS = {"x-federation-license", "x-federation-secret", "x-internal-key"}


# §MCPTEST30 (V0550): the §BAFIN switch dependencies (core/staking_gate.py). A route carrying one answers 403 where its
# registry switched the surface off, and the tester holds such a tool to that refusal there
# (api_tests/contracts/mcp_switches.py, whose map the gate checks against this class). Reported, never gated.
SWITCH_DEPS = {"require_staking_enabled", "require_staking_rewards_enabled"}


def route_switches(dependant: Any) -> List[str]:
    """The switch dependencies in a route's tree (empty for a route no switch turns off)."""
    calls, stack, seen = set(), [dependant], set()
    while stack:
        d = stack.pop()
        if id(d) in seen:
            continue
        seen.add(id(d))
        name = getattr(getattr(d, "call", None), "__name__", "")
        if name:
            calls.add(name)
        stack.extend(getattr(d, "dependencies", None) or [])
    return sorted(calls & SWITCH_DEPS)


def route_peer_auth(dependant: Any) -> List[str]:
    """The federation-peer dependencies in a route's tree (empty for a route a developer or an agent may call)."""
    calls, stack, seen = set(), [dependant], set()
    while stack:
        d = stack.pop()
        if id(d) in seen:
            continue
        seen.add(id(d))
        name = getattr(getattr(d, "call", None), "__name__", "")
        if name:
            calls.add(name)
        stack.extend(getattr(d, "dependencies", None) or [])
    return sorted(calls & PEER_AUTH)


def route_admin_gate(dependant: Any) -> bool:
    """Whether a route admits only an admin: an admin-flag gate (require_admin_flag's closure) or the admin dependency."""
    stack, seen = [dependant], set()
    while stack:
        d = stack.pop()
        if id(d) in seen:
            continue
        seen.add(id(d))
        call = getattr(d, "call", None)
        qual = getattr(call, "__qualname__", "") or ""
        if qual.startswith("require_admin_flag.") or getattr(call, "__name__", "") == "get_current_admin_developer":
            return True
        stack.extend(getattr(d, "dependencies", None) or [])
    return False


def route_principal(dependant: Any) -> Tuple[str, List[str]]:
    """Whom a route's dependency tree authenticates: 'developer', 'agent', 'either' or 'other' (a route that takes
    neither, or its own scheme), with the auth dependencies it found. A permission or admin-flag gate is a closure
    over one of the two, so the walk reaches the one beneath it."""
    calls, stack, seen = set(), [dependant], set()
    while stack:
        d = stack.pop()
        if id(d) in seen:
            continue
        seen.add(id(d))
        name = getattr(getattr(d, "call", None), "__name__", "")
        if name:
            calls.add(name)
        stack.extend(getattr(d, "dependencies", None) or [])
    dev, agent = bool(calls & DEV_AUTH), bool(calls & AGENT_AUTH)
    kind = "either" if dev and agent else "developer" if dev else "agent" if agent else "other"
    return kind, sorted(calls & (DEV_AUTH | AGENT_AUTH))


def sent_credential(headers: Dict[str, str]) -> str:
    tok = headers.get("authorization") or headers.get("Authorization") or ""
    if not tok:
        return "none"
    if tok.endswith(AGENT_TOKEN):
        return "agent"
    return "developer" if tok.endswith(DEV_TOKEN) else "other"


def dummy(name: str, spec: Dict[str, Any]) -> Any:
    value = _dummy(name, spec)
    if isinstance(value, str) and spec.get("minLength") and len(value) < spec["minLength"]:
        value = (value + "-" + "x" * spec["minLength"])[: max(spec["minLength"], len(value))]
    if isinstance(value, str) and spec.get("maxLength") and len(value) > spec["maxLength"]:
        value = value[: spec["maxLength"]]
    return value


def _dummy(name: str, spec: Dict[str, Any]) -> Any:
    if spec.get("enum"):
        return spec["enum"][0]
    t = spec.get("type")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), "string")
    n = name.lower()
    # truthy on purpose: a tool that forwards a value only `if value:` must still be seen forwarding it
    if t == "integer":
        return spec["maximum"] if "maximum" in spec else 999999
    if t == "number":
        return spec.get("minimum", 1)
    if t == "boolean":
        return True
    if t == "array":
        return ["phase6"]
    if t == "object":
        return dict(OBJECT_DUMMY)
    if "did" in n:
        return "did:theprotocol:phase6-no-such"
    if "email" in n:
        return "phase6@phase6.invalid"
    if "uuid" in n or n in ("flag_id", "route_id", "task_id", "deployment_id"):
        return UUID0
    if n.endswith("_id") or n == "id":
        return "999999"
    if "url" in n:
        return "https://phase6.invalid/"
    if n.endswith("_b64") or "base64" in n:
        return "cGhhc2U2"
    if any(w in n for w in NUMERIC_WORDS):
        return "1"  # a number the schema types as a string
    return "phase6"


def args_for(schema: Dict[str, Any], every: bool) -> Dict[str, Any]:
    inp = schema.get("inputSchema") or {}
    props = inp.get("properties") or {}
    req = set(inp.get("required") or [])
    return {k: dummy(k, v or {}) for k, v in props.items() if (every or k in req) and k not in DISPATCHER_KEYS}


def served_routes() -> List[Any]:
    """Every route the app serves, in serving order, as the object that carries its full path and its dependant."""
    try:
        from fastapi.routing import iter_route_contexts
    except ImportError:  # FastAPI before the lazy include: app.routes is already flat
        return list(app.routes)
    return [rc._effective_route for rc in iter_route_contexts(app.routes)]


def _match(r: Any, method: str, path: str):
    if hasattr(r, "matches"):
        return r.matches({"type": "http", "path": path, "method": method, "root_path": ""})
    rx = getattr(r, "path_regex", None)  # an included route's served context: its full path regex and converters
    mt = rx.match(path) if rx is not None else None
    if mt is None:
        return Match.NONE, {}
    child = {"path_params": {k: r.param_convertors[k].convert(v) for k, v in mt.groupdict().items()}}
    return (Match.PARTIAL if r.methods and method not in r.methods else Match.FULL), child


def find_route(method: str, path: str):
    partial = None
    for r in served_routes():
        m, child = _match(r, method, path)
        if m == Match.FULL:
            return r, child, None
        if m == Match.PARTIAL and partial is None:
            partial = r
    return None, None, ("METHOD" if partial is not None else "NO_ROUTE")


def flat_dependant(dependant: Any) -> Any:
    """The route's parameters from its whole dependency tree, each sub-dependency once (get_flat_dependant's skip_repeats)."""
    if _get_flat_dependant is not None:
        return _get_flat_dependant(dependant, skip_repeats=True)
    flat = SimpleNamespace(path_params=[], query_params=[], header_params=[], cookie_params=[], body_params=[])
    cache_key = getattr(_du, "_get_cache_key", None)
    scopes_cache: Dict[Any, Any] = {}
    seen: List[Any] = []
    stack = [dependant]
    while stack:
        d = stack.pop()
        key = cache_key(dependant=d, uses_scopes_cache=scopes_cache) if cache_key else (d.call, id(d))
        if key in seen and d is not dependant:
            continue
        seen.append(key)
        for kind in ("path_params", "query_params", "header_params", "cookie_params", "body_params"):
            getattr(flat, kind).extend(getattr(d, kind))
        stack.extend(reversed(d.dependencies))
    return flat


def _body_declared(flat: Any, route: Any) -> Tuple[set, bool]:
    """(the JSON keys a route's body reads, opaque?): opaque when the body is a dict/Any/list or a model that allows extra
    keys, so what it ignores cannot be told."""
    import typing as _t
    from pydantic import BaseModel as _BM
    params = list(flat.body_params)
    if bool(getattr(route, "_embed_body_fields", False)) or len(params) > 1:
        return {getattr(p, "alias", None) or p.name for p in params}, False
    fi = getattr(params[0], "field_info", None)
    ann = getattr(fi, "annotation", None) or getattr(params[0], "type_", None)
    inner = [a for a in (_t.get_args(ann) or ()) if a is not type(None)]
    if len(inner) == 1:
        ann = inner[0]
    if isinstance(ann, type) and issubclass(ann, _BM):
        if (getattr(ann, "model_config", {}) or {}).get("extra") == "allow":
            return set(), True
        keys = set()
        for name, f in ann.model_fields.items():
            keys.add(name)
            if f.alias:
                keys.add(f.alias)
        return keys, False
    return set(), True


async def validate(method: str, url: str, headers: Dict[str, str], content: bytes) -> List[Tuple[str, str]]:
    parts = urlsplit(url)
    path, query = parts.path, parts.query.encode()
    route, child, miss = find_route(method, path)
    if miss:
        return [(miss, f"{method} {path}")]
    if getattr(route, "dependant", None) is None:
        return []  # a mounted sub-app (the MCP servers) — nothing FastAPI validates at this layer
    flat = flat_dependant(route.dependant)
    scope = {"type": "http", "method": method, "path": path, "root_path": "", "query_string": query,
             "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]}

    async def receive():
        return {"type": "http.request", "body": content, "more_body": False}

    sreq = Request(scope, receive)
    _, perr = request_params_to_args(flat.path_params, child.get("path_params", {}))
    _, qerr = request_params_to_args(flat.query_params, sreq.query_params)
    _, herr = request_params_to_args(flat.header_params, sreq.headers)
    berr: List[Any] = []
    if flat.body_params:
        ctype = headers.get("content-type", headers.get("Content-Type", ""))
        body: Any = None
        if content:
            if "json" in ctype:
                body = json.loads(content)
            elif "form" in ctype:
                body = await sreq.form()
            else:
                body = content
        if _BODY_TAKES_EMBED:
            _, berr = await request_body_to_args(flat.body_params, body, getattr(route, "_embed_body_fields", False))
        else:
            _, berr = await request_body_to_args(flat.body_params, body)
    where = f"{route.endpoint.__module__.rsplit('.', 1)[-1]}.{route.endpoint.__name__}"
    out: List[Tuple[str, str]] = []
    for dep in route_switches(route.dependant):
        out.append(("SWITCHED", f"{dep} at {where}"))
    # §MCPTEST30 (V0538): a tool whose credential its route can never accept fails on every call, whatever it sends.
    # claimTegPayouts, getRelayStatus and relayAction sent an agent's token to routes that authenticate the agent's
    # developer; resolveTegDispute a developer's to a route that authenticates an agent; getCommunityAnnouncements none
    # to a developer route, and turned the 401 into an empty list. Round 10 read three of them as passes (their
    # contracts pinned the refusal), one as an empty feed. The survey gives each tool the credential of its tier.
    needs, auth_deps = route_principal(route.dependant)
    sent = sent_credential(headers)
    if (sent, needs) in (("agent", "developer"), ("developer", "agent"), ("none", "developer"), ("none", "agent")):
        out.append(("TIER", f"{method} {path} sends {sent} credentials and {where} authenticates {needs} "
                            f"({', '.join(auth_deps)})"))
    # §MCPTEST30 (V0538): a route that admits only an admin. On the PUBLIC surface such a tool works for an admin (the
    # tester's public sweep runs as the frame admin, so it reads green) and refuses every other developer. Reported,
    # not gated: whether it belongs on the admin surface is a decision (17 public tools on 2026-10-01).
    if route_admin_gate(route.dependant):
        out.append(("ADMIN_ROUTE", f"{method} {path} admits only an admin ({where})"))
    # §MCPTEST30 (V0547): a route that authenticates only a federation PEER. A tool that sends a developer's, an agent's
    # or no credential there can never succeed; three turned the 401 into an empty list and read as passes on round 14
    # (listFederationAgentCards, listFederationRegistryCards, getFederationPolicyCompliance: {"agent_cards": [],
    # "total": 0} for every caller). Reported; its census may only shrink (the gate's PEER_ROUTE_BASELINE).
    peer = route_peer_auth(route.dependant)
    if peer and sent in ("developer", "agent", "none"):
        out.append(("PEER_ROUTE", f"{method} {path} authenticates only a federation peer ({where}: {', '.join(peer)})"))
    # §MCPTEST30 (V0549): a header the handler (or a dependency) reads and refuses without, which no signature declares.
    # getCloudOperatorSelfLogs, cloudOperatorSelfRestart (a cloud operator's own licence) and federationCliAudit (an
    # operator CLI's) send none and answer 401 or 400 to every MCP caller. A federation credential joins PEER_ROUTE; any
    # other header the handler requires is a field the tool omits, MISSING like a declared one.
    sent_headers = {k.lower() for k in headers}
    for hname, hcode, hwhere in _HH.route_required_headers(route):
        if hname.lower() in sent_headers:
            continue
        if hname.lower() in PEER_HEADERS:
            out.append(("PEER_ROUTE", f"{method} {path} refuses a request without {hname} ({hwhere} answers {hcode}), "
                                       "a federation credential the tool never sends"))
        else:
            out.append(("MISSING", f"{method} {path} [header -> {hname}] required by {hwhere} itself ({hcode})"))
    # §MCPTEST30 (2026-10-01): a query parameter the route does not declare is dropped by FastAPI WITHOUT a word and the
    # request answers 200 (listAgentCards sent `offset` to a route reading `skip`: page 2 was page 1, found by the
    # pagination partition probe). A handler that takes the raw Request may read it itself: reported apart, not gated.
    declared = {(getattr(qp, "alias", None) or qp.name) for qp in flat.query_params}
    takes_request = any(getattr(prm.annotation, "__name__", "") == "Request"
                        for prm in inspect.signature(route.endpoint).parameters.values())
    for qk in sorted({k for k, _ in parse_qsl(parts.query, keep_blank_values=True)} - declared):
        out.append(("UNDECLARED_RAW" if takes_request else "UNDECLARED",
                    f"{method} {path} ?{qk} is no parameter of {where} (it reads {sorted(declared)[:10]})"))
    # §MCPTEST30 (2026-10-01): the same class in a JSON body: a field the route's body model does not declare is dropped
    # by pydantic (extra="ignore") and the request answers 200 (lockUnits' idempotency key, runDiagnosticsSubset's
    # `checks` for `check_ids`, which ran EVERY check). The pass-through dummy's own key is the caller's to send.
    ctype0 = headers.get("content-type", headers.get("Content-Type", "")) or ""
    if flat.body_params and content and "json" in ctype0:
        try:
            jb = json.loads(content)
        except Exception:  # noqa: BLE001
            jb = None
        if isinstance(jb, dict):
            bkeys, opaque = _body_declared(flat, route)
            if not opaque:
                for bk in sorted(set(jb) - bkeys - set(OBJECT_DUMMY)):
                    out.append(("BODY_UNDECLARED", f"{method} {path} body.{bk} is no field of {where} "
                                                   f"(it reads {sorted(bkeys)[:12]})"))
            elif len(flat.body_params) == 1:
                # §MCPTEST30 (V0550): an untyped dict body validates nothing, so a key the handler never reads is dropped
                # without a word (testApiEndpoint's endpoint_path for `path`: every call tested an empty path). The keys
                # the handler reads come from its source; None when it uses the body any other way.
                reads = _HH.handler_body_reads(route.endpoint, flat.body_params[0].name)
                if reads is not None:
                    for bk in sorted(set(jb) - reads - set(OBJECT_DUMMY)):
                        out.append(("BODY_UNREAD", f"{method} {path} body.{bk} is never read by {where} "
                                                   f"(it reads {sorted(reads)[:12]})"))
    for e in list(perr) + list(qerr) + list(herr) + list(berr):
        loc = " -> ".join(str(x) for x in e.get("loc", ()))
        kind = "MISSING" if e.get("type") == "missing" else "TYPE"
        out.append((kind, f"{method} {path} [{loc}] {e.get('msg')} ({where})"))
    return out


async def _validate_captured(req: httpx.Request) -> List[Tuple[str, str]]:
    found = await validate(req.method, str(req.url), dict(req.headers), bytes(req.content))
    try:
        passthrough = json.loads(req.content) == OBJECT_DUMMY
    except Exception:  # noqa: BLE001 — not JSON, so not a pass-through body
        passthrough = False
    return [("PASSTHROUGH" if passthrough and k in ("MISSING", "TYPE") else k, d) for k, d in found]


async def controls() -> Dict[str, List[Tuple[str, str]]]:
    """Hand-built requests with a known answer: the instrument must find what they carry, and nothing in the good one."""
    base = "http://localhost:8000"
    dev = {"authorization": f"Bearer {DEV_TOKEN}"}   # V0538: each models the admin's own call, so it carries the admin's token
    return {
        "missing_query": await validate("PUT", f"{base}/api/v1/admin/disputes/1/ruling", dev, b""),
        "no_route": await validate("GET", f"{base}/api/v1/phase6-no-such-route", dev, b""),
        "missing_body_field": await validate("POST", f"{base}/api/v1/admin/fiat/flare/grant",
                                             {**dev, "content-type": "application/json"}, b'{"developer_id": 1}'),
        "page_too_large": await validate("GET", f"{base}/api/v1/admin/collusion/rings?limit=999999", dev, b""),
        "undeclared_query": await validate("GET", f"{base}/api/v1/admin/collusion/rings?limit=5&phase6_no_such=1", dev, b""),
        "undeclared_body": await validate("POST", f"{base}/api/v1/admin/fiat/flare/grant", {**dev, "content-type": "application/json"},
                                          b'{"developer_id": 1, "flare_tier": "phase6", "phase6_no_such": 1}'),
        "good": await validate("GET", f"{base}/api/v1/admin/collusion/rings?limit=5", dev, b""),
        # §MCPTEST30 (V0538): an agent's token at a route that authenticates the agent's developer, then the developer's
        "tier_agent_at_developer_route": await validate(
            "POST", f"{base}/api/v1/teg/rewards/claim?agent_did=did:theprotocol:phase6", {"authorization": f"Bearer {AGENT_TOKEN}"}, b""),
        "tier_good": await validate(
            "POST", f"{base}/api/v1/teg/rewards/claim?agent_did=did:theprotocol:phase6", {"authorization": f"Bearer {DEV_TOKEN}"}, b""),
        # an admin-flag route (support tickets: require_admin_flag("admin_support")); its control is tier_good above
        "admin_route": await validate("GET", f"{base}/api/v1/admin/support/tickets", dev, b""),
        # §MCPTEST30 (V0547): the peers' agent-card feed (federation_sync.get_agent_cards_for_sync), which a developer's
        # token can never open; its control is every request above (none carries PEER_ROUTE)
        "peer_route": await validate("GET", f"{base}/api/v1/federation/agent-cards?limit=5", dev, b""),
        # §MCPTEST30 (V0549): a cloud operator's own-licence route (the handler checks the header itself): without the
        # header PEER_ROUTE, with it nothing (the header read is the only thing that differs)
        "licence_header": await validate("GET", f"{base}/api/v1/admin/cloud-operators/self-logs?tail=10", dev, b""),
        "licence_header_sent": await validate("GET", f"{base}/api/v1/admin/cloud-operators/self-logs?tail=10",
                                               {**dev, "X-Federation-License": "tp_fed_phase6"}, b""),
        # §MCPTEST30 (V0550): an untyped dict body (the API tester's test-endpoint reads endpoint_test.get("path")): a
        # key it never reads is BODY_UNREAD, the key it reads is nothing
        "unread_body": await validate("POST", f"{base}/api/v1/admin/api-test/test-endpoint",
                                      {**dev, "content-type": "application/json"}, b'{"endpoint_path": "/health", "method": "GET"}'),
        "read_body": await validate("POST", f"{base}/api/v1/admin/api-test/test-endpoint",
                                    {**dev, "content-type": "application/json"}, b'{"path": "/health", "method": "GET"}'),
        # §MCPTEST30 (V0550): an agent's stake (staking_enhanced.stake_tokens: require_staking_enabled) carries SWITCHED
        # and nothing else; every request above that is not a reward claim carries none
        "switched": await validate("POST", f"{base}/api/v1/staking/stake",
                                   {"authorization": f"Bearer {AGENT_TOKEN}", "content-type": "application/json"},
                                   b'{"amount": "10"}'),
    }


async def survey(surface: str) -> Dict[str, Any]:
    tier2: set = set()
    if surface == "admin":
        from agentvault_registry.mcp import server_admin as s
        dispatch, schemas, noauth = s.ADMIN_TOOL_DISPATCH, s.ADMIN_TOOL_SCHEMAS, set(s.ADMIN_NO_AUTH_TOOLS)
        auth = MCPAuthContext(auth_type="developer", developer_id=1, is_admin=True, raw_token=DEV_TOKEN)
    else:
        from agentvault_registry.mcp import server as s
        dispatch, schemas = s.TOOL_DISPATCH, s.ALL_TOOL_SCHEMAS
        noauth = set(dispatch) - set(s.AUTH_REQUIRED_TOOLS)
        tier2 = set(s.TIER2_TOOLS)
        auth = MCPAuthContext(auth_type="developer", developer_id=1, is_admin=False, raw_token=DEV_TOKEN)
    agent_auth = MCPAuthContext(auth_type="agent", agent_did="did:theprotocol:phase6-self", agent_id=1,
                                raw_token=AGENT_TOKEN)
    from agentvault_registry.mcp import tools_admin
    self_host = urlsplit(tools_admin.REGISTRY_SELF_URL).netloc
    by_name = {sc["name"]: sc for sc in schemas if isinstance(sc, dict) and "name" in sc}
    report: Dict[str, Any] = {}
    for name, fn in sorted(dispatch.items()):
        sc = by_name.get(name)
        if sc is None or name.endswith(GATEWAY_TOOLS):
            continue
        row: Dict[str, Any] = {}
        for label, every in (("required", False), ("every", True)):
            CAPTURED.clear()
            a = args_for(sc, every)
            try:
                if name in noauth:
                    await asyncio.wait_for(fn(**a), 8)
                elif name in tier2:
                    await asyncio.wait_for(fn(agent_auth, **a), 8)
                else:
                    await asyncio.wait_for(fn(auth, **a), 8)
                raised = None
            except Exception as e:  # noqa: BLE001 — a survey records, it does not stop
                raised = f"{type(e).__name__}: {str(e)[:160]}"
            found: List[Tuple[str, str]] = []
            external: List[str] = []
            for rq in list(CAPTURED):
                netloc = rq.url.netloc.decode() if isinstance(rq.url.netloc, bytes) else rq.url.netloc
                if netloc != self_host:
                    external.append(f"{rq.method} {rq.url.scheme}://{netloc}{rq.url.path}")
                    continue
                found += await _validate_captured(rq)
            row[label] = {"requests": len(CAPTURED), "raised": raised, "found": found, "external": external}
        report[name] = row
    return report


def classify(report: Dict[str, Any]) -> Dict[str, Dict[str, List[str]]]:
    """class -> tool -> details."""
    cls: Dict[str, Dict[str, List[str]]] = {k: {} for k in (
        "NO_ROUTE", "METHOD", "MISSING_ALWAYS", "MISSING_OPTIONAL", "BOUND", "TYPE", "PASSTHROUGH", "RAISED",
        "NO_REQUEST", "EXTERNAL", "UNDECLARED", "UNDECLARED_RAW", "BODY_UNDECLARED", "BODY_UNREAD", "TIER", "ADMIN_ROUTE",
        "PEER_ROUTE", "SWITCHED")}
    for name, row in report.items():
        req, every = row["required"], row["every"]
        miss_every = sorted({d for k, d in every["found"] if k == "MISSING"})
        miss_req = sorted({d for k, d in req["found"] if k == "MISSING"} - set(miss_every))
        for k, d in every["found"]:
            if k == "TYPE" and _BOUND.search(d):
                # the dummy for a page size is the schema's own maximum (999999 when it declares none), so a route that
                # refuses it serves smaller pages than the schema promises: a caller following the schema is refused
                cls["BOUND"].setdefault(name, []).append(d)
            elif k in ("NO_ROUTE", "METHOD", "TYPE", "PASSTHROUGH", "UNDECLARED", "UNDECLARED_RAW", "BODY_UNDECLARED",
                       "BODY_UNREAD", "TIER", "ADMIN_ROUTE", "PEER_ROUTE", "SWITCHED"):
                if d not in cls[k].get(name, []):
                    cls[k].setdefault(name, []).append(d)
        if miss_every:
            cls["MISSING_ALWAYS"][name] = miss_every
        if miss_req:
            cls["MISSING_OPTIONAL"][name] = miss_req
        if every["raised"] and not every["requests"]:
            cls["RAISED"][name] = [every["raised"]]
        if every["external"]:
            cls["EXTERNAL"][name] = every["external"][:3]
        if not every["requests"] and not every["raised"]:
            cls["NO_REQUEST"][name] = []
    return cls


async def main(surfaces: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"controls": await controls(), "surfaces": {}}
    for s in surfaces:
        rep = await survey(s)
        cls = classify(rep)
        if s == "admin":
            cls["ADMIN_ROUTE"] = {}   # an admin tool at an admin route is where it belongs
        out["surfaces"][s] = {"tools": len(rep), "requests": sum(r["every"]["requests"] for r in rep.values()),
                              "classes": cls}
        out["surfaces"][s]["surveyed"] = sorted(rep)  # §MCPTEST30 (V0547): the sweep grades a row only where it surveyed
    return out


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    result = asyncio.run(main(["admin", "public"] if which == "all" else [which]))
    if "--json" in sys.argv:
        with open(sys.argv[sys.argv.index("--json") + 1], "w") as fh:
            json.dump(result, fh, indent=1, default=str)
    for s, v in result["surfaces"].items():
        print(f"{s}: {v['tools']} tools, {v['requests']} requests")
        for k, tools in v["classes"].items():
            print(f"  == {k}: {len(tools)} tools")
            if k in ("NO_ROUTE", "METHOD", "MISSING_ALWAYS", "MISSING_OPTIONAL", "TYPE", "UNDECLARED", "UNDECLARED_RAW",
                     "BODY_UNDECLARED", "BODY_UNREAD", "TIER", "PEER_ROUTE", "SWITCHED"):
                for t, ds in sorted(tools.items()):
                    for d in ds:
                        print(f"     {t}: {d}")
