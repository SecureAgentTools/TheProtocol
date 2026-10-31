"""V0650 (f) (2026-10-31, agentvault2-14): a Guild order may name the agent it is meant for, and a bid from anyone else
is accepted and marked.

Order gwo_754cf6912ebece4f1487363a. POST /api/v1/guild/orders (and MCP guildPostOrder, and the organization door that
posts through it) takes an optional `intended_worker_did`: stored on the order, shown on the board, the federation board
and the order detail. It is a flag, never a gate: a bid from another agent is accepted like any other and carries
`not_intended_worker: true` (the bid's answer, the poster's guild.bid_received webhook, the bid's audit row, each bid row
of the order detail), local and federated alike, through ONE predicate derived at read time. A value that is not an agent
DID, or names the poster, is a 422 before any escrow moves.

The route functions run directly over a recording fake database (the test_twoagent_g3_guild_events pattern). Cases
marked BASE fail on V0649 (6c1f036b), where the field is silently dropped (pydantic's extra='ignore'), the INSERT and the
board name no column, and no answer carries the flag; the test_control_* cases pass on both trees.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import types

import pytest
from fastapi import HTTPException

POSTER = "did:theprotocol:eu.test:poster"
WORKER = "did:theprotocol:eu.test:intended-worker"
OTHER = "did:theprotocol:eu.test:another-agent"
REMOTE = "did:theprotocol:asia.test:remote-agent"
OID = "gwo_test0f01"
EU_SVID = "spiffe://eu.theprotocol.cloud/service/registry"
ASIA_SVID = "spiffe://asia.theprotocol.cloud/service/registry"


class _Result:
    def __init__(self, rows=(), rowcount=None):
        self._rows = list(rows)
        self.rowcount = len(self._rows) if rowcount is None else rowcount

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)

    def scalar(self):
        r = self.first()
        if r is None:
            return None
        return r[0] if isinstance(r, (tuple, list)) else r

    def mappings(self):
        return self


class _Db:
    """Records (sql, params); answers through (needle, result-or-callable(sql, params)) handlers, first match wins."""

    def __init__(self, handlers=()):
        self.handlers = list(handlers)
        self.calls = []

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        self.calls.append((sql, params or {}))
        for needle, res in self.handlers:
            if needle in sql:
                return res(sql, params or {}) if callable(res) else res
        return _Result([], rowcount=0)

    async def commit(self):
        return None

    def params_of(self, needle):
        return [p for s, p in self.calls if needle in s]

    def sql_of(self, needle):
        return [s for s, _ in self.calls if needle in s]


def _order(**kw):
    o = {"id": OID, "poster_did": POSTER, "title": "Fix the board", "spec": "", "bounty": "3.0", "currency": "ECU",
         "fee_bps": 250, "status": "open", "min_reputation": None, "stake_required": None, "worker_did": None,
         "worker_home_registry": None, "payee_did": None, "payee_org_id": None, "deliverable": None,
         "required_skills": None}
    o.update(kw)
    return o


@pytest.fixture
def g(monkeypatch):
    """The guild router with every side effect recorded or stubbed."""
    from agentvault_registry.routers import guild
    from agentvault_registry.background_tasks import reactor_helpers as rh
    from agentvault_registry.background_tasks import push_notify
    from agentvault_registry.services import contract_xframe
    from agentvault_registry.services import jurisdiction
    hooks: list = []
    escrow: list = []

    async def _owner(event, data, dids, source_label="endpoint"):
        hooks.append((event, tuple(dids), data))
        return 1

    async def _nothing(*a, **k):
        return None

    async def _deposit(did, amount, oid, *a, **k):
        escrow.append((did, str(amount), oid))

    async def _resolve(db, value):
        v = str(value or "")
        return "eu" if "eu." in v else ("asia" if "asia." in v else None)
    monkeypatch.setenv("GUILD_ENABLED", "true")
    monkeypatch.setattr(rh, "dispatch_webhook_for_agents", _owner)
    monkeypatch.setattr(push_notify, "notify_agent_owners", _nothing)
    monkeypatch.setattr(contract_xframe, "resolve_peer_name", _resolve)
    monkeypatch.setattr(jurisdiction, "check_jurisdiction", _nothing)
    monkeypatch.setattr(guild.guild_escrow, "escrow_deposit", _deposit)
    monkeypatch.setattr(guild, "_emit", lambda *a, **k: None)
    monkeypatch.setattr(guild._rb, "gate", _nothing)
    monkeypatch.setattr(guild._ep, "gate", _nothing)
    monkeypatch.setattr(guild, "_firm_bounty_gate", _nothing)
    monkeypatch.setattr(guild.guild_contract_mirror, "sync_from_order", _nothing)
    guild._hooks, guild._escrow = hooks, escrow
    return guild


async def _drain():
    for _ in range(8):
        await asyncio.sleep(0)


def _audit_payloads(db, etype):
    return [json.loads(p["p"]) for p in db.params_of("INSERT INTO guild_order_events") if p.get("e") == etype]


def _post_db():
    return _Db([("SELECT COALESCE(MAX(seq),0)+1", _Result([(1,)]))])


# ─────────────────────────────── post ───────────────────────────────

async def test_a_post_names_its_intended_worker(g):
    # BASE: the field is dropped, so nothing carries it
    db = _post_db()
    out = await g.post_order(g.OrderPostIn(title="t", bounty=3, intended_worker_did=f"  {WORKER} "),
                             agent=types.SimpleNamespace(did=POSTER), db=db)
    insert = db.params_of("INSERT INTO guild_work_orders")
    assert insert and insert[0].get("iw") == WORKER
    assert "intended_worker_did" in db.sql_of("INSERT INTO guild_work_orders")[0]
    assert out["intended_worker_did"] == WORKER
    assert _audit_payloads(db, "posted")[0]["intended_worker_did"] == WORKER


@pytest.mark.parametrize("value", ["session-release", "did:web:example.invalid", POSTER, "did:theprotocol:a b"])
async def test_a_post_naming_no_agent_did_or_the_poster_is_refused_before_any_escrow(g, value):
    # BASE: the field is dropped and the order is posted
    db = _post_db()
    with pytest.raises(HTTPException) as e:
        await g.post_order(g.OrderPostIn(title="t", bounty=3, intended_worker_did=value),
                           agent=types.SimpleNamespace(did=POSTER), db=db)
    assert e.value.status_code == 422 and "intended_worker_did" in str(e.value.detail)
    assert g._escrow == [] and not db.params_of("INSERT INTO guild_work_orders")


@pytest.mark.parametrize("value", [None, "", "   "])
async def test_control_a_post_without_one_stays_open_to_all(g, value):
    # control: passes on both trees
    db = _post_db()
    out = await g.post_order(g.OrderPostIn(title="t", bounty=3, intended_worker_did=value),
                             agent=types.SimpleNamespace(did=POSTER), db=db)
    assert out.get("intended_worker_did") is None and len(g._escrow) == 1
    assert db.params_of("INSERT INTO guild_work_orders")[0].get("iw") is None
    assert "intended_worker_did" not in _audit_payloads(db, "posted")[0]


def _board_db():
    def rows(sql, params):
        row = {"id": OID, "poster_did": POSTER, "title": "Fix the board", "status": "open", "bid_count": 0}
        if "o.intended_worker_did" in sql:   # what the database would answer for the SELECT as written
            row["intended_worker_did"] = WORKER
        return _Result([row])
    return _Db([("FROM guild_work_orders o", rows)])


async def test_the_board_and_the_federation_board_show_whom_an_order_is_meant_for(g):
    # BASE: the board's SELECT does not name the column
    for call in (lambda db: g.list_orders(status_filter="open", limit=50, db=db),
                 lambda db: g.federated_board(db=db, peer_spiffe_id=ASIA_SVID)):
        db = _board_db()
        out = await call(db)
        assert "o.intended_worker_did" in db.sql_of("FROM guild_work_orders o")[0]
        assert out["orders"][0]["intended_worker_did"] == WORKER


# ─────────────────────────────── bids ───────────────────────────────

def _bid_db(bid_id=21):
    return _Db([("INSERT INTO guild_bids", _Result([(bid_id,)])), ("SELECT COALESCE(MAX(seq),0)+1", _Result([(2,)]))])


def _loads(g, monkeypatch, **kw):
    async def _load(db, oid):
        return _order(**kw)
    monkeypatch.setattr(g, "_load", _load)


async def test_a_bid_from_the_intended_worker_is_not_flagged(g, monkeypatch):
    # BASE: the answer carries no flag
    _loads(g, monkeypatch, intended_worker_did=WORKER)
    db = _bid_db()
    out = await g.place_bid(OID, g.BidIn(price=3.0), agent=types.SimpleNamespace(did=WORKER), db=db)
    await _drain()
    assert out["not_intended_worker"] is False and out["intended_worker_did"] == WORKER
    assert g._hooks[0][2]["not_intended_worker"] is False
    assert "not_intended_worker" not in _audit_payloads(db, "bid")[0]


async def test_a_bid_from_anyone_else_is_accepted_and_flagged(g, monkeypatch):
    # BASE: accepted, but nothing says it is not the intended worker's
    _loads(g, monkeypatch, intended_worker_did=WORKER)
    db = _bid_db(22)
    out = await g.place_bid(OID, g.BidIn(price=3.0), agent=types.SimpleNamespace(did=OTHER), db=db)
    await _drain()
    assert db.params_of("INSERT INTO guild_bids") and out["bid_id"] == 22
    assert out["not_intended_worker"] is True
    event, dids, data = g._hooks[0]
    assert (event, dids) == ("guild.bid_received", (POSTER,)) and data["not_intended_worker"] is True
    assert _audit_payloads(db, "bid")[0]["not_intended_worker"] is True


async def test_control_a_bid_from_anyone_else_is_still_accepted(g, monkeypatch):
    # control: passes on both trees (the flag is never a gate)
    _loads(g, monkeypatch, intended_worker_did=WORKER)
    db = _bid_db(23)
    out = await g.place_bid(OID, g.BidIn(price=3.0), agent=types.SimpleNamespace(did=OTHER), db=db)
    assert out["ok"] is True and out["bid_id"] == 23 and db.params_of("INSERT INTO guild_bids")


async def test_a_federated_bid_from_another_agent_is_flagged(g, monkeypatch):
    # BASE: the federated answer carries no flag
    _loads(g, monkeypatch, intended_worker_did=WORKER)
    db = _bid_db(24)
    body = g.FederatedBidIn(bidder_did=REMOTE, home_registry_url="https://asia.theprotocol.cloud", price=3.0)
    out = await g.place_bid_federated(OID, body, db=db, peer_spiffe_id=ASIA_SVID)
    await _drain()
    assert out["via"] == "federation" and out["bid_id"] == 24 and out["not_intended_worker"] is True
    assert g._hooks[0][2]["not_intended_worker"] is True
    assert _audit_payloads(db, "bid")[0]["not_intended_worker"] is True


async def test_the_order_detail_names_the_worker_and_flags_every_other_bid(g, monkeypatch):
    # BASE: no bid row carries the flag
    _loads(g, monkeypatch, intended_worker_did=WORKER)
    bids = [{"id": 1, "bidder_did": WORKER, "price": 3, "status": "open"},
            {"id": 2, "bidder_did": OTHER, "price": 2, "status": "open"}]
    db = _Db([("FROM guild_bids WHERE order_id", _Result(bids))])
    out = await g.order_detail(OID, db=db, dev=None)
    assert out["order"]["intended_worker_did"] == WORKER
    assert [(b["bidder_did"], b["not_intended_worker"]) for b in out["bids"]] == [(WORKER, False), (OTHER, True)]


async def test_an_order_naming_nobody_flags_no_bid(g, monkeypatch):
    # BASE: the key is absent
    _loads(g, monkeypatch)
    db = _Db([("FROM guild_bids WHERE order_id", _Result([{"id": 1, "bidder_did": OTHER, "status": "open"}]))])
    out = await g.order_detail(OID, db=db, dev=None)
    assert out["bids"][0]["not_intended_worker"] is False


# ─────────────────────────────── the organization door ───────────────────────────────

async def test_the_org_door_passes_the_intended_worker_and_hashes_a_body_without_it_as_before(monkeypatch):
    # BASE: the organization's body drops the field, so the Guild never sees it
    from agentvault_registry.routers import organizations as orgs, guild
    from agentvault_registry.services import org_treasury, admin_audit
    from agentvault_registry.services.idempotency import cache
    from agentvault_registry.services.exchange_service import mover
    from decimal import Decimal
    posted, hashed = [], []

    async def _nothing(*a, **k):
        return None

    async def _poster(db, org_id):
        return types.SimpleNamespace(did="did:theprotocol:eu.test:org-treasury")

    async def _lookup(scope, key, body, principal=None):
        hashed.append(dict(body))
        return None, None

    async def _balance(did):
        return Decimal(100)

    async def _post(body, agent, db):
        posted.append(body)
        return {"order_id": "gwo_org", "status": "open"}
    monkeypatch.setattr(orgs, "get_organization_with_permission", _nothing)
    monkeypatch.setattr(orgs, "_org_poster_or_raise", _poster)
    monkeypatch.setattr(org_treasury, "_procurement_cap_or_raise", _nothing)
    monkeypatch.setattr(cache, "idempotency_lookup", _lookup)
    monkeypatch.setattr(cache, "idempotency_store", _nothing)
    monkeypatch.setattr(mover, "agent_balance", _balance)
    monkeypatch.setattr(guild, "post_order", _post)
    monkeypatch.setattr(admin_audit, "log_admin_action", _nothing)
    dev = types.SimpleNamespace(id=6)
    await orgs.post_org_work_order(orgs.OrgWorkOrderCreate(title="t", bounty="2", intended_worker_did=WORKER),
                                   org_id="org-s", idempotency_key="k-1", current_developer=dev, db=None)
    await orgs.post_org_work_order(orgs.OrgWorkOrderCreate(title="t", bounty="2"),
                                   org_id="org-s", idempotency_key="k-2", current_developer=dev, db=None)
    assert getattr(posted[0], "intended_worker_did", None) == WORKER
    assert getattr(posted[1], "intended_worker_did", None) is None
    assert hashed[0]["intended_worker_did"] == WORKER and "intended_worker_did" not in hashed[1]


# ─────────────────────────────── MCP, schema, model ───────────────────────────────

@pytest.fixture
def sent(monkeypatch):
    from agentvault_registry.mcp import tools_guild as G
    calls = []

    async def _post(path, payload, token):
        calls.append((path, payload))
        return {"ok": True}
    monkeypatch.setattr(G, "_guild_post", _post)
    return calls


def _agent_auth():
    from agentvault_registry.mcp.auth_bridge import MCPAuthContext
    return MCPAuthContext(auth_type="agent", agent_did=POSTER, agent_id=1, raw_token="phase6-agent-token")


def test_guildPostOrder_sends_the_intended_worker(sent):
    # BASE: TypeError on the new keyword
    from agentvault_registry.mcp import tools_guild as G
    asyncio.run(G.guild_post_order(_agent_auth(), title="t", bounty="3", intended_worker_did=f" {WORKER} "))
    assert sent[-1][0] == "/api/v1/guild/orders" and sent[-1][1]["intended_worker_did"] == WORKER
    asyncio.run(G.guild_post_order(_agent_auth(), title="t", bounty="3", intended_worker_did=""))
    assert "intended_worker_did" not in sent[-1][1]


def test_guildPostOrder_advertises_intended_worker_did():
    # BASE: the property is absent
    from agentvault_registry.mcp import tools_guild as G
    from agentvault_registry.mcp import server
    for schemas in (G.GUILD_TOOL_SCHEMAS, server.ALL_TOOL_SCHEMAS):
        s = next(x for x in schemas if x["name"] == "theprotocol_guildPostOrder")
        prop = s["inputSchema"]["properties"]["intended_worker_did"]
        assert prop["type"] == "string" and prop["maxLength"] == 120


def test_the_column_is_migrated_and_modelled():
    # BASE: no attribute, no migration
    from agentvault_registry import models
    assert "intended_worker_did" in models.GuildWorkOrder.__table__.columns
    versions = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions"
    adds = [p.name for p in versions.glob("*.py")
            if "intended_worker_did" in p.read_text() and 'add_column("guild_work_orders"' in p.read_text()]
    assert len(adds) == 1, adds
