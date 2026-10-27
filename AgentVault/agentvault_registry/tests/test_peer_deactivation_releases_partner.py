"""A peer's deactivation releases the TEG partner its reactivation registered (agentvault2-5b, 2026-10-18).

The TEG partner rule (ledgergate3, fix/teg-partner-quarantine a9cad595) runs a cross-TEG leg only with a current
partner. A reactivation and a quarantine lift register the peer (reactor_helpers.register_peer_partner_on_teg:
teg-<safe name>), but crud_peer_registry.update_peer_registry_status emitted every PeerRegistryDeactivated with
teg_id None, and the PeerRegistryDeactivated reactor skips a null id: a deactivated peer stayed a current partner at
the TEG. Measured by agentvault2-56 on sbx-alpha 2026-10-18: the V0624 sweep's reactivate row added a fixture peer's
partner at 21:04:22Z, the deactivation at 21:08:51Z removed nothing.

What these tests pin, on the real status write and the real reactor (the database, the emitter and the TEG's HTTP
answers replaced):
- an admin or an owner deactivation names teg-<safe name>, the id the reactivation registers, and the reactor removes
  exactly that id;
- a second spelling of a peer that stays ACTIVE (a fan-out's upper-case copy, a hyphen) releases nothing: the TEG's
  remove-partner drops every entry naming the key, so it would cut the live peer;
- the lookup reads only ACTIVE rows other than the one deactivated;
- a lookup that fails still emits the event, with no id (the partner stays, as before);
- a reactivation's event names no partner to remove.
RED on d6aa283d (V0624): every deactivation emits teg_id None and no lookup runs.
"""
import asyncio
import types

import pytest

from agentvault_registry import event_emitter
from agentvault_registry.background_tasks import reactor_base
from agentvault_registry.background_tasks import reactor_peer_deactivated as rpd
from agentvault_registry.crud import crud_peer_registry
from agentvault_registry.routers import teg_integration as ti


class _DB:
    """The status write's session: commit and refresh do nothing; the partner lookup answers `active` (id, name)."""

    def __init__(self, active=(), fail=False):
        self.active = list(active)
        self.fail = fail
        self.statements = []

    async def commit(self):
        pass

    async def refresh(self, obj):
        pass

    async def execute(self, stmt, *a, **k):
        self.statements.append(stmt)
        if self.fail:
            raise RuntimeError("the database went away")
        return types.SimpleNamespace(all=lambda: list(self.active))


class _Emitter:
    def __init__(self):
        self.received = []

    async def emit(self, **kw):
        self.received.append(kw)


@pytest.fixture(autouse=True)
def reset_leader_keys():
    """Each case builds the reactor; its base refuses a leader_key already registered (tests/reactors' own reset)."""
    reactor_base._registered_leader_keys.clear()
    rpd._instance = None
    yield
    reactor_base._registered_leader_keys.clear()
    rpd._instance = None


@pytest.fixture
def emitter(monkeypatch):
    e = _Emitter()
    monkeypatch.setattr(event_emitter, "get_event_emitter", lambda: e)
    return e


def _peer(name, status="ACTIVE", peer_id=42):
    return types.SimpleNamespace(id=peer_id, name=name, status=status, trust_domain=f"{name.lower()}.example",
                                 deactivated_reason=None, deactivated_at=None,
                                 approved_at=None, approved_by_developer_id=None)


def _deactivate(db, peer, admin_id=1):
    asyncio.run(crud_peer_registry.update_peer_registry_status(db, peer, "INACTIVE", admin_id=admin_id))


def _registered_id(monkeypatch, name):
    """The partner id a reactivation registers for `name` (the real helper; only the TEG's answer replaced)."""
    posts = []

    class _Client:
        async def post(self, url, headers=None, json=None):
            posts.append(json)
            return types.SimpleNamespace(status_code=200, text="{}", json=lambda: {"status": "added"})
    monkeypatch.setenv("TEG_ADMIN_API_KEY", "peer-deactivation-test-key-not-a-secret")
    monkeypatch.setattr(ti, "_get_teg_client", lambda: _Client())

    async def _resolve(peer_name, db):
        return ("https://peer.example:8443", "crossteg-fund-cache:peer")
    monkeypatch.setattr(ti, "_resolve_peer_target_for_cross_teg_fund", _resolve)
    from agentvault_registry.background_tasks.reactor_helpers import register_peer_partner_on_teg
    asyncio.run(register_peer_partner_on_teg(None, name, source_label="test"))
    return posts[0]["teg_id"]


@pytest.mark.parametrize("name", ["lisbon", "Sandbox Beta"])
def test_a_deactivation_releases_the_partner_a_reactivation_registers(name, emitter, monkeypatch):
    _deactivate(_DB(active=[(7, "amsterdam")]), _peer(name))
    (event,) = emitter.received
    assert event["event_type"] == "PeerRegistryDeactivated"
    assert event["data"]["teg_id"] == _registered_id(monkeypatch, name)

    removed = []

    async def _remove(teg_id, *, source_label="?"):
        removed.append(teg_id)
        return {"status": "removed", "total_partners": 2}
    monkeypatch.setattr(rpd, "_remove_partner_on_teg", _remove)
    asyncio.run(rpd.PeerRegistryDeactivatedReactor().handle_event(event["data"]))
    assert removed == [event["data"]["teg_id"]]


def test_an_owner_deactivation_releases_it_too(emitter):
    _deactivate(_DB(), _peer("lisbon"), admin_id=None)
    (event,) = emitter.received
    assert event["data"]["reason"] == "owner_deactivated"
    assert event["data"]["teg_id"] == "teg-lisbon"


@pytest.mark.parametrize("live", ["lisbon", "Lis-bon"])
def test_a_second_spelling_of_a_live_peer_releases_nothing(live, emitter):
    _deactivate(_DB(active=[(42, live)]), _peer("LISBON", peer_id=43))
    (event,) = emitter.received
    assert event["event_type"] == "PeerRegistryDeactivated"
    assert event["data"]["teg_id"] is None


def test_an_unrelated_live_peer_does_not_hold_the_partner(emitter):   # control: the key is compared, not a prefix
    _deactivate(_DB(active=[(9, "lisbon-2"), (10, "lisbonne")]), _peer("lisbon"))
    assert emitter.received[0]["data"]["teg_id"] == "teg-lisbon"


def test_the_lookup_reads_active_rows_other_than_the_one_deactivated(emitter):
    db = _DB()
    _deactivate(db, _peer("lisbon"))
    (stmt,) = db.statements
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "peer_registries.status = 'ACTIVE'" in sql
    assert "peer_registries.id != 42" in sql


def test_a_failed_lookup_still_emits_and_keeps_the_partner(emitter):
    _deactivate(_DB(fail=True), _peer("lisbon"))
    (event,) = emitter.received
    assert event["event_type"] == "PeerRegistryDeactivated"
    assert event["data"]["teg_id"] is None


def test_a_reactivation_names_no_partner_to_remove(emitter):
    db = _DB()
    asyncio.run(crud_peer_registry.update_peer_registry_status(db, _peer("lisbon", status="INACTIVE"), "ACTIVE",
                                                               admin_id=1))
    (event,) = emitter.received
    assert event["event_type"] == "PeerRegistryReactivated"
    assert event["data"]["teg_id"] is None
    assert db.statements == []
