"""The cross-TEG partner rule (2026-10-17): this TEG takes part in a cross-TEG leg only with a CURRENT partner.

A registry that quarantines a peer (or suspends, revokes or deletes its licence, or deactivates it) removes it from its
own TEG's partner list, and that list was read by nothing a leg runs: a removed operator's TEG still prepared and
committed transfers into this frame (the commit credits what the prepare named), the removal named teg-<name> while the
registry had added teg-layer-<name> (so it answered not_found), it reached only the worker that served it, and the next
transfer toward the peer added it back through the address hint. Now a leg a peer calls is refused before anything moves
unless the peer its verified identity names is a current partner, a transfer is refused before the lock unless its
target is one, and only add-partner adds one.

The real router (api/cross_teg_router.py) through FastAPI; the coordinator, the client factory, the sessions and Redis
are in-memory stand-ins, so nothing here needs a database (tests/test_cross_teg_partner_legs.py runs the money on a
real Postgres). The caller is the identity the frame's terminator verified, injected where the router reads it.

RED control: against dad136e9's TEG source (its router and partner cache; it has no core/cross_teg/partner_rule.py)
21 of the 27 fail: the router tests on their assertions (the removed or never-added peer is served, the transfer is
coordinated, the hint adds a partner, the removal answers not_found, the other worker keeps the peer, the lost list is
not written back) and the rule's own tests at their import; the 6 controls pass on both.
"""
from __future__ import annotations

import ast
import asyncio
import json
import pathlib
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import teg_core_service.redis_client as rc
from teg_core_service.api import auth_enhanced as ae
from teg_core_service.api import cross_teg_router as r
from teg_core_service.core.cross_teg import partner_cache as pc
from teg_core_service.core.cross_teg.messages import CrossTEGTransferResponse, TransferStatus

SRC = pathlib.Path(r.__file__).resolve().parents[1]
OWN = "eu.test"
PEER_FRAME = "asia.test"
FRAME_TEG = f"spiffe://{OWN}/service/teg-layer"
FRAME_REGISTRY = f"spiffe://{OWN}/service/eu-registry"
AMSTERDAM = f"spiffe://{OWN}/operator/amsterdam/svid-writer"
AMSTERDAM_REGISTRY = f"spiffe://{OWN}/operator/amsterdam/registry"
LISBON = f"spiffe://{OWN}/operator/lisbon/svid-writer"
ASIA_TEG = f"spiffe://{PEER_FRAME}/service/teg-layer"
HASH = "teg:partners"
META = "#partner-list"
REFUSED = "cross_teg_partner_refused"


# ------------------------------------------------------------------------------------------------ the stand-ins
class FakeRedis:
    """The commands the partner store, the blocklist and the inbound bound use, on dicts (an empty hash is dropped, as
    Redis drops it)."""

    def __init__(self):
        self.h, self.s, self.kv = {}, {}, {}

    async def ping(self):
        return True

    async def hset(self, name, key=None, value=None, mapping=None):
        d = self.h.setdefault(name, {})
        items = dict(mapping or {})
        if key is not None:
            items[key] = value
        n = sum(1 for k in items if k not in d)
        d.update(items)
        return n

    async def hget(self, name, key):
        return self.h.get(name, {}).get(key)

    async def hgetall(self, name):
        return dict(self.h.get(name, {}))

    async def hdel(self, name, *keys):
        d = self.h.get(name, {})
        n = 0
        for k in keys:
            if k in d:
                del d[k]
                n += 1
        if name in self.h and not self.h[name]:
            del self.h[name]
        return n

    async def publish(self, channel, message):
        return 0

    def pipeline(self, transaction=True):
        return _FakePipe(self)

    async def sismember(self, key, member):
        return member in self.s.get(key, set())

    async def incrbyfloat(self, key, amount):
        self.kv[key] = self.kv.get(key, 0.0) + amount
        return self.kv[key]

    async def expire(self, key, seconds):
        return True


