"""§SECFIX (2026-09-25), two found while censusing the registry's Docker socket users for F6:

1. /api/v1/ws/docker-stats subscribed ANY authenticated developer to host and container telemetry: the route called
   manager.subscribe directly (topic_allowed's admin rule never ran) and its get_stats message called the HTTP handler
   get_docker_stats with the developer object, around that handler's require_admin_flag("admin_platform").
2. /api/v1/admin/ironhand/identities read Frame A's SPIRE container by name ("agentvault-spire-server") instead of this
   frame's (services/agent_spire.SPIRE_CONTAINER), so on a shared host EU and ASIA listed Frame A's entries.

RED control: the tree before the fix has no may_watch_docker_stats and names the container literally.
"""
import ast
import pathlib
from types import SimpleNamespace

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
WS = SRC / "routers" / "websocket.py"
MTLS = SRC / "routers" / "agent_mtls.py"


def _fn(tree, name):
    return next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def _load_rule():
    src = WS.read_text(encoding="utf-8")
    seg = ast.get_source_segment(src, _fn(ast.parse(src), "may_watch_docker_stats"))
    ns = {}
    exec(seg, ns)  # the pure predicate alone: importing the router needs the whole app's settings
    return ns["may_watch_docker_stats"]


def test_the_socket_takes_the_http_routes_rule():
    rule = _load_rule()
    dev = lambda **kw: SimpleNamespace(**{"is_admin": False, "admin_platform": False, "must_change_password": False, **kw})
    assert not rule(dev()), "a plain developer"
    assert rule(dev(admin_platform=True)), "the admin_platform flag"
    assert rule(dev(is_admin=True)), "legacy is_admin passes every flag"
    assert not rule(dev(is_admin=True, must_change_password=True)), "never while a password change is forced"
    assert not rule(SimpleNamespace()), "an object with no flags at all"


def test_the_rule_runs_before_anything_is_subscribed():
    src = WS.read_text(encoding="utf-8")
    fn = ast.get_source_segment(src, _fn(ast.parse(src), "websocket_docker_stats"))
    check, connect = fn.find("may_watch_docker_stats(developer)"), fn.find("manager.connect(")
    assert check != -1 and connect != -1 and check < connect, "the check must come before the socket is connected"
    assert "await websocket.close(code=1008" in fn


def test_ironhand_identities_reads_this_frames_spire_server():
    src = MTLS.read_text(encoding="utf-8")
    assert 'containers.get("agentvault-spire-server")' not in src
    assert "from ..services.agent_spire import SPIRE_CONTAINER as _spire_container" in src
