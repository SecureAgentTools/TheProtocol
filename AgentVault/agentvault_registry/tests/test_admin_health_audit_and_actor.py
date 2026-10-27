"""§DOCSFIX D6-612 + D6-766 (2026-10-16): two admin acts in routers/admin_health.py.

D6-612: changing an event emission policy emitted EventEmissionPolicyUpdated carrying the admin's email address. The
event store is immutable, so the address could never be erased there, and the policy reactor passes the event on to
every `federation.emission_policy_updated` webhook. The event names the admin by developer id only.

D6-766: an admin can test, disable or enable ANY developer's webhook (`/admin/webhooks/{id}/test|disable|enable`) and
none of the three wrote an audit row. Each now writes one (`admin.webhook.<act>`, the webhook, its owner, the outcome).

The route functions are driven with recording doubles: a strict emitter, the audit writer, a webhook service.
"""
from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace

import pytest

from agentvault_registry import event_emitter as EE
from agentvault_registry.routers import admin_health as AH
from agentvault_registry.services import admin_audit

# the module, not the package attribute of the same name (services/__init__ binds an instance to it)
webhook_service = importlib.import_module("agentvault_registry.services.webhook_service")

from tests._doubles import StrictEmitter  # noqa: E402

ADMIN = SimpleNamespace(id=10, email="admin@frame.example", is_admin=True)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Session:
    def __init__(self, obj):
        self.obj = obj
        self.commits = 0

    async def execute(self, stmt):
        return SimpleNamespace(scalar_one_or_none=lambda: self.obj)

    async def commit(self):
        self.commits += 1

    async def refresh(self, obj):
        return None


def test_the_policy_event_names_the_admin_by_id_only(monkeypatch):
    emitter = StrictEmitter()

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr(EE, "get_event_emitter", lambda: emitter)
    monkeypatch.setattr(EE, "_load_emission_policies", _noop)
    monkeypatch.setattr(EE, "publish_emission_policy_invalidation", _noop)
    policy = SimpleNamespace(event_type="AgentHeartbeat", emit_from_teg=False, emit_from_registry=True,
                             skip_in_projection=False, description="heartbeat")
    out = _run(AH.update_event_emission_policy("AgentHeartbeat", {"emit_from_registry": False},
                                               current_developer=ADMIN, db=_Session(policy)))
    assert out["status"] == "updated"
    ev = emitter.assert_received("EventEmissionPolicyUpdated")
    assert ev["data"]["actor_developer_id"] == 10
    assert "actor_email" not in ev["data"]
    assert "admin@frame.example" not in repr(ev), "no address anywhere in the immutable event"


@pytest.fixture
def audited(monkeypatch):
    rows = []

    async def _log(db, **kw):
        rows.append(kw)

    monkeypatch.setattr(admin_audit, "log_admin_action", _log)
    return rows


def _hook(active=True):
    return SimpleNamespace(id="wh-1", developer_id=77, is_active=active, failure_count=3)


@pytest.mark.parametrize("route,active,changed", [
    ("disable", True, True), ("disable", False, False), ("enable", False, True), ("enable", True, False)])
def test_disable_and_enable_write_an_audit_row(audited, route, active, changed):
    hook = _hook(active)
    fn = AH.admin_disable_webhook if route == "disable" else AH.admin_enable_webhook
    out = _run(fn("wh-1", db=_Session(hook), _admin=ADMIN))
    assert out["changed"] is changed
    assert len(audited) == 1, audited
    row = audited[0]
    assert row["action"] == f"webhook.{route}" and row["actor_id"] == "10"
    assert (row["target_type"], row["target_id"]) == ("webhook", "wh-1")
    assert row["details"]["owner_developer_id"] == 77 and row["details"]["changed"] is changed


def test_an_admin_test_delivery_writes_an_audit_row(monkeypatch, audited):
    class _Svc:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def deliver_webhook(self, **kw):
            return SimpleNamespace(id="dl-9", response_status=204)

    monkeypatch.setattr(webhook_service, "WebhookService", _Svc)
    out = _run(AH.admin_test_webhook("wh-1", db=_Session(_hook()), _admin=ADMIN))
    assert out["success"] is True
    assert len(audited) == 1
    row = audited[0]
    assert row["action"] == "webhook.test" and row["target_id"] == "wh-1"
    assert row["details"] == {"owner_developer_id": 77, "status_code": 204, "delivery_id": "dl-9"}


def test_the_reactor_passes_no_address_on_to_webhooks(monkeypatch):
    """An event written before this fix still carries actor_email; the policy reactor hands the event to every
    federation.emission_policy_updated webhook and must not hand the address on with it."""
    R = importlib.import_module("agentvault_registry.background_tasks.reactor_emission_policy_updated")
    sent = []

    async def _noop(*a, **k):
        return None

    async def _dispatch(event_type, event_data, *, source_label="reactor", developer_id=None):
        sent.append((event_type, dict(event_data)))
        return 1

    monkeypatch.setattr(R, "_refresh_local_registry_cache", _noop)
    monkeypatch.setattr(R, "_refresh_teg_policy_cache", _noop)
    monkeypatch.setattr(R, "dispatch_webhook_event", _dispatch)
    old_event = {"event_type": "AgentHeartbeat", "emit_from_registry": False, "actor_developer_id": 10,
                 "actor_email": "admin@frame.example"}
    _run(R.EventEmissionPolicyUpdatedReactor.handle_event(SimpleNamespace(name="EventEmissionPolicyUpdated"),
                                                          old_event))
    assert [t for t, _ in sent] == ["federation.emission_policy_updated"]
    assert "actor_email" not in sent[0][1] and sent[0][1]["actor_developer_id"] == 10