class _FakePipe:
    def __init__(self, redis):
        self.redis, self.ops = redis, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def hdel(self, *args):
        self.ops.append(("hdel", args, {}))
        return self

    def hset(self, *args, **kwargs):
        self.ops.append(("hset", args, kwargs))
        return self

    async def execute(self):
        return [await getattr(self.redis, name)(*args, **kwargs) for name, args, kwargs in self.ops]


class FakeCoordinator:
    """Records what reached the 2PC: nothing a refused leg sends may arrive here."""

    def __init__(self):
        self.messages, self.transfers = [], []
        self.active_coordinations = {}

    async def handle_incoming_message(self, kind, message):
        self.messages.append((kind, message["transfer_id"]))

    async def coordinate_transfer(self, request):
        self.transfers.append((request.transfer_id, request.target_teg_id))
        return CrossTEGTransferResponse(transfer_id=request.transfer_id, correlation_id=request.correlation_id,
                                        status=TransferStatus.COMPLETED, processing_teg_id=r.settings.teg_id,
                                        success=True, transaction_hash=request.transfer_id)


class FakeFactory:
    def __init__(self):
        self.closed = []

    def get_client(self, teg_id, url):
        return None

    async def remove_client(self, teg_id):
        self.closed.append(teg_id)
        return True


class Reached(Exception):
    """A leg the rule admitted got as far as its database session."""


class _Sessions:
    def __init__(self):
        self.opened = 0

    def __call__(self, *a, **k):
        self.opened += 1
        raise Reached("the leg opened a database session")

    def _get_session(self):
        return self()


AGENT = "did:theprotocol:partner-rule-sender"


@pytest.fixture(autouse=True)
def world(monkeypatch):
    fake = FakeRedis()

    async def _get():
        return fake

    monkeypatch.setattr(rc, "get_redis", _get)
    monkeypatch.setattr(pc, "get_redis", _get)
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", OWN)
    monkeypatch.setenv("TEG_OWN_SPIFFE_ID", FRAME_TEG)
    monkeypatch.setenv("TRUSTED_SPIFFE_DOMAINS", f"{OWN},{PEER_FRAME}")
    monkeypatch.setenv("CROSS_TEG_PEER_INBOUND_LIMIT_MODE", "off")
    for name in ("TEG_MTLS_REQUIRED", "CROSS_TEG_PARTNER_RULE_MODE", "CROSS_TEG_LOCAL_LEG_SOURCES", "REDIS_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(r, "_runtime_partners", [])
    monkeypatch.setattr(r.settings, "partner_tegs", "[]")
    coord = FakeCoordinator()
    monkeypatch.setattr(r, "transaction_coordinator", coord)
    factory = FakeFactory()
    monkeypatch.setattr(r, "teg_client_factory", factory)
    sessions = _Sessions()
    monkeypatch.setattr(r, "transfer_protocol", sessions)
    import teg_core_service.database.db_session as dbs
    monkeypatch.setattr(dbs, "AsyncSessionLocal", sessions)
    caller = {"id": None}
    monkeypatch.setattr(r, "_extract_spiffe_from_header", lambda req: caller["id"])
    app = FastAPI()
    app.include_router(r.router)
    app.dependency_overrides[ae.verify_admin_key] = lambda: True
    app.dependency_overrides[r.get_current_agent] = lambda: AGENT
    client = TestClient(app)
    yield {"redis": fake, "coord": coord, "factory": factory, "sessions": sessions, "caller": caller, "client": client}


def _as(w, spiffe_id):
    w["caller"]["id"] = spiffe_id


def _add(w, teg_id, url, registry_id=""):
    res = w["client"].post("/api/v1/cross-teg/config/add-partner",
                           json={"teg_id": teg_id, "registry_id": registry_id, "url": url})
    assert res.status_code == 200, res.text
    return res.json()


def _remove(w, teg_id):
    return w["client"].post("/api/v1/cross-teg/config/remove-partner", json={"teg_id": teg_id})


def _prepare(w, tid, amount="5", source_teg="teg-amsterdam"):
    body = {"source_teg_id": source_teg, "source_agent_id": "did:theprotocol:x", "target_agent_id": "did:theprotocol:y",
            "amount": amount, "currency": "ECU", "correlation_id": tid,
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=4)).isoformat()}
    return w["client"].post(f"/api/v1/cross-teg/prepare/{tid}", json=body)


