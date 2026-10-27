"""§FESUITE (2026-10-10, lifecycle 87): a broadcast scoped to one organization reaches that organization's members only.

Measured before: every live push about it went to EVERY connected developer of the frame, title and body (the push
named no audience, and the notification's data carried no target_org_id, so the socket manager's org filter never
applied); the scheduled path pushed with no audience at all; only the bell's read was scoped. Now the live pushes name
the org_<id> audience the manager resolves (§bc4 T4.3), and the data carries target_org_id (the per-org mute reads it).
The delivery test drives the real ConnectionManager with fake sockets: the member gets it, the outsider does not; the
control is an untargeted broadcast, which still reaches both.
"""
import ast
import asyncio
import pathlib
import types

from agentvault_registry.routers import admin_broadcast as ab
from agentvault_registry.routers import websocket as wsmod

ROUTER = pathlib.Path(ab.__file__)
SCHEDULER = ROUTER.parent.parent / "background_tasks" / "broadcast_scheduler.py"


def test_the_audience_is_the_developer_then_the_organization_then_everyone():
    assert ab.ws_audience(types.SimpleNamespace(target_developer_id=9, target_org_id=None)) == "user_9"
    assert ab.ws_audience(types.SimpleNamespace(target_developer_id=None, target_org_id="org-7")) == "org_org-7"
    assert ab.ws_audience(types.SimpleNamespace(target_developer_id=None, target_org_id=None)) is None
    assert ab.ws_audience(types.SimpleNamespace(target_developer_id=None)) is None


def _function(path, name):
    tree = ast.parse(path.read_text())
    return next(n for n in ast.walk(tree) if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == name)


def _pushes(fn):
    return [n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "broadcast"]


def test_the_live_notification_carries_its_organization():
    # both sends push the one notice (§SECFIX D6-304: the scheduler had its own, without the organization or the id);
    # tests/test_broadcast_scheduled_send.py drives the scheduled one
    b = types.SimpleNamespace(id=1, title="t", body="b", broadcast_type="info", cta_url=None, cta_label=None,
                              requires_ack=False, target_org_id="org-7")
    assert ab.live_notice(b)["data"]["target_org_id"] == "org-7"
    for fn in (_function(ROUTER, "create_broadcast"), _function(SCHEDULER, "_cycle_once")):
        msg = _pushes(fn)[0].args[0]
        assert isinstance(msg, ast.Call) and getattr(msg.func, "id", None) == "live_notice"


def test_the_scheduled_push_names_the_broadcasts_audience():
    calls = _pushes(_function(SCHEDULER, "_cycle_once"))
    assert calls, "the scheduler makes no push"
    for c in calls:
        assert any(k.arg == "audience" for k in c.keywords), "the scheduled push goes to everyone regardless of target"


class _Sock:
    def __init__(self):
        self.sent = []

    async def send_json(self, m):
        self.sent.append(m)


def _deliver(audience, data):
    mgr = wsmod.ConnectionManager()
    member, outsider = _Sock(), _Sock()
    mgr.active_connections = {"11": member, "12": outsider}
    mgr.connection_users = {"11": {"id": "11", "org_ids": ["org-7"]}, "12": {"id": "12", "org_ids": []}}

    async def no_prefs(_uid):
        return None

    mgr._get_dev_prefs = no_prefs
    asyncio.run(mgr._local_broadcast({"type": "notification", "data": data}, audience=audience))
    return len(member.sent), len(outsider.sent)


def test_the_member_gets_the_org_broadcast_and_the_outsider_does_not():
    b = types.SimpleNamespace(target_developer_id=None, target_org_id="org-7")
    assert _deliver(ab.ws_audience(b), {"title": "t", "message": "m", "type": "info", "target_org_id": "org-7"}) == (1, 0)
    # a critical one too: an organization's notice is the organization's, whatever its type
    assert _deliver(ab.ws_audience(b), {"title": "t", "message": "m", "type": "critical", "target_org_id": "org-7"}) == (1, 0)


def test_control_an_untargeted_broadcast_reaches_everyone():
    b = types.SimpleNamespace(target_developer_id=None, target_org_id=None)
    assert _deliver(ab.ws_audience(b), {"title": "t", "message": "m", "type": "info"}) == (1, 1)
