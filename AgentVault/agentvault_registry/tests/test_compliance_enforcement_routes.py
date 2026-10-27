"""§MCPTEST30 (V0562): the compliance page's mutations, pinned where nothing pinned them.

- The registry quarantine routes (/api/v1/admin/enforcement/registries/*): each needs the enforcement admin flag; a peer
  with no record is a 404 (quarantine, blacklist) or a 400 (lift); a reason or hash the route refuses never reaches the
  monitor (422 at validation).
- The enforcement mode: a change is stored with who made it and lands on the ledger; asking for the mode it already has
  writes nothing and emits nothing; a mode outside off/dry_run/enforcing never reaches the handler.
"""
import inspect

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from agentvault_registry.routers import consul_admin as ca
from agentvault_registry.routers import enforcement_admin as ea


class _Admin:
    email = "admin@test.sandbox"


# ── the registry quarantine routes ───────────────────────────────────────────

@pytest.mark.parametrize("fn", [ea.list_quarantined_registries, ea.quarantine_registry, ea.lift_registry_quarantine,
                                ea.blacklist_registry])
def test_every_registry_route_needs_the_enforcement_flag(fn):
    assert 'require_admin_flag("admin_enforcement")' in inspect.getsource(fn)


@pytest.mark.parametrize("model,body", [
    (ea.RegistryQuarantineRequest, {"reason": "why"}),                                 # under 5 characters
    (ea.RegistryQuarantineRequest, {"reason": "valid reason", "grace_hours": 337}),   # above two weeks
    (ea.RegistryLiftQuarantineRequest, {"new_policy_hash": "a" * 63}),
    (ea.RegistryBlacklistRequest, {"reason": "too short"}),                            # under 10 characters
])
def test_a_body_the_routes_refuse_never_reaches_the_monitor(model, body):
    with pytest.raises(ValidationError):
        model(**body)


class _Monitor:
    def __init__(self, raises=None):
        self.raises, self.calls = raises, []

    async def trigger_quarantine(self, **kw):
        self.calls.append(("quarantine", kw))
        if self.raises:
            raise self.raises

    async def lift_quarantine(self, **kw):
        self.calls.append(("lift", kw))
        if self.raises:
            raise self.raises

    async def trigger_blacklist(self, **kw):
        self.calls.append(("blacklist", kw))
        if self.raises:
            raise self.raises


@pytest.mark.asyncio
async def test_a_peer_with_no_record_is_refused_by_each_route(monkeypatch):
    mon = _Monitor(raises=ValueError("No compliance record for peer_id=999999"))
    monkeypatch.setattr(ea, "get_federation_compliance_monitor", lambda: mon)
    with pytest.raises(HTTPException) as e:
        await ea.quarantine_registry(999999, ea.RegistryQuarantineRequest(reason="phase probe"), db=None, admin=_Admin())
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        await ea.lift_registry_quarantine(999999, ea.RegistryLiftQuarantineRequest(new_policy_hash="a" * 64), db=None, admin=_Admin())
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        await ea.blacklist_registry(999999, ea.RegistryBlacklistRequest(reason="a reason long enough"), db=None, admin=_Admin())
    assert e.value.status_code == 404


@pytest.mark.asyncio
async def test_the_routes_pass_the_admin_and_the_reason_to_the_monitor(monkeypatch):
    mon = _Monitor()
    monkeypatch.setattr(ea, "get_federation_compliance_monitor", lambda: mon)
    out = await ea.quarantine_registry(2, ea.RegistryQuarantineRequest(reason="drift reviewed", grace_hours=48), db=None,
                                       admin=_Admin())
    assert out == {"peer_registry_id": 2, "federation_status": "quarantined", "grace_hours": 48,
                   "quarantined_by": "admin@test.sandbox"}
    kind, kw = mon.calls[0]
    assert (kind, kw["peer_id"], kw["reason"], kw["grace_hours"], kw["admin_email"]) == \
        ("quarantine", 2, "drift reviewed", 48, "admin@test.sandbox")


# ── the enforcement mode ─────────────────────────────────────────────────────

class _State:
    def __init__(self, mode):
        self.compliance_enforcement_mode = mode
        self.compliance_mode_updated_at = None
        self.compliance_mode_updated_by = None


class _DB:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1

    async def refresh(self, _o):
        return None


class _Emitter:
    def __init__(self):
        self.received = []

    async def emit(self, **kw):
        self.received.append(kw)


def _wire(monkeypatch, mode):
    state = _State(mode)

    async def _get(_db):
        return state
    em = _Emitter()
    monkeypatch.setattr(ca, "_get_singleton_state", _get)
    monkeypatch.setattr(ca, "get_event_emitter", lambda: em)
    return state, em


@pytest.mark.asyncio
async def test_a_mode_change_is_stored_with_its_author_and_lands_on_the_ledger(monkeypatch):
    state, em = _wire(monkeypatch, "dry_run")
    db = _DB()
    out = await ca.set_mode(ca.EnforcementModeWrite(mode="off", reason="tester lifecycle, restored after"), db=db,
                            admin=_Admin())
    assert out.mode == "off" and state.compliance_mode_updated_by == "admin@test.sandbox" and db.commits == 1
    assert [e["event_type"] for e in em.received] == ["ComplianceEnforcementModeChanged"]
    assert em.received[0]["data"]["previous_mode"] == "dry_run" and em.received[0]["data"]["new_mode"] == "off"


@pytest.mark.asyncio
async def test_asking_for_the_mode_it_already_has_writes_nothing(monkeypatch):
    state, em = _wire(monkeypatch, "dry_run")
    db = _DB()
    out = await ca.set_mode(ca.EnforcementModeWrite(mode="dry_run", reason="no change asked"), db=db, admin=_Admin())
    assert out.mode == "dry_run" and db.commits == 0 and em.received == [] and state.compliance_mode_updated_by is None


@pytest.mark.parametrize("body", [{"mode": "enforce", "reason": "valid reason"}, {"mode": "off", "reason": "why"}])
def test_a_mode_or_reason_the_route_refuses_never_reaches_the_handler(body):
    with pytest.raises(ValidationError):
        ca.EnforcementModeWrite(**body)


@pytest.mark.asyncio
async def test_effective_enforcement_needs_the_mode_and_both_switches(monkeypatch):
    for enforce, central, mode, want in [(True, True, "enforcing", True), (False, True, "enforcing", False),
                                         (True, False, "enforcing", False), (True, True, "dry_run", False)]:
        monkeypatch.setattr(ca.settings, "FEDERATION_ENFORCEMENT_ACTIVE", enforce, raising=False)
        monkeypatch.setattr(ca.settings, "IS_CENTRAL_REGISTRY", central, raising=False)
        assert ca._effective_enforcement(mode) is want, (enforce, central, mode)