def _commit(w, tid):
    return w["client"].post(f"/api/v1/cross-teg/commit/{tid}")


def _abort(w, tid):
    return w["client"].post(f"/api/v1/cross-teg/abort/{tid}", json={"reason": "test"})


def _refused(res):
    return res.status_code == 403 and REFUSED in res.text


def _transfer(w, target, url="https://elsewhere.test:8443"):
    now = datetime.now(timezone.utc)
    body = {"transfer_id": f"t-{target}", "correlation_id": f"c-{target}", "source_teg_id": r.settings.teg_id,
            "source_registry_id": "registry-eu", "source_agent_id": AGENT, "target_teg_id": target,
            "target_registry_id": "registry-x", "target_teg_url": url, "target_agent_id": "did:theprotocol:far",
            "amount": "3", "authorization_token": "t", "expires_at": (now + timedelta(seconds=120)).isoformat(),
            "idempotency_key": f"k-{target}"}
    return w["client"].post("/api/v1/cross-teg/transfer", json=body)


# ------------------------------------------------------------------------------------------------ the 2PC legs a peer calls
def test_a_partner_operator_prepares_and_commits(world):
    """Control: the registry added the operator (as it names it, teg-layer-<name>); its TEG's legs are served."""
    _add(world, "teg-layer-amsterdam", "https://amsterdam.op.test:8443", "registry-amsterdam")
    _as(world, AMSTERDAM)
    assert _prepare(world, "t-ok").status_code == 200
    assert _commit(world, "t-ok").status_code == 200
    assert world["coord"].messages == [("prepare_request", "t-ok"), ("commit_request", "t-ok")]


def test_an_operator_that_is_no_partner_moves_nothing(world):
    _add(world, "teg-layer-lisbon", "https://lisbon.op.test:8443")
    _as(world, AMSTERDAM)
    for res in (_prepare(world, "t-1"), _commit(world, "t-1"), _abort(world, "t-1")):
        assert _refused(res), (res.status_code, res.text[:200])
    assert world["coord"].messages == [], "a refused leg reached the coordinator"


def test_the_claimed_source_teg_never_decides(world):
    """The body names a partner's TEG id; the verified identity is another operator: refused."""
    _add(world, "teg-layer-lisbon", "https://lisbon.op.test:8443")
    _as(world, AMSTERDAM)
    assert _refused(_prepare(world, "t-claim", source_teg="teg-lisbon"))
    assert world["coord"].messages == []


def test_the_reactor_removal_stops_the_peer(world):
    """The registry added teg-layer-amsterdam; its reactors remove teg-amsterdam. The removal names the same peer, and a
    transfer prepared before it is not committed after it."""
    _add(world, "teg-layer-amsterdam", "https://amsterdam.op.test:8443", "registry-amsterdam")
    _as(world, AMSTERDAM)
    assert _prepare(world, "t-before").status_code == 200
    res = _remove(world, "teg-amsterdam")
    assert res.status_code == 200 and res.json()["status"] == "removed", res.text
    assert "teg-layer-amsterdam" in res.json()["removed"]
    assert r._runtime_partners == []
    assert set(world["redis"].h.get(HASH, {})) == {META}, "the shared list still names the peer"
    assert _refused(_commit(world, "t-before")), "a removed peer's prepared transfer was committed"
    assert _refused(_prepare(world, "t-after"))
    assert world["coord"].messages == [("prepare_request", "t-before")]


def test_a_removal_on_another_worker_stops_this_one(world):
    """This worker still holds the peer; the shared list (as the worker that served the removal left it) does not."""
    _add(world, "teg-layer-amsterdam", "https://amsterdam.op.test:8443")
    world["redis"].h[HASH].pop("teg-layer-amsterdam")
    world["redis"].h[HASH][META] = json.dumps({"v": 1})
    assert [p["teg_id"] for p in r._runtime_partners] == ["teg-layer-amsterdam"]
    _as(world, AMSTERDAM)
    assert _refused(_prepare(world, "t-stale"))
    assert world["coord"].messages == []


