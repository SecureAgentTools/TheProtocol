"""§TWOAGENT G3 (2026-09-23) — the Guild tells agent RUNTIMES what it tells phones, and a registry vouches only for its own.

Measured in the two-agent run (V0430, order gwo_d2bb…, ASIA poster, EU worker): every step was learned by POLLING the
order, 14 to 38 s each (the bid on the poster's side, the award on the worker's side, the delivery, the verdict). The
§NOTIFV2 push reaches a phone; no webhook reached a runtime, and a worker on another frame heard nothing at all. Now
`guild.bid_received` / `guild.work_submitted` go to the poster's owner and `guild.awarded` / `guild.verified` to the
worker's owner, owner-scoped; a REMOTE worker hears through its home (`POST /api/v1/federation/guild/notice`, advisory,
the host resolved from its SVID, one webhook per host/order/kind). The award answer's `bid_id` is in the bid webhook.

Found on the way, the same class three times (a federation caller trusted to speak for someone else):
  * `POST /federation/guild/orders/{oid}/bid` took ANY caller's word for the bidder's home and reputation;
  * `POST /federation/guild/orders/{oid}/submit` let ANY caller deliver in a remote worker's name (a reject of that
    delivery disputes the real worker);
  * `POST /federation/guild/stake` let ANY caller that named the host SLASH a bidder's collateral held here.
Each is now bound to the caller's SVID (`resolve_peer_name`): the bidder's home, the worker's home, the order's host.

RED on V0430: no webhooks, no notice route, the three routes obey a stranger. The controls (the host itself may still
release a stake; a notice is delivered once) pass where they can on both trees.
"""
from __future__ import annotations

import asyncio
import types

import pytest
from fastapi import HTTPException

POSTER = "did:theprotocol:asia.test:poster"
WORKER = "did:theprotocol:eu.test:worker"
LOCAL_WORKER = "did:theprotocol:asia.test:local-worker"
OID = "gwo_test0001"
EU_SVID = "spiffe://eu.theprotocol.cloud/service/registry"
ASIA_SVID = "spiffe://asia.theprotocol.cloud/service/registry"
STRANGER_SVID = "spiffe://lantern.theprotocol.cloud/service/registry"


class _Result:
    def __init__(self, rows=(), rowcount=None):
        self._rows = list(rows)
        self.rowcount = len(self._rows) if rowcount is None else rowcount

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar(self):
        r = self.first()
        if r is None:
            return None
        return r[0] if isinstance(r, (tuple, list)) else r

    def mappings(self):
        return self


class _Db:
    def __init__(self, handlers=()):
        self.handlers = list(handlers)
        self.sql = []

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        self.sql.append(sql)
        for needle, res in self.handlers:
            if needle in sql:
                return res() if callable(res) else res
        return _Result([], rowcount=0)

    async def commit(self):
        return None

    def wrote(self, needle):
        return any(needle in q for q in self.sql)


def _order(**kw):
    o = {"id": OID, "poster_did": POSTER, "title": "Assay a sample", "spec": "", "bounty": "3.0", "currency": "ACU",
         "fee_bps": 250, "status": "open", "min_reputation": None, "stake_required": None, "worker_did": None,
         "worker_home_registry": None, "payee_did": None, "payee_org_id": None}
    o.update(kw)
    return o


@pytest.fixture
def g(monkeypatch):
    """The guild router with every side effect recorded or stubbed; peer names resolved by host substring."""
    from agentvault_registry.routers import guild
    from agentvault_registry.background_tasks import reactor_helpers as rh
    from agentvault_registry.background_tasks import push_notify
    from agentvault_registry.services import contract_xframe
    hooks: list = []

    async def _owner(event, data, dids, source_label="endpoint"):
        hooks.append((event, tuple(dids), data))
        return 1

    async def _nothing(*a, **k):
        return None

    async def _resolve(db, value):
        v = str(value or "")
        return "eu" if "eu." in v else ("asia" if "asia." in v else ("lantern" if "lantern" in v else None))
    monkeypatch.setenv("GUILD_ENABLED", "true")
    monkeypatch.setattr(rh, "dispatch_webhook_for_agents", _owner)
    monkeypatch.setattr(push_notify, "notify_agent_owners", _nothing)
    monkeypatch.setattr(contract_xframe, "resolve_peer_name", _resolve)
    monkeypatch.setattr(guild, "_emit", lambda *a, **k: None)
    monkeypatch.setattr(guild._rb, "gate", _nothing)
    monkeypatch.setattr(guild._ep, "gate", _nothing)
    monkeypatch.setattr(guild, "_firm_bounty_gate", _nothing)
    monkeypatch.setattr(guild, "_refund_all_stakes", _nothing)
    monkeypatch.setattr(guild.guild_contract_mirror, "sync_from_order", _nothing)
    guild._hooks = hooks
    return guild


