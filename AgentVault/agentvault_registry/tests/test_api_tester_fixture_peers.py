"""§SUITES1018 batch 6c (2026-10-18): the api-tester's admin peer status rows act only on its own fixture peer.

Measured on sbx-alpha in the V0624 sweep (20:57Z): the approve row approved the sweep's pending fixture and retired it
at once (batch 4), and one second later the reactivate row made the NEWEST inactive fixture ACTIVE again and nothing
retired it (agentvault2-5b's watcher caught it in sbx-alpha's console manifest; retired by hand at 21:08:51Z). The
reactivate and reject rows sat outside the fixture resolver and took whatever `peer_id` an earlier row had left in
DYNAMIC_VALUES (the dispute rows store the frame's REAL peer there), and base classed reactivate a harmless recovery
verb, so it always ran. Now each of the four rows takes a fixture of the sweep's own in the state it needs, made ready
through the frame's own rails, base withholds all four unless the router marked that one concrete path, and the
approve, reactivate and deactivate rows' fixture is retired once measured. No fixture: the row is NOT MEASURED. The
slash settings row joins them (it wrote whatever peer `peer_id` named), and every slash update now records its own
event. The same sweep blacklisted and quarantined sbx-alpha's real peer frame through the enforcement contracts, which
run before any destructive check: a peer's federation standing, the compliance kill switch and the emission policy are
NOT MEASURED before any contract runs.

RED on a8c031f5 (batch 6b): every test_red_* fails there. The test_control_* ones pin what must not change; those whose
function is new (the resolver, the pool receiver, the re-grant, the contract skip) fail there for that reason alone.
"""
from __future__ import annotations

import asyncio
import json
from urllib.parse import parse_qs

import httpx
import pytest

from agentvault_registry.api_tests import base as B

ROWS = {
    "approve": "/admin/federation/peers/{peer_id}/approve",
    "reject": "/admin/federation/peers/{peer_id}/reject",
    "reactivate": "/admin/federation/peers/{peer_id}/reactivate",
    "deactivate": "/admin/federation/peers/{peer_id}/deactivate",
}


def _router(monkeypatch, values=None):
    from agentvault_registry.routers import admin_api_test as R
    monkeypatch.setattr(R, "DYNAMIC_VALUES", dict(values or {}))
    monkeypatch.setattr(R, "API_TEST_TARGET_URL", "http://registry-test:8000")
    return R


def _fixture(pid, status):
    return {"id": pid, "name": f"Test Federation Peer 17923{pid:08d}",
            "base_url": f"https://test-peer-17923{pid:08d}.theprotocol.test", "status": status}


REAL_ACTIVE = {"id": 2, "name": "Sandbox Beta", "base_url": "https://sbx-beta.theprotocol.cloud", "status": "ACTIVE"}
REAL_RETIRED = {"id": 7, "name": "sandboxgamma", "base_url": "https://sandboxgamma.op.theprotocol.cloud",
                "status": "INACTIVE"}


class _Frame:
    """The four admin peer rails and the peer list, over an in-memory peer table, recording every request."""

    def __init__(self, monkeypatch, peers, list_status=200):
        self.peers = {p["id"]: dict(p) for p in peers}
        self.list_status = list_status
        self.seen = []
        real = httpx.AsyncClient

        def _client(*a, **k):
            k["transport"] = httpx.MockTransport(self._handle)
            return real(*a, **k)
        monkeypatch.setattr(httpx, "AsyncClient", _client)

    @property
    def writes(self):
        return [(r.method, r.url.path) for r in self.seen if r.method != "GET"]

    def _handle(self, request):
        self.seen.append(request)
        path = request.url.path
        q = parse_qs(request.url.query.decode() if isinstance(request.url.query, bytes) else str(request.url.query))
        if request.method == "GET" and path == "/api/v1/admin/federation/peers/all":
            if self.list_status != 200:
                return httpx.Response(self.list_status, json={"detail": "boom"})
            want = (q.get("status") or [None])[0]
            items = [p for p in self.peers.values() if want is None or p["status"] == want]
            return httpx.Response(200, json={"items": items, "pagination": {"total_items": len(items)}})
        if request.method == "POST" and path == "/api/v1/federation/peers/":
            body = json.loads(request.content)
            pid = max(self.peers) + 1 if self.peers else 1
            self.peers[pid] = {"id": pid, "name": body["name"], "base_url": body["base_url"],
                               "status": "PENDING_APPROVAL"}
            return httpx.Response(201, json=self.peers[pid])
        parts = path.rstrip("/").split("/")
        if request.method == "POST" and path.startswith("/api/v1/admin/federation/peers/") and len(parts) == 8:
            pid, verb = int(parts[-2]), parts[-1]
            p = self.peers.get(pid)
            need, to = {"reactivate": ("INACTIVE", "ACTIVE"), "deactivate": ("ACTIVE", "INACTIVE"),
                        "approve": ("PENDING_APPROVAL", "ACTIVE"), "reject": ("PENDING_APPROVAL", "REJECTED")}[verb]
            if not p or p["status"] != need:
                return httpx.Response(400, json={"detail": f"Cannot {verb} peer registry"})
            p["status"] = to
            if verb == "deactivate":
                p["deactivated_reason"] = (q.get("reason") or [None])[0]
            return httpx.Response(200, json=p)
        return httpx.Response(404, json={"detail": f"unexpected {request.method} {path}"})


