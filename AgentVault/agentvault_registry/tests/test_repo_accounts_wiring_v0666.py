"""V0666 repository accounts, the wiring (gwo_662c03447bcd627afa4a11e5): what the flow's own tests cannot see.

  - the routes: GET and POST /api/v1/developers/me/repo-account (the developer's own; the POST needs `confirm`), and the admin's
    GET /api/v1/admin/repo-accounts/stuck (admin_platform); main.py includes the router and starts the worker
  - the legs ride the act they follow, in its transaction: suspend_developer queues `pause`, reinstate_developer `restore`,
    delete_developer `close`, each BEFORE that route's commit, so the act and its leg commit (or roll back) together; the
    account deletion worker queues `close` too
  - the submit gate: proposing a code change asks repo_accounts.require_linked BEFORE the flow runs, and its refusal answers with
    its code and sentence
RED on 633f06b42: routers/repo_accounts and background_tasks/repo_account_worker do not exist.
"""
from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"


def _fn(path: Path, name: str) -> ast.AST:
    tree = ast.parse(path.read_text())
    return next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def _calls_in_order(fn: ast.AST):
    out = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            f = n.func
            name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else None
            args = [a.value for a in n.args if isinstance(a, ast.Constant)]
            out.append((n.lineno, name, args))
    return sorted(out)


def test_the_routes_and_their_guards():
    from agentvault_registry.routers import repo_accounts as r
    routes = {(m, rt.path) for rt in r.router.routes for m in rt.methods}
    assert ("GET", "/api/v1/developers/me/repo-account") in routes
    assert ("POST", "/api/v1/developers/me/repo-account") in routes
    assert ("GET", "/api/v1/admin/repo-accounts/stuck") in routes
    text = (SRC / "routers" / "repo_accounts.py").read_text()
    assert 'require_admin_flag("admin_platform")' in text and "get_current_developer" in text
    assert "confirm" in text


def test_main_includes_the_router_and_starts_the_worker():
    text = (SRC / "main.py").read_text()
    assert "routers import repo_accounts" in text and "_repo_accounts_router.router" in text
    assert "repo_account_worker_loop" in text


def test_the_worker_drains_under_leadership_and_only_when_the_switch_is_on():
    text = (SRC / "background_tasks" / "repo_account_worker.py").read_text()
    assert "try_acquire_leadership" in text and "is_leader(" not in text
    assert "repo_accounts.enabled()" in text and "drain_once" in text


def _queues_before_commit(route_file: Path, fn_name: str, op: str):
    calls = _calls_in_order(_fn(route_file, fn_name))
    q = [ln for ln, name, args in calls if name == "enqueue_in" and op in args]
    c = [ln for ln, name, _a in calls if name == "commit"]
    assert q, f"{fn_name} queues no {op}"
    assert c and q[0] < c[0], f"{fn_name}: the {op} leg must be written before the route's commit"


def test_the_legs_ride_the_acts_they_follow():
    f = SRC / "routers" / "admin_developers.py"
    _queues_before_commit(f, "suspend_developer", "pause")
    _queues_before_commit(f, "reinstate_developer", "restore")
    _queues_before_commit(f, "delete_developer", "close")


def test_the_account_deletion_worker_closes_the_account():
    text = (SRC / "background_tasks" / "account_deletion_worker.py").read_text()
    assert "enqueue_in" in text and '"close"' in text


def test_the_submit_gate_comes_before_the_flow():
    calls = _calls_in_order(_fn(SRC / "routers" / "code_changes.py", "propose"))
    gate = [ln for ln, name, _a in calls if name == "require_linked"]
    flow = [ln for ln, name, _a in calls if name == "propose"]
    assert gate and flow and gate[0] < flow[0], calls
    text = (SRC / "routers" / "code_changes.py").read_text()
    assert "RepoAccountRefusal" in text