def test_add_partner_brings_the_peer_back(world):
    """The explicit path still adds (the registry's own authority, for a peer it has not quarantined)."""
    _add(world, "teg-layer-amsterdam", "https://amsterdam.op.test:8443")
    assert _remove(world, "teg-amsterdam").json()["status"] == "removed"
    _as(world, AMSTERDAM)
    assert _refused(_prepare(world, "t-x"))
    _add(world, "teg-layer-amsterdam", "https://amsterdam.op.test:8443")
    assert _prepare(world, "t-y").status_code == 200


def test_the_frame_is_never_a_peer_and_a_sibling_operator_is(world, monkeypatch):
    """On an operator TEG: the parent frame (the trust root that issued the operator's identity) and the operator's own
    identities are not peers; another operator of the same frame is one."""
    monkeypatch.setenv("TEG_OWN_SPIFFE_ID", AMSTERDAM)
    _as(world, FRAME_TEG)
    assert _prepare(world, "t-frame").status_code == 200
    _as(world, AMSTERDAM_REGISTRY)
    assert _commit(world, "t-frame").status_code == 200
    _as(world, LISBON)
    assert _refused(_prepare(world, "t-sibling"))
    assert world["coord"].messages == [("prepare_request", "t-frame"), ("commit_request", "t-frame")]


def test_a_foreign_frame_is_a_partner_by_its_own_address(world):
    _as(world, ASIA_TEG)
    assert _refused(_prepare(world, "t-asia-0"))
    _add(world, "teg-layer-asia", "https://asia.test:8443", "registry-asia")
    assert _prepare(world, "t-asia-1").status_code == 200
    res = _remove(world, "teg-asia")            # the compliance monitor's teg-<safe name> for a peer named ASIA
    assert res.json()["status"] == "removed", res.text
    assert _refused(_prepare(world, "t-asia-2"))
    assert world["coord"].messages == [("prepare_request", "t-asia-1")]


def test_the_treasury_fund_drain_is_not_asked(world):
    """Control, and the rule's one deliberate exception: a purge drains a revoked operator (no longer a partner) into
    its frame's treasury through /treasury-fund, whose configured sources decide it."""

    class _Db:
        def query(self, *a, **k):
            raise Reached("the treasury-fund leg read its database")

    def _db():
        yield _Db()

    world["client"].app.dependency_overrides[r.get_db] = _db
    _as(world, AMSTERDAM)
    with pytest.raises(Reached):
        world["client"].post("/api/v1/cross-teg/treasury-fund",
                             json={"amount": "1", "source_teg_id": "teg-amsterdam", "correlation_id": "td-1"})


def test_a_static_partner_counts_and_stays(world, monkeypatch):
    monkeypatch.setattr(r.settings, "partner_tegs", json.dumps(
        [{"teg_id": "teg-layer-amsterdam", "registry_id": "registry-amsterdam", "url": "https://a.test:8443"}]))
    _as(world, AMSTERDAM)
    assert _prepare(world, "t-static").status_code == 200
    res = _remove(world, "teg-layer-amsterdam")
    assert res.json()["status"] == "static_immutable", res.text


# ------------------------------------------------------------------------------------------------ the legs local by design
LOCAL = {
    "lock-async": {"transfer_id": "l1", "sender_did": "did:theprotocol:a", "amount": "1"},
    "credit-async": {"transfer_id": "l2", "sender_did": "did:theprotocol:a", "receiver_did": "did:theprotocol:b",
                     "amount": "1"},
    "credit-async-bulk": {"transfers": [{"transfer_id": "l3", "sender_did": "did:theprotocol:a",
                                         "receiver_did": "did:theprotocol:b", "amount": "1"}]},
    "refund-async": {"transfer_id": "l4", "sender_did": "did:theprotocol:a", "amount": "1"},
    "reverse-async": {"transfer_id": "l5", "receiver_did": "did:theprotocol:b", "amount": "1"},
}


def _local_leg(w, route):
    try:
        res = w["client"].post(f"/api/v1/cross-teg/{route}", json=LOCAL[route])
    except Reached:
        return "reached"
    return res