def _resolve(R, row):
    return asyncio.run(R._fixture_peer_for(ROWS[row], "dev.jwt"))


# ── each status row takes a fixture of the sweep's own, in the state it needs ───────────────────────────────────────

def test_red_each_status_row_takes_its_own_fixture_in_the_state_it_needs(monkeypatch):
    R = _router(monkeypatch)
    f = _Frame(monkeypatch, [REAL_ACTIVE, REAL_RETIRED, _fixture(10, "PENDING_APPROVAL"), _fixture(11, "INACTIVE"),
                             _fixture(12, "ACTIVE"), _fixture(9, "INACTIVE")])
    assert _resolve(R, "approve") == ("10", "")
    assert _resolve(R, "reject") == ("10", "")
    assert _resolve(R, "reactivate") == ("11", "")     # the newest inactive one
    assert _resolve(R, "deactivate") == ("12", "")
    assert f.writes == []                              # all four were ready: nothing was changed to find them


def test_red_the_deactivate_row_approves_a_fixture_of_its_own_never_reactivates_one(monkeypatch):
    # A reactivation registers the peer as a TEG partner and a deactivation emits teg_id=None, so no reactor removes it:
    # the V0624 sweep's reactivate row left teg-testfederationpeer1792334245459 on sbx-alpha's TEG (21:04:22Z).
    R = _router(monkeypatch)
    f = _Frame(monkeypatch, [REAL_ACTIVE, REAL_RETIRED, _fixture(11, "INACTIVE")])
    assert _resolve(R, "deactivate") == ("12", "")
    assert f.writes == [("POST", "/api/v1/federation/peers/"), ("POST", "/api/v1/admin/federation/peers/12/approve")]
    assert f.peers[11]["status"] == "INACTIVE" and f.peers[12]["status"] == "ACTIVE"
    assert f.peers[2]["status"] == "ACTIVE" and f.peers[7]["status"] == "INACTIVE"


def test_control_a_pending_fixture_is_approved_without_minting_another(monkeypatch):
    R = _router(monkeypatch)
    f = _Frame(monkeypatch, [REAL_ACTIVE, _fixture(10, "PENDING_APPROVAL"), _fixture(11, "INACTIVE")])
    assert _resolve(R, "deactivate") == ("10", "")
    assert f.writes == [("POST", "/api/v1/admin/federation/peers/10/approve")]


def test_red_the_reactivate_row_retires_an_active_fixture_of_its_own_first(monkeypatch):
    R = _router(monkeypatch)
    f = _Frame(monkeypatch, [REAL_ACTIVE, REAL_RETIRED, _fixture(12, "ACTIVE")])
    assert _resolve(R, "reactivate") == ("12", "")
    assert f.writes == [("POST", "/api/v1/admin/federation/peers/12/deactivate")]
    assert f.peers[7]["status"] == "INACTIVE"          # the retired real peer is never the one revived


