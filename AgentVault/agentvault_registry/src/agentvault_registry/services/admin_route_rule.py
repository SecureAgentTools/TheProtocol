"""V0662, the admin guard's one rule (order gwo_c406296cb118596aa7c5c1c2; his suggestion 1 of 2026-11-13, seq 3068).

Which route needs which admin flag, read from the registry's own served routes rather than a hand list: FastAPI's
effective routes (an included router is a lazy entry in app.routes; its routes carry the full path and the dependant,
router-level dependencies included), and in each dependant the require_admin_flag(...) dependencies (security.py: the
closure holds the flag's name). The console ships the result (scripts/gen_admin_routes.py writes it into
static/new_registry_frontend/src/services/api/adminRoutes.generated.json) and refuses, before sending, a call the
session's flags do not cover (services/api/adminGuard.ts); tests/test_admin_route_rule_v0662.py keeps the copy equal.

The rule lists EVERY served route of each /api/v1/<segment> group that holds an admin route, in serving order, with
the flags it needs ([] for a member route): the console takes the first route that matches, as the server does, so a
literal member route served before an admin route with a path parameter wins there too.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

FE_RULE_PATH = Path(__file__).resolve().parent.parent / "static" / "new_registry_frontend" / "src" / "services" / "api" \
    / "adminRoutes.generated.json"
_NOTE = ("Generated from the registry's served routes by scripts/gen_admin_routes.py (services/admin_route_rule.py); "
         "do not edit. tests/test_admin_route_rule_v0662.py keeps it equal to the app.")


def served_routes(app: Any) -> List[Any]:
    """Every served route, in serving order, as the object carrying its full path and its dependant."""
    try:
        from fastapi.routing import iter_route_contexts
    except ImportError:  # FastAPI before the lazy include: app.routes is already flat
        return list(app.routes)
    return [rc._effective_route for rc in iter_route_contexts(app.routes)]


def _flags(dependant: Any, out: set) -> set:
    for sub in getattr(dependant, "dependencies", None) or []:
        call = getattr(sub, "call", None)
        if getattr(call, "__qualname__", "") == "require_admin_flag.<locals>._check":
            name = inspect.getclosurevars(call).nonlocals.get("flag_name")
            if isinstance(name, str) and name.startswith("admin_"):
                out.add(name[len("admin_"):])
        _flags(sub, out)
    return out


def _group(path: str) -> str:
    parts = path.split("/")
    return "/".join(parts[:4])          # '', 'api', 'v1', '<segment>'


def admin_route_rule(app: Any) -> Dict[str, Any]:
    entries: List[List[Any]] = []
    for r in served_routes(app):
        path = getattr(r, "path", "") or ""
        methods = sorted(m for m in (getattr(r, "methods", None) or []) if m != "HEAD")
        if not path.startswith("/api/v1/") or not methods:
            continue
        flags = sorted(_flags(getattr(r, "dependant", None), set()))
        for m in methods:
            entries.append([m, path, flags])
    admin_groups = {_group(p) for _m, p, f in entries if f}
    return {"note": _NOTE, "routes": [e for e in entries if _group(e[1]) in admin_groups]}


def render(rule: Dict[str, Any]) -> str:
    """One route a line, so a change reads as a diff of the routes it touches."""
    lines = ["{", f'  "note": {json.dumps(rule["note"])},', '  "routes": [']
    rows = [f"    {json.dumps(r, separators=(', ', ': '))}" for r in rule["routes"]]
    lines.append(",\n".join(rows))
    lines += ["  ]", "}"]
    return "\n".join(lines) + "\n"


def load_committed(path: Path = FE_RULE_PATH) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
