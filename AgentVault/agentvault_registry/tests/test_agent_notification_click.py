"""D6-781 (2026-10-17): the agent-owner notifications open a page their owner can open.

Seven owner notifications (agent.mtls_revoked; agent.suspended and agent.reinstated from the single-agent rail and the
coordinated one; agent.health_changed; agent.slashed) clicked through to "/ui/#/agents", a route the console has only
inside Pocket (#/pocket/agents). The desktop bell opens a click's hash route as given (NotificationBell's feedRoute), so
the in-app row opened the not-found page, and a web push opened the same address. The click is now the desktop agent
list, "/ui/#/my-agents" (the format D6-679 used): the desktop bell opens My Agents, and Pocket's alerts send every agent.*
type to Pocket's own Agents tab whatever a desktop click says (services/notificationDoors.ts, rule 2, pinned in
notificationDoors.test.ts), so each device lands on its own agent list. Read from the source and the console's router:
nothing runs and nothing is sent.
"""
from __future__ import annotations

import ast
import os
import re
from collections import Counter
from pathlib import Path

import pytest

import agentvault_registry

PKG = Path(agentvault_registry.__file__).resolve().parent
ROUTER = PKG / "static" / "new_registry_frontend" / "src" / "router" / "index.ts"
NOTIFIERS = {"notify_agent_owners", "notify", "notify_developers"}
AGENT_LIST = "/ui/#/my-agents"
# the seven sites the finding named, by module and notification type
NAMED = Counter({
    ("routers/agent_mtls.py", "agent.mtls_revoked"): 1,
    ("routers/enforcement_admin.py", "agent.suspended"): 1,
    ("routers/enforcement_admin.py", "agent.reinstated"): 1,
    ("background_tasks/agent_health_checker.py", "agent.health_changed"): 1,
    ("services/coordinated_suspension.py", "agent.suspended"): 1,
    ("services/coordinated_suspension.py", "agent.reinstated"): 1,
    ("services/force_unstake.py", "agent.slashed"): 1,
})


def _agent_notifications():
    """(module, type, click) for every notification call in the package whose type is agent.* and that names a click.
    The console's tree (static/) is not walked: it holds no Python, and its node_modules may be a link elsewhere."""
    out = []
    for root, dirs, files in os.walk(PKG):
        dirs[:] = [d for d in dirs if d not in ("static", "__pycache__", "node_modules")]
        for fn in files:
            if not fn.endswith(".py"):
                continue
            path = Path(root) / fn
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if not isinstance(node, ast.Call) or not node.args:
                    continue
                name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                first = node.args[0]
                if name not in NOTIFIERS or not (isinstance(first, ast.Constant) and isinstance(first.value, str)
                                                 and first.value.startswith("agent.")):
                    continue
                click = next((k.value for k in node.keywords if k.arg == "click"), None)
                if click is not None:
                    shown = click.value if isinstance(click, ast.Constant) else ast.unparse(click)
                    out.append((path.relative_to(PKG).as_posix(), first.value, shown))
    return out


def _console_routes(src: str) -> dict:
    """{full path: the route's own source, its children left out} for every route of the console's `routes` table, path
    segments joined through `children` the way vue-router joins them. A small scanner: strings and comments are skipped,
    so a brace or a path inside one is not read as a route."""
    start = src.index("= [", src.index("const routes")) + 2   # the table, not the `RouteRecordRaw[]` type before it
    routes, stack, i, n = {}, [], start, len(src)
    while i < n:
        c = src[i]
        if src.startswith("//", i):
            i = src.find("\n", i) if src.find("\n", i) >= 0 else n
            continue
        if src.startswith("/*", i):
            i = src.index("*/", i + 2) + 2
            continue
        if c in "'\"`":
            j = i + 1
            while src[j] != c:
                j += 2 if src[j] == "\\" else 1
            if stack and stack[-1][0] == "{" and stack[-1][2] is None and re.search(r"\bpath:\s*$", src[i - 20:i]):
                stack[-1][2] = src[i + 1:j]
            i = j + 1
            continue
        if c in "{[":
            stack.append([c, i, None])
        elif c in "}]":
            kind, at, seg = stack.pop()
            if kind == "{" and seg is not None:
                full = ""
                for s in [f[2] for f in stack if f[0] == "{" and f[2] is not None] + [seg]:
                    full = s if s.startswith("/") else (full.rstrip("/") + "/" + s if s else full)
                routes.setdefault(full or "/", src[at:i + 1].split("children:", 1)[0])
            if not stack:
                break
        i += 1
    assert not stack, "the scanner did not reach the end of the routes table"
    return routes


def test_the_seven_named_notifications_open_the_desktop_agent_list():
    found = _agent_notifications()
    missing = NAMED - Counter((rel, t) for rel, t, _ in found)
    assert not missing, f"the reader no longer sees these notifications: {sorted(missing)}"
    named = [(rel, t, click) for rel, t, click in found if (rel, t) in NAMED]
    assert [x for x in named if x[2] != AGENT_LIST] == [], f"a click other than {AGENT_LIST}"


@pytest.mark.skipif(not ROUTER.is_file(), reason="the console source is not in this tree (a release image)")
def test_every_agent_notification_click_is_a_page_the_console_serves_its_owner():
    routes = _console_routes(ROUTER.read_text(encoding="utf-8"))
    # the instrument first: it reads the whole table, nested Pocket routes and the dashboard's children alike
    assert len(routes) >= 150 and {"/pocket/agents", "/leaderboard", "/my-agents"} <= set(routes), sorted(routes)[:20]
    assert "/agents" not in routes, "the console serves #/agents now: D6-781's premise changed"
    clicks = {click for _rel, _t, click in _agent_notifications()}
    assert clicks, "the reader found no agent notification that names a click"
    for click in sorted(clicks):
        path = click.split("#", 1)[1].split("?", 1)[0]
        assert path in routes, f"{click}: the console has no route {path}"
        own = routes[path]
        assert "requiresRole: 'admin'" not in own and "requiresAdminFlag" not in own and "requiresAdmin:" not in own, \
            f"{click}: an administrator's page, and these go to the agents' owners"