def test_red_a_pending_fixture_is_minted_on_the_reserved_host(monkeypatch):
    R = _router(monkeypatch)
    f = _Frame(monkeypatch, [REAL_ACTIVE, REAL_RETIRED])
    pid, why = _resolve(R, "reject")
    assert (pid, why) == ("8", "")
    assert f.writes == [("POST", "/api/v1/federation/peers/")]
    assert R._is_fixture_peer(f.peers[8]) and f.peers[8]["base_url"].endswith(".theprotocol.test")
    assert R.DYNAMIC_VALUES["fixture_peer_id"] == "8"


def test_red_with_no_fixture_of_its_own_the_reactivate_row_gets_none_never_a_real_peer(monkeypatch):
    R = _router(monkeypatch, {"peer_id": "2"})        # an earlier row left the frame's real peer here
    f = _Frame(monkeypatch, [REAL_ACTIVE, REAL_RETIRED])
    pid, why = _resolve(R, "reactivate")
    assert pid is None and "no fixture peer of the sweep's own" in why, why
    assert f.writes == []
    assert f.peers[2]["status"] == "ACTIVE" and f.peers[7]["status"] == "INACTIVE"


def test_red_with_no_fixture_of_its_own_the_deactivate_row_makes_one_never_takes_a_real_peer(monkeypatch):
    R = _router(monkeypatch, {"peer_id": "2"})
    f = _Frame(monkeypatch, [REAL_ACTIVE, REAL_RETIRED])
    assert _resolve(R, "deactivate") == ("8", "")
    assert f.writes == [("POST", "/api/v1/federation/peers/"), ("POST", "/api/v1/admin/federation/peers/8/approve")]
    assert R._is_fixture_peer(f.peers[8])
    assert f.peers[2]["status"] == "ACTIVE" and f.peers[7]["status"] == "INACTIVE"


def test_control_an_unreadable_peer_list_gives_none_and_changes_nothing(monkeypatch):
    R = _router(monkeypatch)
    f = _Frame(monkeypatch, [_fixture(12, "ACTIVE")], list_status=500)
    pid, why = _resolve(R, "deactivate")
    assert pid is None and "500" in why, why
    assert f.writes == []


# ── base withholds the four routes unless the router verified that one concrete path ────────────────────────────────

def test_red_the_peer_status_routes_are_withheld_unless_their_path_was_verified(monkeypatch):
    monkeypatch.setattr(B, "_VERIFIED_SWEEP_OWN", set())
    for verb in ("approve", "reject", "reactivate", "deactivate"):
        assert B._classify_destructive("POST", f"/admin/federation/peers/33/{verb}"), verb
        assert B._classify_destructive("POST", f"/admin/federation/peers/{{peer_id}}/{verb}"), verb
    B.mark_sweep_own("POST", "/admin/federation/peers/33/reactivate")
    assert B._classify_destructive("POST", "/admin/federation/peers/33/reactivate") == ""
    assert B._classify_destructive("POST", "/admin/federation/peers/34/reactivate")      # another peer: withheld
    assert B._classify_destructive("POST", "/admin/federation/peers/33/deactivate")      # another verb: withheld
    B.mark_sweep_own("POST", "/admin/federation/peers/35/deactivate")                    # one mark at a time
    assert B._classify_destructive("POST", "/admin/federation/peers/33/reactivate")
    assert B._classify_destructive("POST", "/admin/federation/peers/35/deactivate") == ""
    # the slash settings of a peer, the same way, and only for the method that was checked
    assert B._classify_destructive("PUT", "/federation/disputes/peer-slash-config/2")
    B.mark_sweep_own("PUT", "/federation/disputes/peer-slash-config/33")
    assert B._classify_destructive("PUT", "/federation/disputes/peer-slash-config/33") == ""
    assert B._classify_destructive("PUT", "/federation/disputes/peer-slash-config/2")


def test_control_other_recovery_routes_and_reads_are_untouched(monkeypatch):
    monkeypatch.setattr(B, "_VERIFIED_SWEEP_OWN", set(), raising=False)
    assert B._classify_destructive("POST", "/admin/agents/did:theprotocol:x/reinstate") == ""
    assert B._classify_destructive("GET", "/admin/federation/peers/all") == ""
    assert B._classify_destructive("GET", "/federation/peers/33") == ""


# ── the fixture an approve, reactivate or deactivate row leaves ACTIVE is retired once measured ─────────────────────

