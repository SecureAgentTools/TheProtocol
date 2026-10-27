"""POCKET FRAME unit tests — device push router validation, notify fan-out gating,
and reactor message composition (f-mobile, 2026-07-07).

DB-free: everything exercised either short-circuits before DB access or is
monkeypatched. Run in the registry image (has all deps + pytest):

    docker run --rm -v <repo>/AgentVault/agentvault_registry:/mnt \
      --entrypoint bash agentvault2-registry-a:latest \
      -c "cd /mnt && PYTHONPATH=/mnt/src pytest tests/test_device_push.py -q"
"""
import asyncio

from agentvault_registry.routers.device_push import _NTFY_TOPIC_RE, _ALLOWED_RAILS, _ALLOWED_PLATFORMS
from agentvault_registry.background_tasks import push_notify
from agentvault_registry.background_tasks.reactor_push_notify import (
    CapabilityIssuedPushReactor,
    CapabilityRevokedPushReactor,
    DelegationGrantedPushReactor,
)
from agentvault_registry.config import settings


# ---------- router validation surface ----------

def test_ntfy_topic_regex_accepts_sane_topics():
    for ok in ("commander-pixel9", "tp_dev_2", "AbC-123_xyz"):
        assert _NTFY_TOPIC_RE.match(ok), ok


def test_ntfy_topic_regex_rejects_url_hostile_topics():
    for bad in ("ab", "a" * 65, "has space", "slash/attack", "dot.dot", "q?x=1", "#frag", ""):
        assert not _NTFY_TOPIC_RE.match(bad), bad


def test_rails_and_platforms_frozen():
    """A CLOSED set, pinned so a rail cannot be added without someone deciding to.

    §CHATCOHERE-CI (2026-09-01) — `webpush` shipped (§POCKETBRIDGE) and this pin was
    never updated, so it had been red ever since. Pinned to the truth; the point of
    the test is unchanged: adding a rail must be a deliberate edit here too.
    """
    assert _ALLOWED_RAILS == ("ntfy", "fcm", "apns", "webpush")
    assert _ALLOWED_PLATFORMS == ("android", "ios", "web")


# ---------- fan-out gating (no DB touched when disabled / empty) ----------

def test_notify_developers_disabled_short_circuits(monkeypatch):
    monkeypatch.setattr(settings, "PUSH_NOTIFY_ENABLED", False)
    sent = asyncio.run(push_notify.notify_developers([1, 2], title="t", message="m"))
    assert sent == 0


def test_notify_developers_empty_devs_short_circuits(monkeypatch):
    monkeypatch.setattr(settings, "PUSH_NOTIFY_ENABLED", True)
    sent = asyncio.run(push_notify.notify_developers([], title="t", message="m"))
    assert sent == 0


def test_send_ntfy_without_base_url_is_false(monkeypatch):
    monkeypatch.setattr(settings, "PUSH_NTFY_URL", "")
    ok = asyncio.run(push_notify._send_ntfy("topic", "t", "m", "key", "default"))
    assert ok is False


# ---------- reactor message composition (notify + resolve monkeypatched) ----------

def _capture(monkeypatch):
    calls = {}

    async def fake_resolve(dids):
        calls["dids"] = [d for d in dids if d]
        return [42]

    # §CHATCOHERE-CI (2026-09-01) — TWO faults, both from changes these tests were
    # never updated for:
    #   1. §NOTIFV2 made `notify()` the catalog-validated send path and every reactor
    #      moved to it; `notify_developers` is, in its own comment, "kept for
    #      reference". The spy patched the function NOTHING CALLS, so the REAL
    #      notifier ran against the DB and logged a foreign-key violation while the
    #      assertions failed with a KeyError that named the symptom, not the cause.
    #   2. The spy pinned a fixed signature. `notify()` carries `amount` and `click`;
    #      a spy that breaks when the real function grows a keyword is testing its
    #      own signature. `**extra` keeps it honest.
    # `type_key` is captured too — it is the catalog key §NOTIFV2 validates against,
    # so a reactor sending under the wrong key is now a visible failure.
    async def fake_notify(type_key, dev_ids, *, title, message, tags="key",
                          priority="default", **extra):
        calls["type_key"] = type_key
        calls["dev_ids"] = list(dev_ids)
        calls["title"] = title
        calls["message"] = message
        calls["priority"] = priority
        calls.update(extra)
        return 1

    import agentvault_registry.background_tasks.reactor_push_notify as rpn
    monkeypatch.setattr(rpn, "resolve_developer_ids_for_dids", fake_resolve)
    monkeypatch.setattr(rpn, "notify", fake_notify)
    return calls


def test_capability_issued_reactor_composes_message(monkeypatch):
    calls = _capture(monkeypatch)
    r = CapabilityIssuedPushReactor()
    asyncio.run(r.handle_event({
        "token_id": 7, "issuer_did": "did:tp:iss", "holder_did": "did:tp:hold",
        "permissions": ["exchange.order", "teg.transfer"], "budget_total": 500, "currency": "BVT",
        "expires_at": "2026-07-08T00:00:00+00:00",
    }))
    assert calls["dev_ids"] == [42]
    assert "did:tp:iss" in calls["message"] and "did:tp:hold" in calls["message"]
    assert "exchange.order" in calls["message"] and "500" in calls["message"]
    assert calls["type_key"] == "capability.issued"   # the §NOTIFV2 catalog key


