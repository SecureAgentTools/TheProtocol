"""§FEFRAME W3 (V0504): which token each route takes, read from the FastAPI dependency tree, never from a path list.

The console decided "agent token or developer token?" with substring rules (`services/api/tier.ts`: a path containing
`/exchange/portfolio` got an AGENT token, so `/developers/me/exchange/portfolio` did too, §COCKPITBOOK), and the
OpenAPI document labelled 14 of 1,298 operations `AgentJWT` from a hand list of path hints, so `POST /agora/orders` and
`POST /agents/spawn` read as developer routes although both take an agent token. Both now come from ONE walk:

  AGENT   the route depends on the agent-JWT verifier (`security.verify_agent_token`: through get_current_agent,
          require_agent_permission or routers.utils.get_current_agent)
  EITHER  it takes an agent OR a developer token (`get_current_actor_for_read` and its optional twin, the agent-log
          reader's own decoder)
  (else)  developer-tier or public: the console sends its developer token, the document says DeveloperJWT

`tier_map(app)` lists the AGENT and EITHER operations; `write(path)` writes the console's copy
(`static/new_registry_frontend/src/services/api/authTiers.generated.json`) and tests/test_auth_tiers.py fails when that
copy and the running app disagree:  python -m agentvault_registry.core.auth_tiers --write <that path>
"""
from __future__ import annotations

import json
import sys
from typing import Any, Dict, Iterable, List, Optional, Set

AGENT, EITHER = "agent", "either"
FE_COPY = "static/new_registry_frontend/src/services/api/authTiers.generated.json"
_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")


def _agent_calls() -> Set[Any]:
    from agentvault_registry import security
    return {security.verify_agent_token}


def _either_calls() -> Set[Any]:
    from agentvault_registry import security
    out = {security.get_current_actor_for_read, security.get_current_actor_for_read_optional}
    try:
        from agentvault_registry.routers import agent_logs
        out.add(agent_logs.get_auth_context)
    except Exception:  # noqa: BLE001 — a registry without the router simply has no such route
        pass
    return out


def _calls(dependant, out: Optional[Set[Any]] = None, depth: int = 0) -> Set[Any]:
    """Every callable in a route's dependency tree (router-level dependencies included: FastAPI folds them in)."""
    out = set() if out is None else out
    if depth > 40:
        return out
    for d in getattr(dependant, "dependencies", None) or []:
        call = getattr(d, "call", None)
        if call is not None:
            out.add(call)
        _calls(d, out, depth + 1)
    return out


def route_tier(route, agent_calls: Optional[Set[Any]] = None, either_calls: Optional[Set[Any]] = None) -> Optional[str]:
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return None
    calls = _calls(dependant)
    if calls & (agent_calls if agent_calls is not None else _agent_calls()):
        return AGENT
    if calls & (either_calls if either_calls is not None else _either_calls()):
        return EITHER
    return None


def api_routes(app) -> Iterable[Any]:
    """Every API operation with its full path. FastAPI 0.141 keeps an included router NESTED (`app.routes` holds
    `_IncludedRouter` branches, 173 of 226 entries on this app), so a plain `isinstance(route, APIRoute)` loop sees
    only the app's own 52 routes and none of the routers' (measured: a walk that way found 0 agent routes). The route
    contexts are what the OpenAPI generator itself iterates; an older FastAPI without them has flat APIRoutes."""
    from fastapi import routing as _routing
    iter_contexts = getattr(_routing, "iter_route_contexts", None)
    if iter_contexts is None:
        for route in app.routes:
            if isinstance(route, _routing.APIRoute):
                yield route
        return
    for ctx in iter_contexts(app.routes):
        if isinstance(getattr(ctx, "original_route", None), _routing.APIRoute):
            yield ctx


def operations(app) -> List[tuple]:
    """(method, path, tier or None) for every operation, in REGISTRATION order (the order FastAPI tries them)."""
    agent_calls, either_calls = _agent_calls(), _either_calls()
    out = []
    for route in api_routes(app):
        path = getattr(route, "path_format", None) or getattr(route, "path", None)
        if not path:
            continue
        tier = route_tier(route, agent_calls, either_calls)
        for m in sorted(getattr(route, "methods", None) or ()):
            if m in _METHODS:
                out.append((m, path, tier))
    return out


def tier_map(app) -> List[Dict[str, str]]:
    """[{method, path, tier}] for every AGENT or EITHER operation, sorted (a stable list)."""
    rows = {(m, p, t) for (m, p, t) in operations(app) if t}
    return [{"method": m, "path": p, "tier": t} for (m, p, t) in sorted(rows, key=lambda r: (r[1], r[0]))]


def operation_tiers(app) -> Dict[tuple, str]:
    """{(path, method lowercase): tier} for the OpenAPI labels (same walk)."""
    return {(r["path"], r["method"].lower()): r["tier"] for r in tier_map(app)}


def _segments(path: str) -> List[str]:
    return [s for s in path.split("/") if s != ""]


def _is_param(seg: str) -> bool:
    return seg.startswith("{") and seg.endswith("}")


def _is_tail(seg: str) -> bool:
    return _is_param(seg) and seg[1:-1].split(":", 1)[-1] == "path"


def templates_intersect(a: str, b: str) -> bool:
    """True when some concrete path matches both FastAPI templates (`{x}` = one segment, `{x:path}` = the rest)."""
    sa, sb = _segments(a), _segments(b)
    i = 0
    while i < len(sa) and i < len(sb):
        x, y = sa[i], sb[i]
        if _is_tail(x) or _is_tail(y):
            return True
        if not _is_param(x) and not _is_param(y) and x != y:
            return False
        i += 1
    if len(sa) == len(sb):
        return True
    rest = sa[i:] if len(sa) > len(sb) else sb[i:]
    return len(rest) == 1 and _is_tail(rest[0])


def document(app) -> Dict[str, Any]:
    """The console's copy. `routes` = [method, path, code] in REGISTRATION order; code `a` (agent token), `e` (agent
    or developer token) or `d` (neither: listed only because a concrete URL can match both it and an `a`/`e` template,
    e.g. a literal `/agents/spawn` beside a templated `/agents/{did}`). The console takes the FIRST template that
    matches, as FastAPI does, so a `d` route registered first shadows the templated agent route exactly as it does on
    the server; a route that can never meet an `a`/`e` template is left out (it reads `d` by absence)."""
    ops = operations(app)
    tiered = [(m, p) for (m, p, t) in ops if t]
    rows, seen = [], set()
    for (m, p, t) in ops:
        if (m, p) in seen:
            continue                      # FastAPI answers with the first registration; a duplicate never matches
        seen.add((m, p))
        if t:
            rows.append([m, p, "a" if t == AGENT else "e"])
        elif any(m == m2 and templates_intersect(p, p2) for (m2, p2) in tiered):
            rows.append([m, p, "d"])
    return {
        "version": 2,
        "source": "agentvault_registry/core/auth_tiers.py (the FastAPI dependency tree, registration order)",
        "counts": {code: sum(1 for r in rows if r[2] == code) for code in ("a", "e", "d")},
        "routes": rows,
    }


def write(path: str, app=None) -> Dict[str, Any]:
    if app is None:
        from agentvault_registry.main import app as _app
        app = _app
    doc = document(app)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, sort_keys=False)
        f.write("\n")
    return doc


if __name__ == "__main__":  # python -m agentvault_registry.core.auth_tiers --write <path>
    if len(sys.argv) == 3 and sys.argv[1] == "--write":
        d = write(sys.argv[2])
        print(f"wrote {sys.argv[2]}: {d['counts']}")
    else:
        sys.exit(__doc__)