def test_red_the_reactivate_rows_fixture_is_retired_once_measured(monkeypatch):
    R = _router(monkeypatch)
    f = _Frame(monkeypatch, [REAL_ACTIVE, _fixture(12, "ACTIVE")])
    asyncio.run(R._retire_fixture_peer(ROWS["reactivate"], "/admin/federation/peers/12/reactivate", {}, "dev.jwt"))
    assert f.writes == [("POST", "/api/v1/admin/federation/peers/12/deactivate")]
    assert f.peers[12]["deactivated_reason"] == "apitest: reactivated fixture peer retired at once"


def test_red_the_deactivate_rows_fixture_is_retired_when_the_row_did_not(monkeypatch):
    R = _router(monkeypatch)
    f = _Frame(monkeypatch, [_fixture(11, "ACTIVE")])
    asyncio.run(R._retire_fixture_peer(ROWS["deactivate"], "/admin/federation/peers/11/deactivate", {}, "dev.jwt"))
    assert f.peers[11]["status"] == "INACTIVE"
    assert f.peers[11]["deactivated_reason"] == "apitest: fixture peer retired after the deactivate row"


def test_control_the_approve_row_keeps_its_retire_reason(monkeypatch):
    R = _router(monkeypatch)
    f = _Frame(monkeypatch, [_fixture(10, "ACTIVE")])
    asyncio.run(R._retire_fixture_peer(ROWS["approve"], "/admin/federation/peers/10/approve", {}, "dev.jwt"))
    assert f.peers[10]["deactivated_reason"] == "apitest: approved fixture peer retired at once"


def test_control_a_real_peer_is_never_retired_and_reject_retires_nothing(monkeypatch):
    R = _router(monkeypatch)
    f = _Frame(monkeypatch, [REAL_ACTIVE, _fixture(10, "PENDING_APPROVAL")])
    asyncio.run(R._retire_fixture_peer(ROWS["reactivate"], "/admin/federation/peers/2/reactivate", {}, "dev.jwt"))
    asyncio.run(R._retire_fixture_peer(ROWS["reject"], "/admin/federation/peers/10/reject", {}, "dev.jwt"))
    assert f.writes == []
    assert f.peers[2]["status"] == "ACTIVE"
    assert not [r for r in f.seen if "/10/" in r.url.path or r.url.path.endswith("/reject")]


# ── the slash settings row takes a fixture of the sweep's own too ───────────────────────────────────────────────────

SLASH = "/federation/disputes/peer-slash-config/{peer_id}"


def test_red_the_slash_row_takes_the_newest_fixture_of_its_own(monkeypatch):
    R = _router(monkeypatch, {"peer_id": "2"})
    f = _Frame(monkeypatch, [REAL_ACTIVE, _fixture(9, "ACTIVE"), _fixture(11, "INACTIVE")])
    assert asyncio.run(R._fixture_peer_for(SLASH, "dev.jwt")) == ("11", "")
    assert f.writes == []


def test_control_with_no_fixture_the_slash_row_mints_one_never_the_real_peer(monkeypatch):
    R = _router(monkeypatch, {"peer_id": "2"})
    f = _Frame(monkeypatch, [REAL_ACTIVE, REAL_RETIRED])
    pid, why = asyncio.run(R._fixture_peer_for(SLASH, "dev.jwt"))
    assert (pid, why) == ("8", "") and f.writes == [("POST", "/api/v1/federation/peers/")]


def test_red_every_slash_update_records_its_own_event(monkeypatch):
    # The key was the resulting config: the second identical update, and an update back to an earlier config, were
    # dropped by the store as duplicates of the first (the V0624 sweep's red: "missing PeerSlashConfigUpdated").
    from agentvault_registry.routers import federation_disputes as FD

    class _Peer:
        id, name, base_url = 33, "Test Federation Peer 1", "https://test-peer-1.theprotocol.test"
        auto_slash_enabled, auto_slash_max_avt = True, 500

    class _Res:
        def scalar_one_or_none(self):
            return _Peer

    class _Db:
        async def execute(self, *a, **k):
            return _Res()

        async def commit(self):
            return None

    from tests._doubles import StrictEmitter
    emitter = StrictEmitter()                          # the real EventEmitter.emit signature, every call recorded
    monkeypatch.setattr(FD, "get_event_emitter", lambda: emitter)
    admin = type("Admin", (), {"email": "admin@test.sandbox"})()
    cfg = FD.PeerSlashConfigUpdate(auto_slash_enabled=True, auto_slash_max_avt=500)
    for _ in range(2):
        asyncio.run(FD.update_peer_slash_config(peer_id=33, config=cfg, current_admin=admin, db=_Db()))
    emitter.assert_received("PeerSlashConfigUpdated", via="emit")
    keys = [r["idempotency_key"] for r in emitter.of_type("PeerSlashConfigUpdated")]
    assert len(keys) == 2 and keys[0] != keys[1], keys
    assert all(k.startswith("peerslash-33-") for k in keys), keys