def test_an_operator_admitted_to_the_frames_async_legs_must_be_a_partner(world):
    """The async legs admit this TEG's own trust domain, which holds its operators: one that is no partner is refused
    before any session opens, and /accept before its body is read."""
    _as(world, LISBON)
    for route in LOCAL:
        res = _local_leg(world, route)
        assert res != "reached" and _refused(res), (route, res if res == "reached" else res.text[:200])
    res = world["client"].post("/api/v1/cross-teg/accept", json={})
    assert _refused(res), (res.status_code, res.text[:200])
    assert world["sessions"].opened == 0


def test_the_own_frame_and_a_partner_reach_the_async_legs(world):
    """Control: the frame's own registry is not a peer; an operator that is a partner passes the rule."""
    _as(world, FRAME_REGISTRY)
    for route in LOCAL:
        assert _local_leg(world, route) == "reached", route
    _add(world, "teg-layer-lisbon", "https://lisbon.op.test:8443")
    _as(world, LISBON)
    assert _local_leg(world, "lock-async") == "reached"


# ------------------------------------------------------------------------------------------------ a transfer this TEG starts
def test_a_transfer_toward_no_partner_is_refused_before_the_lock(world):
    _as(world, FRAME_REGISTRY)
    res = _transfer(world, "teg-layer-elsewhere")
    assert res.status_code == 400, (res.status_code, res.text[:200])
    detail = res.json()["detail"]
    assert detail.startswith(f"This TEG ({r.settings.teg_id})") and REFUSED in detail and "nothing moved" in detail
    assert world["coord"].transfers == [], "the coordinator locked funds for a transfer toward no partner"
    assert r._runtime_partners == [] and HASH not in world["redis"].h, "the address in the payload added a partner"


def test_a_transfer_toward_a_partner_is_coordinated(world):
    """Control: the registry adds the target first (as its 2PC and FX legs do), then the transfer runs."""
    _add(world, "teg-layer-amsterdam", "https://amsterdam.op.test:8443")
    _as(world, FRAME_REGISTRY)
    assert _transfer(world, "teg-layer-amsterdam").status_code == 200
    assert world["coord"].transfers == [("t-teg-layer-amsterdam", "teg-layer-amsterdam")]


def test_a_removed_target_is_refused(world):
    _add(world, "teg-layer-amsterdam", "https://amsterdam.op.test:8443")
    _remove(world, "teg-amsterdam")
    _as(world, FRAME_REGISTRY)
    assert _transfer(world, "teg-layer-amsterdam").status_code == 400
    assert world["coord"].transfers == []


# ------------------------------------------------------------------------------------------------ no partner from a leg
def test_an_address_hint_adds_no_partner_and_changes_none(world):
    assert r.resolve_partner_url("teg-layer-elsewhere", "https://elsewhere.test:8443") == "https://elsewhere.test:8443"
    assert r._runtime_partners == [], "a hint added a partner"
    _add(world, "teg-layer-amsterdam", "https://amsterdam.op.test:8443")
    before = json.dumps(world["redis"].h[HASH], sort_keys=True)
    assert r.resolve_partner_url("teg-layer-amsterdam", "https://moved.test:8443") == "https://moved.test:8443"
    assert r._runtime_partners[0]["url"] == "https://amsterdam.op.test:8443", "a hint rewrote a stored address"
    assert json.dumps(world["redis"].h[HASH], sort_keys=True) == before
    assert r.resolve_partner_url("teg-layer-amsterdam") == "https://amsterdam.op.test:8443"
    with pytest.raises(KeyError):
        r.resolve_partner_url("teg-layer-elsewhere")


# ------------------------------------------------------------------------------------------------ the shared list
def test_the_refresh_follows_removals(world):
    world["redis"].h[HASH] = {
        "teg-layer-lisbon": json.dumps({"teg_id": "teg-layer-lisbon", "url": "https://lisbon.op.test:8443"}),
        META: json.dumps({"v": 1}),
    }
    r._runtime_partners.extend([{"teg_id": "teg-layer-amsterdam", "url": "https://amsterdam.op.test:8443"},
                                {"teg_id": "teg-layer-lisbon", "url": "https://lisbon.op.test:8443"}])
    asyncio.run(r.refresh_partners_from_redis())
    assert [p["teg_id"] for p in r._runtime_partners] == ["teg-layer-lisbon"], r._runtime_partners
    assert world["factory"].closed == ["teg-layer-amsterdam"]