def test_capability_revoked_reactor_high_priority(monkeypatch):
    calls = _capture(monkeypatch)
    r = CapabilityRevokedPushReactor()
    asyncio.run(r.handle_event({
        "token_id": 9, "issuer_did": "did:tp:iss", "holder_did": "did:tp:hold",
        "revoked_by": "did:tp:iss", "revoked_count": 3,
    }))
    assert calls["priority"] == "max"  # panic/security → bypass DND
    assert "#9" in calls["message"] and "3" in calls["message"]


def test_device_wants_prefs_matrix():
    w = push_notify._device_wants
    # defaults: delegation events yes, transfers no.
    # §CHATCOHERE-CI — `AgentCapabilityIssued` was REMOVED from the default set on
    # 2026-07-25 on purpose ("routine issuance is high-volume — a spawn spree buries
    # every notification that actually needs a human"). This asserted the pre-July
    # behaviour and had been red since. Now it pins the DECISION in both directions:
    # off by default, and reachable with an explicit opt-in.
    assert w(None, "AgentCapabilityIssued", None) is False
    assert w({"event_types": ["AgentCapabilityIssued"]}, "AgentCapabilityIssued", None) is True
    assert w({}, "AgentDelegationGranted", None) is True
    assert w(None, "AgentCapabilityRevoked", None) is True   # a security event stays default-on
    assert w(None, "LiabilityChallenge", None) is True       # the one push a human must not miss
    assert w(None, "TokensTransferred", 999999) is False
    # explicit allowlist
    assert w({"event_types": ["AgentCapabilityRevoked"]}, "AgentCapabilityRevoked", None) is True
    assert w({"event_types": ["AgentCapabilityRevoked"]}, "AgentCapabilityIssued", None) is False
    # transfer opt-in threshold
    assert w({"min_transfer_avt": 100}, "TokensTransferred", 100) is True
    assert w({"min_transfer_avt": 100}, "TokensTransferred", 99.9) is False
    assert w({"min_transfer_avt": "50"}, "TokensTransferred", 60) is True
    assert w({"min_transfer_avt": "junk"}, "TokensTransferred", 60) is False
    assert w({"min_transfer_avt": 100}, "TokensTransferred", None) is False


# reactor_base registers leader_key globally at __init__ — share ONE instance
# across tests (prod uses a module singleton the same way).
_transfer_reactor = None


def _get_transfer_reactor(rpn):
    global _transfer_reactor
    if _transfer_reactor is None:
        _transfer_reactor = rpn.TransferPushReactor()
    return _transfer_reactor


def test_transfer_reactor_early_exits_without_subscribers(monkeypatch):
    import agentvault_registry.background_tasks.reactor_push_notify as rpn

    async def no_subs():
        return False

    called = {"resolve": 0}

    async def fake_resolve(dids):
        called["resolve"] += 1
        return [1]

    monkeypatch.setattr(rpn, "any_transfer_subscribers", no_subs)
    monkeypatch.setattr(rpn, "resolve_developer_ids_for_dids", fake_resolve)
    asyncio.run(_get_transfer_reactor(rpn).handle_event({"from": "a", "to": "b", "amount": 500}))
    assert called["resolve"] == 0  # early-exit before any per-event work


def test_transfer_reactor_composes_with_amount(monkeypatch):
    import agentvault_registry.background_tasks.reactor_push_notify as rpn
    calls = {}

    async def subs():
        return True

    async def fake_resolve(dids):
        return [7]

    # Same two faults as `_capture`, in this test's own inline spy: it patched
    # `notify_developers` (which no reactor calls since §NOTIFV2) and pinned a
    # signature. See the comment in `_capture`.
    async def fake_notify(type_key, dev_ids, *, title, message, tags="key",
                          priority="default", **extra):
        calls.update(type_key=type_key, dev_ids=list(dev_ids), title=title,
                     message=message, **extra)
        return 1

    monkeypatch.setattr(rpn, "any_transfer_subscribers", subs)
    monkeypatch.setattr(rpn, "resolve_developer_ids_for_dids", fake_resolve)
    monkeypatch.setattr(rpn, "notify", fake_notify)
    asyncio.run(_get_transfer_reactor(rpn).handle_event(
        {"from": "did:tp:a", "to": "did:tp:b", "amount": "250.5", "memo": "rent"}))
    assert calls["amount"] == 250.5 and calls["type_key"] == "money.received"
    assert "did:tp:a" in calls["message"] and "rent" in calls["message"]
    assert "250.5" in calls["title"]


def test_delegation_granted_reactor_includes_granting_dev(monkeypatch):
    calls = _capture(monkeypatch)
    r = DelegationGrantedPushReactor()
    asyncio.run(r.handle_event({
        "delegate_agent_did": "did:tp:delegate", "principal": "dev:2",
        "permissions": ["governance.vote"], "granted_by_dev_id": 2,
    }))
    # resolver returned [42]; granting dev 2 appended
    assert set(calls["dev_ids"]) == {42, 2}
    assert "dev:2" in calls["message"] and "governance.vote" in calls["message"]