# ── a peer's federation standing, the compliance switch and the emission policy are never written ───────────────────

STANDING = (("POST", "/admin/enforcement/registries/{peer_id}/quarantine"),
            ("POST", "/admin/enforcement/registries/2/lift-quarantine"),
            ("POST", "/admin/enforcement/registries/2/blacklist"),
            ("POST", "/admin/federation/frames/2/revoke"),
            ("POST", "/admin/federation/frames/{peer_id}/resync-eventstore"))


def test_red_a_peers_standing_is_not_measured_contract_or_not():
    for m, p in STANDING:
        kind, why = B._classify_frame_control(m, p)
        assert kind == "peer_standing" and "blacklist the API cannot undo" in why, (m, p)
    for m, p in (("POST", "/admin/federation/compliance/enforcement-mode"),
                 ("PUT", "/admin/event-emission-policies/TokensTransferred")):
        assert B._classify_frame_control(m, p)[0] == "frame_control", (m, p)


def test_control_their_reads_are_untouched():
    for m, p in (("GET", "/admin/enforcement/registries/quarantined"),
                 ("GET", "/admin/federation/compliance/enforcement-mode"),
                 ("GET", "/admin/event-emission-policies"),
                 ("POST", "/admin/federation/compliance/peers/2/poll-now")):
        assert B._classify_frame_control(m, p) == ("", ""), (m, p)


class _SharedValues(dict):
    async def refresh_from_redis(self):
        return None


@pytest.mark.parametrize("method,path", [("POST", "/admin/enforcement/registries/{peer_id}/blacklist"),
                                         ("POST", "/admin/enforcement/registries/{peer_id}/quarantine")])
def test_red_the_router_sends_nothing_for_a_peers_standing(monkeypatch, method, path):
    from agentvault_registry.routers import admin_api_test as R
    monkeypatch.setattr(R, "DYNAMIC_VALUES", _SharedValues(peer_id="2"))   # the frame's real peer, left by a prereq
    monkeypatch.setattr(R, "API_TEST_TARGET_URL", "http://registry-test:8000")
    monkeypatch.setattr(R, "_delegation_target", lambda: None)
    f = _Frame(monkeypatch, [REAL_ACTIVE])
    out = asyncio.run(R.test_endpoint(request=None, endpoint_test={"method": method, "path": path,
                                                                   "body": {"reason": "AAA+ contract test"}},
                                      current_developer=None))
    assert out["not_measured"] is True and out["failure_bucket"] == "not_measured_peer_standing", out
    assert f.seen == []


# ── the FX pool row reads the pool toward a frame with another unit ─────────────────────────────────────────────────

class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _PoolDb:
    """The two reads _fx_counterparty_did makes: the ACTIVE peer frames, then a mirrored card of one of them."""

    def __init__(self, peers, cards):
        self.peers, self.cards, self.card_names = peers, cards, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, stmt, params=None):
        if "FROM agent_cards" in str(stmt):
            self.card_names.append(params["n"])
            did = self.cards.get(params["n"])
            return type("R", (), {"scalar": lambda _self: did})()
        return type("R", (), {"scalars": lambda _self: _Scalars(self.peers)})()


def _pool(monkeypatch, peers, cards, currencies, local="SBXA"):
    from agentvault_registry import database
    from agentvault_registry.routers import admin_api_test as R
    from agentvault_registry.routers import teg_integration as T
    db = _PoolDb(peers, cards)
    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: db)
    monkeypatch.setattr(T, "_local_frame_currency", lambda: local)

    async def _ccy(_db, target_peer=None, trust_domain=None):
        return currencies.get(target_peer.name)
    monkeypatch.setattr(T, "_resolve_peer_currency", _ccy)
    return R, db