def test_a_lost_list_is_written_back_and_never_emptied(world):
    """A frame Redis that restarted holds no list: a worker that holds partners writes them back; a worker that holds
    none writes nothing (an empty list would read as every partner removed)."""
    asyncio.run(r.refresh_partners_from_redis())
    assert HASH not in world["redis"].h, "an empty worker wrote an empty list"
    r._runtime_partners.append({"teg_id": "teg-layer-amsterdam", "url": "https://amsterdam.op.test:8443"})
    asyncio.run(r.refresh_partners_from_redis())
    assert set(world["redis"].h.get(HASH, {})) == {"teg-layer-amsterdam", META}


def test_a_list_written_before_the_rule_is_taken_whole_and_marked(world):
    world["redis"].h[HASH] = {"teg-layer-amsterdam": json.dumps({"teg_id": "teg-layer-amsterdam",
                                                                 "url": "https://amsterdam.op.test:8443"})}
    asyncio.run(r.refresh_partners_from_redis(force_full=True))
    assert [p["teg_id"] for p in r._runtime_partners] == ["teg-layer-amsterdam"]
    assert META in world["redis"].h[HASH]
    _as(world, AMSTERDAM)
    assert _prepare(world, "t-migrated").status_code == 200


def test_a_removal_the_shared_list_did_not_take_answers_503(world, monkeypatch):
    _add(world, "teg-layer-amsterdam", "https://amsterdam.op.test:8443")

    async def _none():
        return None

    monkeypatch.setattr(pc, "get_redis", _none)
    monkeypatch.setenv("REDIS_URL", "redis://example.invalid:6379/0")
    res = _remove(world, "teg-amsterdam")
    assert res.status_code == 503 and "partner_list_unreachable" in res.text, (res.status_code, res.text[:200])
    assert r._runtime_partners == [], "this worker kept the peer"


# ------------------------------------------------------------------------------------------------ the switch
def test_shadow_serves_and_off_asks_nothing(world, monkeypatch):
    _as(world, AMSTERDAM)
    monkeypatch.setenv("CROSS_TEG_PARTNER_RULE_MODE", "shadow")
    assert _prepare(world, "t-shadow").status_code == 200
    monkeypatch.setenv("CROSS_TEG_PARTNER_RULE_MODE", "off")
    assert _prepare(world, "t-off").status_code == 200
    _as(world, FRAME_REGISTRY)
    assert _transfer(world, "teg-layer-nowhere").status_code == 200


# ------------------------------------------------------------------------------------------------ the rule itself
def test_peer_key_makes_the_three_names_one():
    from teg_core_service.core.cross_teg import partner_rule as pr
    assert pr.peer_key("teg-layer-amsterdam") == pr.peer_key("teg-amsterdam") == pr.peer_key("registry-amsterdam") \
        == pr.name_key("amsterdam") == "amsterdam"
    assert pr.peer_key("teg-layer-sandbox-beta") == pr.peer_key("teg-sandboxbeta") == "sandboxbeta"
    assert pr.peer_key("teg-layer-op-tokyo") == pr.name_key("op-tokyo") == "optokyo"
    assert pr.peer_key("teg-layer") == "layer" and pr.peer_key("") == "" and pr.peer_key(None) == ""


