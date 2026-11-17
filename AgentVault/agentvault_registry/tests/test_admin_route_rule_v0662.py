"""V0662, the admin guard's one rule (order gwo_c406296cb118596aa7c5c1c2; his suggestion 1, seq 3068;
sessionlogs2026/PLAN_2026-11-13_NO_ADMIN_CALLS_FOR_NON_ADMINS.md).

CrowdSec counts every refused call on a non-static path, so a console page that fires admin calls for a member bans
that member after a few refreshes. The console refuses such a call itself, before sending it, and it reads WHICH
routes need WHICH admin flag from the registry's own routes, never a hand list: services/admin_route_rule walks the
served routes (FastAPI's effective routes, router-level dependencies included) and reads each one's
require_admin_flag(...) dependencies. The console ships the result as a generated file
(static/.../src/services/api/adminRoutes.generated.json, written by scripts/gen_admin_routes.py), and this test fails
the day a route's rule and the committed copy differ, so the guard can never drift from the server.

The rule lists every served route of each /api/v1/<segment> group that holds an admin route, in serving order, each
with the flags it needs (none for a member route): a literal member route served before an admin route with a path
parameter must win, as it does on the server.
Red on f569f6a6e: the module and the generated file do not exist.
"""
from __future__ import annotations

from agentvault_registry.main import app
from agentvault_registry.services import admin_route_rule as R

FLAGS = {"treasury", "support", "enforcement", "federation", "platform"}


def _rule():
    return R.admin_route_rule(app)


def test_the_rule_names_each_routes_flags():
    by = {(m, p): f for m, p, f in _rule()["routes"]}
    assert by[("POST", "/api/v1/teg/treasury/fund-agent")] == ["treasury"]          # an admin route outside /admin
    assert by[("GET", "/api/v1/admin/events/search")] == ["platform"]
    assert by[("GET", "/api/v1/admin/federation/topology-overview")] == ["federation"]
    assert by[("POST", "/api/v1/admin/tutorial/execute")] == []                     # /admin/ in its path, a member's route


def test_the_rule_sees_the_population():
    routes = _rule()["routes"]
    admin = [r for r in routes if r[2]]
    assert len(admin) >= 400, "the walk must reach the included routers' routes, not the 50 the app holds directly"
    assert all(set(f) <= FLAGS for _m, _p, f in routes)
    assert all(p.startswith("/api/v1/") for _m, p, _f in routes)


def test_the_console_ships_the_apps_rule():
    committed = R.load_committed()
    assert committed is not None, f"missing {R.FE_RULE_PATH}: run scripts/gen_admin_routes.py --write"
    assert committed == _rule(), "the console's copy differs from the app's rule: run scripts/gen_admin_routes.py --write"