def _peer(name):
    return type("Peer", (), {"name": name})()


def test_red_the_pool_row_names_a_receiver_on_a_frame_with_another_unit(monkeypatch):
    R, db = _pool(monkeypatch, [_peer("Old Alpha Twin"), _peer("Sandbox Beta")],
                  {"Old Alpha Twin": "did:theprotocol:twin-card", "Sandbox Beta": "did:theprotocol:beta-card"},
                  {"Old Alpha Twin": "SBXA", "Sandbox Beta": "SBXB"})
    assert asyncio.run(R._fx_counterparty_did()) == "did:theprotocol:beta-card"
    assert db.card_names == ["Sandbox Beta"]          # a frame with this frame's own unit is never asked for a card


def test_control_no_frame_with_another_unit_names_no_receiver(monkeypatch):
    R, db = _pool(monkeypatch, [_peer("Old Alpha Twin")], {"Old Alpha Twin": "did:theprotocol:twin-card"},
                  {"Old Alpha Twin": "SBXA"})
    assert asyncio.run(R._fx_counterparty_did()) is None


def test_red_with_no_such_frame_the_pool_row_is_not_measured(monkeypatch):
    from agentvault_registry.routers import admin_api_test as R
    monkeypatch.setattr(R, "DYNAMIC_VALUES", _SharedValues(agent_002_did="did:theprotocol:local-agent"))
    monkeypatch.setattr(R, "API_TEST_TARGET_URL", "http://registry-test:8000")
    monkeypatch.setattr(R, "_delegation_target", lambda: None)

    async def _none():
        return None
    monkeypatch.setattr(R, "_fx_counterparty_did", _none)
    f = _Frame(monkeypatch, [])
    out = asyncio.run(R.test_endpoint(request=None, endpoint_test={"method": "GET", "path": "/teg/fx/pool",
                                                                   "auth": "agent"}, current_developer=None))
    assert out["not_measured"] is True and "no cross-frame pool to read" in out["not_measured_reason"], out
    assert not [r for r in f.seen if "/teg/fx/pool" in r.url.path]


def test_red_the_pool_default_never_names_a_local_agent():
    from agentvault_registry.routers import admin_api_test as R
    q = R._REQUIRED_QUERY_DEFAULTS["/teg/fx/pool"]({"agent_002_did": "did:theprotocol:local-agent"})
    assert "local-agent" not in q
    assert R._REQUIRED_QUERY_DEFAULTS["/teg/fx/pool"]({"fx_counterparty_did": "did:theprotocol:beta-card"}) == \
        "receiver_did=did:theprotocol:beta-card"


# ── the support desk reads a live review grant: the revoke row is followed by a fresh grant ─────────────────────────

def _grant_http(monkeypatch):
    seen = []
    real = httpx.AsyncClient

    def _handle(request):
        seen.append(request)
        return httpx.Response(201, json={"grant_id": "g-new"})

    def _client(*a, **k):
        k["transport"] = httpx.MockTransport(_handle)
        return real(*a, **k)
    monkeypatch.setattr(httpx, "AsyncClient", _client)
    return seen


REVOKE = "/chat/conversations/{conversation_id}/support-review/{grant_id}"


def test_red_review_is_granted_again_once_the_revoke_row_is_measured(monkeypatch):
    R = _router(monkeypatch, {"chat_review_ticket_id": "77", "grant_id": "g-old", "conversation_id": "c-1"})
    seen = _grant_http(monkeypatch)
    asyncio.run(R._regrant_after_revoke(REVOKE, "/chat/conversations/c-1/support-review/g-old",
                                        {"healthy": True}, "dev.jwt"))
    assert [(r.method, r.url.path) for r in seen] == [("POST", "/api/v1/chat/conversations/c-1/support-review")]
    assert json.loads(seen[0].content).get("ticket_id") == 77, seen[0].content
    assert R.DYNAMIC_VALUES["grant_id"] == "g-new"


@pytest.mark.parametrize("values,result", [
    ({"chat_review_ticket_id": "77"}, {"healthy": False, "statusCode": 404}),      # the revoke itself failed
    ({}, {"healthy": True}),                                                       # no ticket of the sweep's own
])
def test_control_no_grant_after_a_failed_revoke_or_without_a_ticket(monkeypatch, values, result):
    R = _router(monkeypatch, {**values, "grant_id": "g-old"})
    seen = _grant_http(monkeypatch)
    asyncio.run(R._regrant_after_revoke(REVOKE, "/chat/conversations/c-1/support-review/g-old", result, "dev.jwt"))
    assert seen == [] and R.DYNAMIC_VALUES["grant_id"] == "g-old"