def test_peer_of_reads_the_verified_identity():
    from teg_core_service.core.cross_teg import partner_rule as pr
    frame = dict(own_trust_domain=OWN, own_operator=None)
    assert pr.peer_of(FRAME_REGISTRY, **frame) is None
    assert pr.peer_of(AMSTERDAM, **frame) == {"kind": "operator", "trust_domain": OWN, "name": "amsterdam"}
    assert pr.peer_of(ASIA_TEG, **frame) == {"kind": "frame", "trust_domain": PEER_FRAME, "name": ""}
    assert pr.peer_of("shared-key", **frame) is None and pr.peer_of(None, **frame) is None
    op = dict(own_trust_domain=OWN, own_operator="amsterdam")
    assert pr.peer_of(AMSTERDAM_REGISTRY, **op) is None and pr.peer_of(FRAME_TEG, **op) is None
    assert pr.peer_of(LISBON, **op)["name"] == "lisbon"
    assert pr.peer_of(f"spiffe://{PEER_FRAME}/operator/amsterdam/x", **op)["kind"] == "operator", \
        "a foreign operator of the same name is not this TEG"


def test_a_frame_partner_is_named_by_its_address_only():
    from teg_core_service.core.cross_teg import partner_rule as pr
    asia = {"kind": "frame", "trust_domain": PEER_FRAME, "name": ""}
    assert pr.names_peer({"teg_id": "teg-layer-asia", "url": "https://asia.test:8443"}, asia)
    assert not pr.names_peer({"teg_id": "teg-layer-asia", "url": "https://asia-nginx-federation:8443"}, asia)
    assert not pr.names_peer({"teg_id": "teg-layer-asia", "url": "not a url"}, asia)
    op = {"kind": "operator", "trust_domain": OWN, "name": "amsterdam"}
    assert pr.names_peer({"teg_id": "teg-x", "registry_id": "registry-amsterdam", "url": ""}, op)
    assert not pr.names_peer({"teg_id": "teg-layer-amsterdamx", "url": ""}, op)


def test_an_unknown_mode_serves_as_enforce(monkeypatch):
    from teg_core_service.core.cross_teg import partner_rule as pr
    monkeypatch.setenv("CROSS_TEG_PARTNER_RULE_MODE", "sometimes")
    assert pr.mode() == "enforce"
    monkeypatch.delenv("CROSS_TEG_PARTNER_RULE_MODE")
    assert pr.mode() == "enforce"


# ------------------------------------------------------------------------------------------------ the wiring, by source
def _fn(tree, name):
    return next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def _awaited(fn, name):
    return [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Await) and isinstance(n.value, ast.Call)
            and getattr(n.value.func, "id", None) == name]


def test_every_leg_asks_the_rule_before_it_runs():
    tree = ast.parse((SRC / "api" / "cross_teg_router.py").read_text())
    for name in ("prepare_transfer", "commit_transfer", "abort_transfer", "lock_async", "credit_async",
                 "credit_async_bulk", "refund_async", "reverse_async"):
        assert _awaited(_fn(tree, name), "_require_current_partner"), name
    dep = _fn(tree, "_local_caller_dependency")
    assert _awaited(dep, "_require_current_partner"), "the /accept dependency does not ask the rule"
    start = _fn(tree, "initiate_cross_teg_transfer")
    ask = _awaited(start, "_require_target_partner")
    lock = [n.lineno for n in ast.walk(start) if isinstance(n, ast.Attribute) and n.attr == "coordinate_transfer"]
    assert ask and lock and min(ask) < min(lock), "the transfer is coordinated before the rule is asked"
    # the treasury-fund drain is decided by its configured sources, deliberately not by this rule
    assert not _awaited(_fn(tree, "receive_cross_teg_treasury_fund"), "_require_current_partner")


def test_resolving_an_address_writes_no_partner():
    tree = ast.parse((SRC / "api" / "cross_teg_router.py").read_text())
    fn = _fn(tree, "resolve_partner_url")
    writes = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr in ("append", "insert", "extend")]
    stores = [n for n in ast.walk(fn) if isinstance(n, (ast.Assign, ast.AugAssign))
              and any(isinstance(t, ast.Subscript) for t in (getattr(n, "targets", None) or [n.target]))]
    calls = {getattr(n.func, "id", None) for n in ast.walk(fn) if isinstance(n, ast.Call)}
    assert not writes and not stores, "resolve_partner_url writes the partner list"
    assert not calls & {"set_partner_in_redis", "mark_partner_list", "_mirror_partner_to_redis_async"}