async def _drain():
    for _ in range(8):
        await asyncio.sleep(0)


def _events(g):
    return [(e, d) for e, d, _ in g._hooks]


def test_the_vocabulary_names_the_events():
    from agentvault_registry.services.webhook_service import WebhookService
    assert {"guild.bid_received", "guild.awarded", "guild.work_submitted", "guild.verified"} <= set(
        WebhookService.SUPPORTED_EVENTS)


# ─────────────────────────────── bids ───────────────────────────────

async def test_a_local_bid_is_told_to_the_posters_owner_with_its_bid_id(g, monkeypatch):
    async def _load(db, oid):
        return _order()
    monkeypatch.setattr(g, "_load", _load)
    db = _Db([("INSERT INTO guild_bids", _Result([(11,)]))])
    out = await g.place_bid(OID, g.BidIn(price=3.0), agent=types.SimpleNamespace(did=LOCAL_WORKER), db=db)
    await _drain()
    assert out.get("bid_id") == 11
    assert _events(g) == [("guild.bid_received", (POSTER,))]
    assert g._hooks[0][2]["bid_id"] == 11 and "award_with" in g._hooks[0][2]


def _fed_bid(**kw):
    from agentvault_registry.routers import guild
    return guild.FederatedBidIn(**{"bidder_did": WORKER, "home_registry_url": "https://eu.theprotocol.cloud",
                                   "price": 3.0, **kw})


async def test_a_federated_bid_must_come_from_the_bidders_home(g, monkeypatch):
    async def _load(db, oid):
        return _order()
    monkeypatch.setattr(g, "_load", _load)
    db = _Db([("INSERT INTO guild_bids", _Result([(12,)]))])
    with pytest.raises(HTTPException) as e:
        await g.place_bid_federated(OID, _fed_bid(), db=db, peer_spiffe_id=STRANGER_SVID)
    assert e.value.status_code == 403 and not db.wrote("INSERT INTO guild_bids")


async def test_a_federated_bid_from_the_home_is_told_to_the_poster(g, monkeypatch):
    async def _load(db, oid):
        return _order()
    monkeypatch.setattr(g, "_load", _load)
    db = _Db([("INSERT INTO guild_bids", _Result([(12,)]))])
    out = await g.place_bid_federated(OID, _fed_bid(), db=db, peer_spiffe_id=EU_SVID)
    await _drain()
    assert out["via"] == "federation" and out.get("bid_id") == 12
    assert _events(g) == [("guild.bid_received", (POSTER,))]


# ─────────────────────────────── award ───────────────────────────────

def _award_db(home):
    bid = {"id": 12, "bidder_did": WORKER if home else LOCAL_WORKER, "status": "open", "on_behalf_of_org_id": None,
           "home_registry_url": home, "payee_did_hint": None}
    return _Db([("SELECT id, bidder_did, status, on_behalf_of_org_id", _Result([bid])),
                ("UPDATE guild_work_orders SET status='awarded'", _Result([], rowcount=1))])


async def test_an_award_to_a_local_worker_is_told_to_its_owner(g, monkeypatch):
    async def _load(db, oid):
        return _order()
    monkeypatch.setattr(g, "_load", _load)
    await g.award(OID, g.AwardIn(bid_id=12), agent=types.SimpleNamespace(did=POSTER), db=_award_db(None))
    await _drain()
    assert _events(g) == [("guild.awarded", (LOCAL_WORKER,))]


async def test_an_award_to_a_remote_worker_goes_to_its_home(g, monkeypatch):
    shipped: list = []

    async def _load(db, oid):
        return _order()
    monkeypatch.setattr(g, "_load", _load)
    monkeypatch.setattr(g, "_ship_guild_notice", lambda o, kind, extra: shipped.append(
        (kind, o.get("worker_did"), o.get("worker_home_registry"))), raising=False)
    await g.award(OID, g.AwardIn(bid_id=12), agent=types.SimpleNamespace(did=POSTER),
                  db=_award_db("https://eu.theprotocol.cloud"))
    await _drain()
    assert shipped == [("awarded", WORKER, "https://eu.theprotocol.cloud")] and _events(g) == []


# ─────────────────────────────── the worker's home ───────────────────────────────

def _notice(kind="awarded", **kw):
    from agentvault_registry.routers import guild
    return guild.GuildNoticeIn(**{"order_id": OID, "kind": kind, "worker_did": WORKER, "bid_id": 12, **kw})