# ── the peer status rows run no contract: the contract would act on the shared peer_id before any resolver ──────────
# Rehearsed on sbx-alpha 2026-10-18 22:09Z with the first cut of this batch: the reactivate CONTRACT
# (api_tests/contracts/frame_federation.py) reactivated fixture 35, the one the deactivate row had just retired, and the
# row ended there with it ACTIVE; the approve and deactivate contracts had called 33 and 34 first (400) and fallen
# through. Contracts run before the router's fixture resolver, base's gate and the retire hook.

def test_red_the_peer_status_rows_run_no_contract():
    from agentvault_registry.routers import admin_api_test as R
    from agentvault_registry.api_tests.core.contract import get_contract
    R._ensure_contracts_loaded()
    for verb in ("approve", "deactivate", "reactivate"):
        p = f"/admin/federation/peers/{{peer_id}}/{verb}"
        assert get_contract("POST", p) is not None, p          # the contracts exist
        assert R._contract_for("POST", p) is None, p
    assert R._contract_for("POST", "/admin/federation/peers/33/reactivate") is None


def test_control_every_other_row_keeps_its_contract():
    from agentvault_registry.routers import admin_api_test as R
    from agentvault_registry.api_tests.core.contract import get_contract
    R._ensure_contracts_loaded()
    for m, p in (("GET", "/admin/federation/peers"), ("GET", "/federation/peers/{peer_id}"),
                 ("POST", "/federation/peers/")):
        assert get_contract(m, p) is not None and R._contract_for(m, p) is get_contract(m, p), (m, p)


# ── the internal federation rail with no peer to speak as ──────────────────────────────────────────────────────────

def _fed_router(monkeypatch, identity):
    from agentvault_registry.api_tests import auth_manager
    from agentvault_registry.routers import admin_api_test as R
    monkeypatch.setattr(R, "DYNAMIC_VALUES", _SharedValues())
    monkeypatch.setattr(R, "API_TEST_TARGET_URL", "http://registry-test:8000")
    monkeypatch.setattr(R, "_delegation_target", lambda: None)

    async def _identity(path=""):
        return identity
    monkeypatch.setattr(auth_manager, "federation_spiffe_id", _identity)
    return R


def test_red_a_peer_route_with_no_peer_to_speak_as_is_not_measured(monkeypatch):
    # sbx-alpha 2026-10-18 21:12Z: its only peer frame held blacklisted, GET /federation/agent-cards, /peers and
    # /sync-status went out with an empty identity and read FAIL on the 401 that alone produced.
    R = _fed_router(monkeypatch, "")
    f = _Frame(monkeypatch, [])
    out = asyncio.run(R.test_endpoint(request=None, endpoint_test={"method": "GET", "path": "/federation/agent-cards",
                                                                   "auth": "mtls"}, current_developer=None))
    assert out["not_measured"] is True and "no ACTIVE peer to speak as" in out["not_measured_reason"], out
    assert f.seen == []


def test_control_with_a_peer_to_speak_as_the_route_is_called_as_that_peer(monkeypatch):
    R = _fed_router(monkeypatch, "spiffe://sandbox-b.theprotocol.cloud/service/registry")
    seen = []
    real = httpx.AsyncClient

    def _client(*a, **k):
        k["transport"] = httpx.MockTransport(lambda req: seen.append(req) or httpx.Response(200, json={"items": []}))
        return real(*a, **k)
    monkeypatch.setattr(httpx, "AsyncClient", _client)
    out = asyncio.run(R.test_endpoint(request=None, endpoint_test={"method": "GET", "path": "/federation/agent-cards",
                                                                   "auth": "mtls"}, current_developer=None))
    assert out.get("not_measured") is not True and out["statusCode"] == 200, out
    calls = [r for r in seen if r.url.path == "/api/v1/federation/agent-cards"]
    assert calls and calls[0].headers["X-Federation-SPIFFE-ID"] == "spiffe://sandbox-b.theprotocol.cloud/service/registry"
