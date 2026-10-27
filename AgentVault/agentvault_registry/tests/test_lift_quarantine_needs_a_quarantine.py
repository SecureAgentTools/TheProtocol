"""§MCPTEST30 V0638 (agentvault2-aa, 2026-10-24): only a quarantine is lifted.

services/federation_compliance_monitor.lift_quarantine checked only that the peer had a compliance record and was not
blacklisted: on a FEDERATED peer it rewrote the admitted policy hash with the caller's value and emitted a
RegistryQuarantineLifted for a quarantine that never was. The API tester's probe did exactly that to sbx-alpha's operator
peer on 2026-10-18 15:27:25Z (new_policy_hash "a"*64, the ledger's one RegistryQuarantineLifted for peer 1), and every
compliance poll since read a drift (363 drift events by 10-24). Now a peer that is not quarantined is refused, 409
"not_quarantined: ...", nothing written or emitted; a quarantined peer lifts as before. The control: on V0637's monitor
this module cannot collect (there is no NotQuarantined), and V0637's lift_quarantine run directly on a federated peer
rewrites its hash to the caller's ("aaaaaaaa..."), commits, emits RegistryQuarantineLifted and tries to re-register the
peer as a TEG partner.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from agentvault_registry.routers import enforcement_admin
from agentvault_registry.services import federation_compliance_monitor as fcm

LIVE = "b" * 64


class _Db:
    def __init__(self, row):
        self.row, self.commits = row, 0

    async def execute(self, stmt):
        return SimpleNamespace(scalar_one_or_none=lambda: self.row)

    async def commit(self):
        self.commits += 1


class _Emitter:
    def __init__(self):
        self.received = []

    async def emit(self, **kw):
        self.received.append(kw)
        return True


def _row(status):
    return SimpleNamespace(federation_status=status, policy_hash=LIVE, quarantine_reason="r" if status == "quarantined" else None,
                           quarantine_since=None, quarantine_grace_expires=None)


def _lift(monkeypatch, status):
    emitter = _Emitter()
    monkeypatch.setattr(fcm, "get_event_emitter", lambda: emitter)
    db = _Db(_row(status))
    monitor = fcm.get_federation_compliance_monitor()
    asyncio.run(monitor.lift_quarantine(db, 1, "a" * 64, "admin@example.test"))
    return db, emitter


def test_a_federated_peer_has_no_quarantine_to_lift(monkeypatch):
    with pytest.raises(fcm.NotQuarantined) as e:
        _lift(monkeypatch, "federated")
    assert str(e.value).startswith("not_quarantined: peer 1 is federated")


def test_nothing_is_written_or_emitted_for_it(monkeypatch):
    emitter = _Emitter()
    monkeypatch.setattr(fcm, "get_event_emitter", lambda: emitter)
    db = _Db(_row("federated"))
    with pytest.raises(fcm.NotQuarantined):
        asyncio.run(fcm.get_federation_compliance_monitor().lift_quarantine(db, 1, "a" * 64, "admin@example.test"))
    assert db.row.policy_hash == LIVE and db.row.federation_status == "federated"
    assert db.commits == 0 and emitter.received == []


def test_a_quarantined_peer_lifts_as_before(monkeypatch):
    db, emitter = _lift(monkeypatch, "quarantined")
    assert db.row.federation_status == "federated" and db.row.policy_hash == "a" * 64 and db.commits == 1
    assert [e["event_type"] for e in emitter.received] == ["RegistryQuarantineLifted"]


def test_a_blacklisted_peer_is_still_refused_as_before(monkeypatch):
    with pytest.raises(ValueError) as e:
        _lift(monkeypatch, "blacklisted")
    assert not isinstance(e.value, fcm.NotQuarantined) and "blacklisted" in str(e.value)


@pytest.mark.parametrize("raised, code", [(fcm.NotQuarantined("not_quarantined: peer 1 is federated"), 409),
                                          (ValueError("No compliance record for peer_id=1"), 400)])
def test_the_route_answers_409_for_nothing_to_lift_and_400_otherwise(monkeypatch, raised, code):
    class _Monitor:
        async def lift_quarantine(self, **kw):
            raise raised
    monkeypatch.setattr(enforcement_admin, "get_federation_compliance_monitor", lambda: _Monitor())
    req = enforcement_admin.RegistryLiftQuarantineRequest(new_policy_hash="a" * 64)
    with pytest.raises(HTTPException) as e:
        asyncio.run(enforcement_admin.lift_registry_quarantine(1, req, db=None, admin=SimpleNamespace(email="a@x.test")))
    assert e.value.status_code == code and str(e.value.detail) == str(raised)