async def test_the_home_tells_its_workers_owner_once(g, monkeypatch):
    seen: set = set()

    async def _first(host, oid, kind):
        k = (host, oid, kind)
        new = k not in seen
        seen.add(k)
        return new
    monkeypatch.setattr(g, "_notice_first_time", _first, raising=False)
    db = _Db([("SELECT 1 FROM agents WHERE did", _Result([(1,)]))])
    a = await g.receive_guild_notice(_notice(), db=db, peer_spiffe_id=ASIA_SVID)
    b = await g.receive_guild_notice(_notice(), db=db, peer_spiffe_id=ASIA_SVID)
    await _drain()
    assert (a["notified"], b["notified"]) == (True, False)
    assert _events(g) == [("guild.awarded", (WORKER,))]
    assert g._hooks[0][2]["host_registry"] == "asia" and "submit_with" in g._hooks[0][2]


async def test_the_home_refuses_a_notice_about_someone_elses_agent_or_from_nobody(g):
    with pytest.raises(HTTPException) as e:
        await g.receive_guild_notice(_notice(), db=_Db([]), peer_spiffe_id=ASIA_SVID)
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        await g.receive_guild_notice(_notice(), db=_Db([("SELECT 1 FROM agents WHERE did", _Result([(1,)]))]),
                                     peer_spiffe_id="spiffe://nowhere.test/service/registry")
    assert e.value.status_code == 403


# ─────────────────────────────── submit ───────────────────────────────

async def test_a_federated_submit_must_come_from_the_workers_home(g, monkeypatch):
    async def _load(db, oid):
        return _order(status="awarded", worker_did=WORKER, worker_home_registry="https://eu.theprotocol.cloud")
    monkeypatch.setattr(g, "_load", _load)
    db = _Db([])
    with pytest.raises(HTTPException) as e:
        await g.submit_federated(OID, g.FederatedSubmitIn(worker_did=WORKER, deliverable={"uri": "x"}), db=db,
                                 peer_spiffe_id=STRANGER_SVID)
    assert e.value.status_code == 403 and not db.wrote("SET status='submitted'")
    out = await g.submit_federated(OID, g.FederatedSubmitIn(worker_did=WORKER, deliverable={"uri": "x"}), db=db,
                                   peer_spiffe_id=EU_SVID)
    await _drain()
    assert out["status"] == "submitted"
    assert _events(g) == [("guild.work_submitted", (POSTER,))]


# ─────────────────────────────── verify ───────────────────────────────

async def test_a_rejected_delivery_is_told_to_the_local_worker(g, monkeypatch):
    async def _load(db, oid):
        return _order(status="submitted", worker_did=LOCAL_WORKER)

    async def _ddr(db, a, b):
        return "ddr-1"
    monkeypatch.setattr(g, "_load", _load)
    monkeypatch.setattr(g, "_file_ddr_dispute", _ddr)
    db = _Db([("SET status='disputed'", _Result([], rowcount=1))])
    out = await g.verify(OID, g.VerifyIn(accept=False, feedback="not it"), request=types.SimpleNamespace(headers={}),
                         agent=types.SimpleNamespace(did=POSTER), db=db)
    await _drain()
    assert out["status"] == "disputed"
    assert _events(g) == [("guild.verified", (LOCAL_WORKER,))] and g._hooks[0][2]["accepted"] is False


# ─────────────────────────────── stake ───────────────────────────────

def _stake_db():
    return _Db([("FROM guild_remote_stakes", _Result([types.SimpleNamespace(id=1, amount="2.0")]))])


async def test_only_the_orders_host_can_slash_a_stake_held_here(g):
    db = _stake_db()
    out = await g.federated_stake_action(g.FederatedStakeIn(order_id=OID, bidder_did=WORKER, action="slash",
                                                            host_registry="https://asia.theprotocol.cloud"),
                                         db=db, peer_spiffe_id=STRANGER_SVID)
    assert out == {"ok": True, "already": True} and not db.wrote("UPDATE guild_remote_stakes")


async def test_control_the_host_itself_can_release_a_stake(g, monkeypatch):
    async def _payout(*a, **k):
        return None
    monkeypatch.setattr(g.guild_escrow, "escrow_payout", _payout)
    db = _stake_db()
    out = await g.federated_stake_action(g.FederatedStakeIn(order_id=OID, bidder_did=WORKER, action="release",
                                                            host_registry="https://asia.theprotocol.cloud"),
                                         db=db, peer_spiffe_id=ASIA_SVID)
    assert out["action"] == "release" and db.wrote("UPDATE guild_remote_stakes")
