"""V0658 (k): one configurable slash order for every slash, with a cascade to the owner's other agents.

Before V0658 a local ruling drained the registry's `slash_waterfall` (bond, then locks, then liquid), while a peer's
accepted slash request (routers/federation_disputes.receive_slash_request) and an administrator's approval of one took
only the defendant's CACHED liquid balance. The lock step released the positions and moved only the 10% penalty: the
slashed units stayed with the agent on the TEG and the slash was a write to the cached balance (D6-460). Now every slash
drains the same order through services/slash_order.drain:
  - each step's capacity is read from the TEG (GET /admin/agent-locked-balance), never from the cached balances;
  - the lock step moves the slashed units to the treasury (the penalty on top of them);
  - a configurable cascade step (off by default, last in the order) drains the same developer's other agents on this
    registry through the same steps, never past the slash amount; a service account (developers
    .agents_unlisted_by_default) and an administrator's account are never part of a cascade;
  - every move goes agent -> treasury on the TEG's existing rails under its own Idempotency-Key (delta 0: the TEG's
    units are conserved) and is recorded once as SlashMoved, an audit record whose policy row skips the projection;
  - what nothing could cover is the shortfall, recorded on the settlement and in the summary event.

Doubles: the TEG (per-DID liquid and locked balances, the admin balance read, the unlock, the treasury receive with its
idempotency record) and the registry's database (rows in memory, read through the statements' own WHERE clauses). The
code under test is the real router, engine, slash order, force-unstake and bond forfeit.

RED on v0657/cut (e70fb58b2): services/slash_order does not exist, a peer's request takes the cached liquid balance
only, and force_unstake_for_slash moves only the penalty.
"""
from __future__ import annotations

import ast
import asyncio
import pathlib
import types
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from sqlalchemy.sql import operators as ops
from sqlalchemy.sql.elements import BinaryExpression, BindParameter, BooleanClauseList, False_, Grouping, Null, True_

from agentvault_registry import event_emitter as event_emitter_module
from agentvault_registry.models import Agent, CrossRegistrySettlement, Developer, PeerRegistry, ReputationBond, Stake
from tests._doubles import StrictEmitter

D = Decimal
HERE = pathlib.Path(__file__).resolve().parent
ORIGIN = "http://registry-a.peer.example"
PRESENTER = "spiffe://peer/service/registry"
COMPLAINANT = "did:theprotocol:eu.theprotocol.cloud:complainant-0000"
T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
CASCADE_ON = {"slash_waterfall": [{"source": "bond", "max_percent": 100}, {"source": "stake", "max_percent": 100},
                                  {"source": "liquid", "max_percent": 100}, {"source": "cascade", "max_percent": 100}]}


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _so():
    from agentvault_registry.services import slash_order
    return slash_order


# ── the TEG ──────────────────────────────────────────────────────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, status_code, body):
        self.status_code, self.body, self.text = status_code, body, str(body)

    def json(self):
        return self.body


class Teg:
    """Liquid and locked units per DID and the treasury's; every call it receives, in order."""
    def __init__(self):
        self.liquid, self.locked, self.treasury = {}, {}, D(0)
        self.records, self.calls = {}, []

    def total(self):
        return sum(self.liquid.values(), D(0)) + sum(self.locked.values(), D(0)) + self.treasury

    def balances(self, did):
        self.calls.append(("read", did))
        return self.liquid.get(did, D(0)), self.locked.get(did, D(0))

    def unlock(self, did, amount):
        if self.locked.get(did, D(0)) < amount:
            from agentvault_registry.teg_client import TEGBalanceError
            raise TEGBalanceError(f"Insufficient locked balance: {self.locked.get(did)} < {amount}")
        self.locked[did] -= amount
        self.liquid[did] = self.liquid.get(did, D(0)) + amount
        self.calls.append(("unlock", did, amount))

    def receive(self, body, key):
        did, amount, reason = body["source_agent_id"], D(body["amount"]), body["reason"]
        sig = (did, str(amount), reason)
        if key and key in self.records:
            seen, answer = self.records[key]
            if seen != sig:
                return _Resp(409, {"detail": "Idempotency key already used with different parameters"})
            return answer
        if self.liquid.get(did, D(0)) < amount:
            return _Resp(400, {"detail": f"Agent has {self.liquid.get(did, D(0))} AVT, requested {amount} AVT"})
        self.liquid[did] -= amount
        self.treasury += amount
        self.calls.append(("receive", did, amount, key, reason))
        answer = _Resp(200, {"transaction_id": f"tx-{len(self.calls)}", "status": "completed",
                             "new_source_balance": str(self.liquid[did])})
        if key:
            self.records[key] = (sig, answer)
        return answer

    def moves(self):
        return [c for c in self.calls if c[0] in ("unlock", "receive")]


class _TegClient:
    def __init__(self, teg):
        self.teg = teg

    async def get_balances_admin(self, did):
        return self.teg.balances(did)

    async def unlock_tokens(self, did, amount):
        self.teg.unlock(did, D(str(amount)))
        return types.SimpleNamespace(transaction_id="unlock", agent_id=did)


# ── the registry's database ──────────────────────────────────────────────────────────────────────────────────────────

_LIKE = {getattr(ops, n) for n in ("like_op",) if hasattr(ops, n)}
_NOT_LIKE = {getattr(ops, n) for n in ("not_like_op", "notlike_op") if hasattr(ops, n)}
_IS_NOT = {getattr(ops, n) for n in ("is_not", "isnot") if hasattr(ops, n)}
_NOT_IN = {getattr(ops, n) for n in ("not_in_op", "notin_op") if hasattr(ops, n)}


def _conditions(clause):
    if clause is None:
        return []
    if isinstance(clause, Grouping):
        return _conditions(clause.element)
    if isinstance(clause, BooleanClauseList):
        assert clause.operator is ops.and_, f"the test database reads AND only: {clause}"
        return [c for el in clause.clauses for c in _conditions(el)]
    assert isinstance(clause, BinaryExpression), f"the test database cannot read {type(clause).__name__}: {clause}"
    key = getattr(clause.left, "key", None)
    right = clause.right
    if isinstance(right, Grouping):
        right = right.element
    if isinstance(right, BindParameter):
        value = right.effective_value
    elif isinstance(right, True_):
        value = True
    elif isinstance(right, False_):
        value = False
    elif isinstance(right, Null):
        value = None
    else:
        raise AssertionError(f"the test database cannot read the right side of {clause}")
    return [(key, clause.operator, value)]


def _like(value, pattern):
    value = str(value or "")
    return value.startswith(pattern[:-1]) if pattern.endswith("%") else value == pattern


def _matches(row, conditions):
    for key, op, value in conditions:
        have = getattr(row, key, None)
        if op is ops.eq:
            ok = have == value
        elif op is ops.ne:
            ok = have != value
        elif op is ops.is_:
            ok = have is value or have == value
        elif op in _IS_NOT:
            ok = not (have is value or have == value)
        elif op is ops.in_op:
            ok = have in value
        elif op in _NOT_IN:
            ok = have not in value
        elif op in _LIKE:
            ok = _like(have, value)
        elif op in _NOT_LIKE:
            ok = not _like(have, value)
        else:
            raise AssertionError(f"the test database cannot apply {op}")
        if not ok:
            return False
    return True


class _Result:
    def __init__(self, rows, tuples=None):
        self.rows, self.tuples = rows, tuples

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None

    def scalars(self):
        return types.SimpleNamespace(all=lambda: list(self.rows), first=lambda: self.rows[0] if self.rows else None)

    def all(self):
        return list(self.tuples if self.tuples is not None else self.rows)


class Db:
    """Rows in memory, read through each statement's WHERE clause."""
    def __init__(self):
        self.tables = {Agent: [], Developer: [], Stake: [], ReputationBond: [], CrossRegistrySettlement: [],
                       PeerRegistry: []}
        self.added, self.commits = [], 0

    async def execute(self, stmt, *a, **k):
        if "federated_registry_compliance" in str(stmt):   # no registry is held in quarantine here
            return _Result([], [])
        desc = stmt.column_descriptions[0]
        entity = desc.get("entity")
        rows = [r for r in self.tables.get(entity, []) if _matches(r, _conditions(stmt.whereclause))]
        if desc.get("expr") is not entity:   # a column select: tuples of the named columns
            names = [d["name"] for d in stmt.column_descriptions]
            return _Result(rows, [tuple(getattr(r, n, None) for n in names) for r in rows])
        return _Result(rows)

    def add(self, obj):
        self.added.append(obj)
        if isinstance(obj, CrossRegistrySettlement):
            if any(s.id == obj.id for s in self.tables[CrossRegistrySettlement]):
                from sqlalchemy.exc import IntegrityError
                raise IntegrityError("duplicate", {}, Exception("pk"))
            self.tables[CrossRegistrySettlement].append(obj)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass

    async def flush(self):
        pass


# ── the world ────────────────────────────────────────────────────────────────────────────────────────────────────────

class World:
    def __init__(self, monkeypatch, policy=None):
        from agentvault_registry.routers import federation_disputes as fd
        from agentvault_registry.services import enforcement_engine as ee, force_unstake as fu, reputation_bond as rb
        try:
            so = _so()
        except ImportError:   # the base (v0657/cut) has no slash order: its own code runs against the same doubles
            so = None
        self.teg, self.db, self.emitter, self.callbacks = Teg(), Db(), StrictEmitter(), []
        self.policy = {} if policy is None else policy
        teg_client, world = _TegClient(self.teg), self

        class _Client:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, json=None, headers=None, **k):
                if "/treasury/receive" in url:
                    return world.teg.receive(json, (headers or {}).get("Idempotency-Key"))
                world.callbacks.append(json)
                return _Resp(200, {"ok": True})

        async def _policy(db):
            return world.policy

        async def _no_touch(db, did):
            return 0

        async def _no_operator(db, peer):
            return None
        import agentvault_registry.input_validators as iv
        import agentvault_registry.services.federation_license_gate as flg
        monkeypatch.setattr(httpx, "AsyncClient", _Client)
        if so is not None:
            monkeypatch.setattr(so, "get_teg_client", lambda: teg_client)
            monkeypatch.setattr(so, "get_event_emitter", lambda: world.emitter)
        monkeypatch.setattr(fu, "_force_unstake_service", None)
        monkeypatch.setattr(fu, "get_teg_client", lambda: teg_client)
        monkeypatch.setattr(fu, "get_event_emitter", lambda: world.emitter)
        monkeypatch.setattr(rb, "policy_json", _policy)
        monkeypatch.setattr(rb, "touch_native_card", _no_touch)
        monkeypatch.setattr(event_emitter_module, "get_event_emitter", lambda: world.emitter)
        monkeypatch.setattr(fd, "get_event_emitter", lambda: world.emitter)
        monkeypatch.setattr(ee, "get_event_emitter", lambda: world.emitter)
        monkeypatch.setattr(iv, "validate_webhook_url", lambda url, **kw: url)
        monkeypatch.setattr(flg, "resolve_peer_operator_did", _no_operator)
        self._next_id = 100

    def developer(self, **marks):
        self._next_id += 1
        dev = types.SimpleNamespace(id=self._next_id, is_admin=False, agents_unlisted_by_default=False,
                                    admin_treasury=False, admin_support=False, admin_enforcement=False,
                                    admin_federation=False, admin_platform=False, is_federation_shadow=False,
                                    deleted_at=None)
        for k, v in marks.items():
            setattr(dev, k, v)
        self.db.tables[Developer].append(dev)
        return dev

    def agent(self, dev, name, *, liquid=0, locked=0, bond=0, cached=None, status="active", age_days=10):
        """An agent of `dev`: its TEG balances (liquid, locked), its bond, and the registry's cached balances (`cached`,
        default the TEG's; a stale cache is how the tests tell a TEG read from a cache read)."""
        self._next_id += 1
        did = f"did:theprotocol:test:{name}"
        liquid_cache, staked_cache = (liquid, locked) if cached is None else cached
        a = types.SimpleNamespace(id=self._next_id, did=did, creator_developer_id=dev.id, status=status,
                                  created_at=T0 - timedelta(days=age_days), liquid_balance=D(str(liquid_cache)),
                                  staked_balance=D(str(staked_cache)), reputation_bond_amount=D(str(bond)),
                                  reputation_bond_status="locked" if bond else "none")
        self.db.tables[Agent].append(a)
        self.teg.liquid[did], self.teg.locked[did] = D(str(liquid)), D(str(locked))
        if locked:
            self._next_id += 1
            self.db.tables[Stake].append(types.SimpleNamespace(
                id=f"stake-{self._next_id}", agent_did=did, amount=D(str(locked)), is_active=True,
                staked_at=T0 - timedelta(days=30), unstaked_at=None, lock_period_days=30))
        if bond:
            self.db.tables[ReputationBond].append(types.SimpleNamespace(
                id=self._next_id, agent_did=did, amount=D(str(bond)), status="locked", funded_by="self",
                forfeit_ref=None, updated_at=None, forfeited_at=None, forfeit_reason=None))
        return a

    def bond_of(self, a):
        return next((b for b in self.db.tables[ReputationBond] if b.agent_did == a.did), None)

    def peer(self, *, auto_max=10_000):
        p = types.SimpleNamespace(id=1, name="registry-a", base_url=ORIGIN, status="ACTIVE", auto_slash_enabled=True,
                                  auto_slash_max_avt=D(auto_max), trust_domain="peer", peer_type="frame",
                                  spiffe_id=None)
        self.db.tables[PeerRegistry].append(p)
        return p

    def slash_request(self, defendant, amount, settlement_id="set-1"):
        from agentvault_registry.routers import federation_disputes as fd
        req = fd.SlashRequest(settlement_id=settlement_id, dispute_id=7, ruling="IN_FAVOR_OF_COMPLAINANT",
                              amount=amount, complainant_did=COMPLAINANT, defendant_did=defendant.did,
                              origin_registry_url=ORIGIN,
                              callback_url=f"{ORIGIN}/api/v1/federation/disputes/slash-confirmation")
        out = _run(fd.receive_slash_request(req, federation_identity=PRESENTER, db=self.db))
        settlement = next(s for s in self.db.tables[CrossRegistrySettlement] if s.id == settlement_id)
        return out, settlement

    def of_type(self, event_type):
        return [r for r in self.emitter.received if r.get("event_type") == event_type]

    def slash_moved(self):
        return [(r["data"]["agent_did"].rsplit(":", 1)[-1], r["data"]["source"], D(r["data"]["amount"]),
                 r["data"]["cascade"]) for r in self.of_type("SlashMoved")]


def _short(did):
    return did.rsplit(":", 1)[-1]


# ── 1. a peer's request drains the order: bond, then locks, then liquid ─────────────────────────────────────────────

def test_a_peer_request_drains_bond_then_locks_then_liquid(monkeypatch):
    w = World(monkeypatch)
    w.peer()
    dev = w.developer()
    # the TEG: 40 locked, 50 liquid; the registry's cache says 500 liquid, nothing locked (stale)
    d = w.agent(dev, "defendant", liquid=50, locked=40, bond=30, cached=(500, 0))
    before = w.teg.total()
    out, s = w.slash_request(d, 100)

    # bond 30 (the treasury keeps the escrow), locks 36 (40 released, the 10% penalty of 4 on top), liquid 34
    assert out["status"] == "slashed" and out["slashed_amount"] == 100 and out["shortfall"] == 0, out
    assert (s.status, s.slashed_amount, s.saga_state) == ("SLASHED", 100, "SLASH_CONFIRMED")
    assert w.slash_moved() == [("defendant", "bond", D(30), False), ("defendant", "stake", D(36), False),
                               ("defendant", "liquid", D(34), False)]
    assert w.bond_of(d).status == "forfeited" and w.bond_of(d).amount == 0
    # the TEG: the release, then its penalty and the slashed units, then the liquid units, each under its own key
    assert w.teg.moves() == [
        ("unlock", d.did, D(40)),
        ("receive", d.did, D(4), "dispute-slash-set-1-stake-penalty", "force_unstake_penalty"),
        ("receive", d.did, D(36), "dispute-slash-set-1-stake", "dispute_slash"),
        ("receive", d.did, D(34), "dispute-slash-set-1", "dispute_slash"),   # the liquid move keeps its key
    ]
    assert (w.teg.liquid[d.did], w.teg.locked[d.did], w.teg.treasury) == (D(16), D(0), D(74))
    assert w.teg.total() == before, "every move is agent -> treasury: nothing issued, nothing destroyed"
    # the origin is told what moved; DisputeSlash records the same amount
    assert [(c["status"], c["amount"]) for c in w.callbacks] == [("slashed", 100)]
    assert [r["amount"] for r in w.emitter.received if r["_method"] == "emit_dispute_slash"] == [100]


def test_every_capacity_is_read_from_the_teg_never_the_cache(monkeypatch):
    w = World(monkeypatch)
    w.peer()
    d = w.agent(w.developer(), "defendant", liquid=7, cached=(500, 0))
    out, s = w.slash_request(d, 100)
    # the TEG holds 7: the slash asks the TEG for 7, never for the 100 the stale cache could cover
    assert [m for m in w.teg.moves()] == [("receive", d.did, D(7), "dispute-slash-set-1", "dispute_slash")]
    assert (out["status"], out["slashed_amount"], out["shortfall"]) == ("slashed", 7, 93)
    assert s.status == "SLASHED" and s.slashed_amount == 7
    assert "Partial slash: 7/100" in s.error_message and "shortfall 93" in s.error_message, s.error_message
    assert d.liquid_balance == 0, "the cached balance follows the TEG's answer"


# ── 2. the lock step moves the slashed units (D6-460) ───────────────────────────────────────────────────────────────

def test_the_lock_step_moves_the_slashed_units_not_only_the_penalty(monkeypatch):
    from agentvault_registry.services import force_unstake as fu
    w = World(monkeypatch)
    d = w.agent(w.developer(), "staker", liquid=0, locked=100)
    before = w.teg.total()
    res = _run(fu.get_force_unstake_service().force_unstake_for_slash(
        db=w.db, agent_did=d.did, required_amount=45, admin_did="did:developer:1", reason="admin slash"))
    # 50 released (45 / 0.9), the penalty of 5 and the slashed 45 to the treasury: nothing of the slash stays liquid
    assert w.teg.locked[d.did] == D(50) and w.teg.liquid[d.did] == D(0) and w.teg.treasury == D(50), w.teg.calls
    assert [m[2] for m in w.teg.moves() if m[0] == "receive"] == [D(5), D(45)]
    assert res["slashed"] == 45 and res["penalty_moved"] == 5 and res["deficit"] == 0
    assert w.teg.total() == before
    # the cache follows the TEG: 50 released, 50 gone to the treasury
    assert (d.staked_balance, d.liquid_balance) == (D(50), D(0))


def test_the_lock_step_never_releases_more_than_the_teg_holds_locked(monkeypatch):
    from agentvault_registry.services import force_unstake as fu
    w = World(monkeypatch)
    # the registry's positions say 100 locked, the TEG holds 20
    d = w.agent(w.developer(), "staker", liquid=0, locked=100)
    w.teg.locked[d.did] = D(20)
    w.teg.liquid[d.did] = D(80)
    res = _run(fu.get_force_unstake_service().force_unstake_for_slash(
        db=w.db, agent_did=d.did, required_amount=45, admin_did="did:developer:1"))
    assert [m for m in w.teg.moves() if m[0] == "unlock"] == [("unlock", d.did, D(20))]
    assert res["slashed"] == 18 and res["penalty_moved"] == 2 and res["deficit"] == 27


# ── 3. a cascade across two agents of one developer ─────────────────────────────────────────────────────────────────

def _cascade_world(monkeypatch, **marks):
    w = World(monkeypatch, policy=CASCADE_ON)
    w.peer()
    dev = w.developer(**marks)
    d = w.agent(dev, "defendant", liquid=10, cached=(10, 0), age_days=5)
    # the most held first (the registry's cached holdings), each through bond, locks, liquid
    a = w.agent(dev, "rich", liquid=22, locked=20, bond=20, cached=(400, 100), age_days=50)
    b = w.agent(dev, "middle", liquid=50, cached=(300, 0), age_days=40)
    c = w.agent(dev, "poor", liquid=40, cached=(100, 0), age_days=60)
    other = w.agent(w.developer(), "someone-else", liquid=1000)
    return w, d, a, b, c, other


def test_a_cascade_drains_the_owners_other_agents_in_order_and_never_past_the_amount(monkeypatch):
    w, d, a, b, c, other = _cascade_world(monkeypatch)
    before = w.teg.total()
    out, s = w.slash_request(d, 100)
    # the defendant 10; "rich" 20 bond + 18 from its 20 locked + 22 liquid = 60; "middle" 30 of its 50; "poor" nothing
    assert w.slash_moved() == [("defendant", "liquid", D(10), False),
                               ("rich", "bond", D(20), True), ("rich", "stake", D(18), True),
                               ("rich", "liquid", D(22), True), ("middle", "liquid", D(30), True)]
    assert (out["status"], out["slashed_amount"], s.slashed_amount) == ("slashed", 100, 100)
    assert w.teg.liquid[b.did] == D(20) and w.teg.liquid[c.did] == D(40) and w.teg.liquid[other.did] == D(1000)
    assert w.teg.total() == before
    keys = [m[3] for m in w.teg.moves() if m[0] == "receive"]
    assert f"dispute-slash-set-1-cascade-{b.did}-liquid" in keys and f"dispute-slash-set-1-cascade-{a.did}-stake" in keys
    assert [(c_["status"], c_["amount"]) for c_ in w.callbacks] == [("slashed", 100)]


def test_the_cascade_is_off_by_default(monkeypatch):
    w, d, a, b, c, other = _cascade_world(monkeypatch)
    w.policy = {}   # the factory order: bond, locks, liquid; no cascade
    out, s = w.slash_request(d, 100)
    assert w.slash_moved() == [("defendant", "liquid", D(10), False)]
    assert (out["slashed_amount"], s.status) == (10, "SLASHED")
    from agentvault_registry.crud.crud_enforcement import DEFAULT_POLICY_JSON
    assert "cascade" not in [step["source"] for step in DEFAULT_POLICY_JSON["slash_waterfall"]]


def test_a_cascade_switched_off_in_the_order_drains_nothing_of_the_others(monkeypatch):
    # a control: green on the base too (it has no cascade at all)
    w, d, a, b, c, other = _cascade_world(monkeypatch)
    w.policy = {"slash_waterfall": CASCADE_ON["slash_waterfall"][:3] + [{"source": "cascade", "max_percent": 100,
                                                                         "enabled": False}]}
    out, _ = w.slash_request(d, 100)
    assert out["slashed_amount"] == 10 and w.teg.liquid[a.did] == D(22)


def test_the_cascade_cap_bounds_what_the_others_give(monkeypatch):
    w, d, a, b, c, other = _cascade_world(monkeypatch)
    w.policy = {"slash_waterfall": CASCADE_ON["slash_waterfall"][:3] + [{"source": "cascade", "max_percent": 25}]}
    out, _ = w.slash_request(d, 100)
    # the cascade gives at most 25 of the 100: the "rich" agent's bond 20, then 5 of its locks
    assert w.slash_moved() == [("defendant", "liquid", D(10), False), ("rich", "bond", D(20), True),
                               ("rich", "stake", D(5), True)]
    assert out["slashed_amount"] == 35


# ── 4. a service account is never touched ───────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("marks,why", [
    ({"agents_unlisted_by_default": True}, "a service account"),
    ({"is_admin": True}, "an administrator's account"),
    ({"admin_treasury": True}, "an administrator's account"),
])
def test_a_service_account_or_an_administrator_is_never_part_of_a_cascade(monkeypatch, marks, why):
    w, d, a, b, c, other = _cascade_world(monkeypatch, **marks)
    out, s = w.slash_request(d, 100)
    assert w.slash_moved() == [("defendant", "liquid", D(10), False)]
    assert all(w.teg.liquid[x.did] == v for x, v in ((a, D(22)), (b, D(50)), (c, D(40))))
    assert w.teg.locked[a.did] == D(20) and w.bond_of(a).amount == D(20)
    assert (out["slashed_amount"], s.status) == (10, "SLASHED")
    assert f"No cascade: {why}" in s.error_message, s.error_message


def test_a_deleted_agent_and_a_system_did_are_never_asked(monkeypatch):
    # a control: green on the base too (it asks no other agent)
    w = World(monkeypatch, policy=CASCADE_ON)
    w.peer()
    dev = w.developer()
    d = w.agent(dev, "defendant", liquid=0)
    gone = w.agent(dev, "gone", liquid=500, status="revoked")
    system = w.agent(dev, "x", liquid=500)
    system.did = "did:theprotocol:teg_system_treasury"
    w.teg.liquid[system.did] = D(500)
    out, s = w.slash_request(d, 50)
    assert out["slashed_amount"] == 0 and s.status == "FAILED"
    assert w.teg.liquid[gone.did] == D(500) and w.teg.liquid[system.did] == D(500) and w.teg.moves() == []


# ── 5. the shortfall is recorded when everything is drained ─────────────────────────────────────────────────────────

def test_the_shortfall_is_recorded_when_everything_is_drained(monkeypatch):
    w, d, a, b, c, other = _cascade_world(monkeypatch)
    out, s = w.slash_request(d, 500)
    # 10 + 60 + 50 + 40 = 160 in the order, 340 short; every agent of the developer is empty on the TEG
    assert (out["status"], out["slashed_amount"], out["shortfall"]) == ("slashed", 160, 340)
    assert (s.status, s.slashed_amount) == ("SLASHED", 160)
    assert "Partial slash: 160/500" in s.error_message and "shortfall 340" in s.error_message, s.error_message
    assert all(w.teg.liquid[x.did] == 0 for x in (d, a, b, c)) and w.teg.locked[a.did] == 0
    assert [(c_["status"], c_["amount"]) for c_ in w.callbacks] == [("slashed", 160)]
    assert "Partial slash: 160/500" in w.callbacks[0]["error_message"]


def test_a_local_ruling_drains_the_same_order_and_records_the_shortfall(monkeypatch):
    from agentvault_registry.services.enforcement_engine import EnforcementEngine
    w, d, a, b, c, other = _cascade_world(monkeypatch)
    action = types.SimpleNamespace(id=4242, agent_did=d.did, amount=500, action_type="slash_liquid",
                                   escalation_level=2)
    handled = _run(EnforcementEngine()._slash_waterfall(w.db, d, action, mode="enforce"))
    assert handled is True
    assert sum(m[2] for m in w.slash_moved()) == D(160)
    (applied,) = w.of_type("EnforcementSlashWaterfallApplied")
    assert applied["idempotency_key"] == "slashwf-applied-4242"
    assert (applied["data"]["requested"], applied["data"]["absorbed"], applied["data"]["shortfall"]) == ("500", "160", "340")
    assert applied["data"]["cascade"] == {"on": True, "refused": None, "agents_asked": 3}
    # the local ruling's own keys are the ones it always had
    keys = [m[3] for m in w.teg.moves() if m[0] == "receive"]
    assert keys[0] == "slash-4242-liquid" and all(k.startswith("slash-4242-") for k in keys)


def test_an_administrators_approval_drains_the_order(monkeypatch):
    from agentvault_registry.routers import federation_disputes as fd
    w = World(monkeypatch)
    d = w.agent(w.developer(), "defendant", liquid=50, locked=40, bond=30, cached=(0, 0))
    s = CrossRegistrySettlement(id="s-9", dispute_id=9, origin_registry_url=ORIGIN, defendant_registry_url="",
                                complainant_did=COMPLAINANT, defendant_did=d.did, requested_amount=D(100),
                                slashed_amount=0, minted_amount=0, status="PENDING_ADMIN_APPROVAL",
                                ruling="IN_FAVOR_OF_COMPLAINANT", callback_url=f"{ORIGIN}/cb", saga_state="INITIATED")
    w.db.tables[CrossRegistrySettlement].append(s)
    out = _run(fd.approve_settlement("s-9", None, current_admin=types.SimpleNamespace(id=1, email="a@example.test"),
                                     db=w.db))
    assert (out["status"], out["slashed_amount"], s.status) == ("SLASHED", 100, "SLASHED")
    assert [k for *_x, k, _r in [m for m in w.teg.moves() if m[0] == "receive"]] == [
        "settlement-approve-s-9-stake-penalty", "settlement-approve-s-9-stake", "settlement-approve-s-9-liquid"]
    assert [(c_["status"], c_["amount"]) for c_ in w.callbacks] == [("slashed", 100)]


# ── every move once: idempotent keys, one audit record per move ─────────────────────────────────────────────────────

def test_a_repeat_of_the_same_slash_moves_nothing_twice(monkeypatch):
    so = _so()
    w = World(monkeypatch)
    d = w.agent(w.developer(), "defendant", liquid=50, locked=40)
    first = _run(so.drain(w.db, d, 60, ref="slash-1", reason="enforcement_slash", reference_id="slash-1", actor="t"))
    treasury = w.teg.treasury
    second = _run(so.drain(w.db, d, 60, ref="slash-1", reason="enforcement_slash", reference_id="slash-1", actor="t"))
    assert first.moved == 60 and w.teg.treasury == treasury, "the second run under the same keys moved nothing"
    assert second.moved < 60


def test_each_move_is_recorded_once_as_an_audit_record(monkeypatch):
    w = World(monkeypatch)
    w.peer()
    d = w.agent(w.developer(), "defendant", liquid=50, locked=40, bond=30)
    w.slash_request(d, 100)
    moved = w.of_type("SlashMoved")
    assert [r["idempotency_key"] for r in moved] == ["slashmoved-dispute-slash-set-1-bond",
                                                     "slashmoved-dispute-slash-set-1-stake",
                                                     "slashmoved-dispute-slash-set-1"]
    assert all(r["data"]["slash_ref"] == "dispute-slash-set-1" and r["data"]["slash_of"] == d.did for r in moved)
    assert moved[1]["data"]["penalty"] == "4"


def test_slash_moved_is_an_audit_record_its_policy_row_skips_the_projection():
    from agentvault_registry.core.event_catalog import REGISTRY_EMITS, TEG_EMITS
    from agentvault_registry.event_emitter import BALANCE_MOVING_EVENT_TYPES
    path = HERE.parent / "alembic" / "versions" / "0212_slash_moved_policy.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    consts = {t.id: n.value for n in tree.body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
    assert ast.literal_eval(consts["revision"]) == "0212_slash_moved_policy"
    assert ast.literal_eval(consts["down_revision"]) == "0211_orgs_v2"
    rows = ast.literal_eval(consts["EMISSION_POLICY_ROWS"])
    assert rows == {"SlashMoved": (True, False, True)}, "registry emits, the TEG never, and the projection skips it"
    assert "SlashMoved" in REGISTRY_EMITS and "SlashMoved" not in TEG_EMITS
    assert "SlashMoved" not in BALANCE_MOVING_EVENT_TYPES


# ── a refused move is not counted, the next step drains ─────────────────────────────────────────────────────────────

def test_a_move_the_teg_refuses_is_not_counted_and_the_next_step_drains(monkeypatch):
    so = _so()
    w = World(monkeypatch)
    d = w.agent(w.developer(), "defendant", liquid=50, locked=0)
    w.policy = {"slash_waterfall": [{"source": "liquid", "max_percent": 100}, {"source": "bond", "max_percent": 100}]}
    real = w.teg.receive

    def refuse_once(body, key):
        w.teg.receive = real
        return _Resp(400, {"detail": "Insufficient agent balance for treasury receive"})
    w.teg.receive = refuse_once
    out = _run(so.drain(w.db, d, 20, ref="slash-2", reason="enforcement_slash", reference_id="slash-2", actor="t"))
    # refused, then asked again under the same key: the second answer is the TEG's
    assert out.moved == 20 and not out.failed


# ── the order's rules ───────────────────────────────────────────────────────────────────────────────────────────────

def test_the_order_accepts_a_cascade_step_last_and_refuses_it_anywhere_else():
    from agentvault_registry.crud import crud_enforcement as ce
    ok = CASCADE_ON
    assert ce.validate_policy_json(ok) == []
    off = {"slash_waterfall": ok["slash_waterfall"][:3] + [{"source": "cascade", "max_percent": 50, "enabled": False}]}
    assert ce.validate_policy_json(off) == []
    first = {"slash_waterfall": [{"source": "cascade", "max_percent": 100}] + ok["slash_waterfall"][:3]}
    assert any("must be the last step" in e for e in ce.validate_policy_json(first))
    assert any("enabled must be a boolean" in e for e in ce.validate_policy_json(
        {"slash_waterfall": [{"source": "liquid", "enabled": "yes"}]}))
    assert any("at least one of bond, stake or liquid" in e for e in ce.validate_policy_json(
        {"slash_waterfall": [{"source": "liquid", "enabled": False}, {"source": "cascade"}]}))


def test_the_cascade_statement_names_its_order():
    from sqlalchemy.dialects import postgresql
    so = _so()
    sql = str(so.cascade_statement(types.SimpleNamespace(did="did:theprotocol:test:x", creator_developer_id=7))
              .compile(dialect=postgresql.dialect()))
    assert "agents.creator_developer_id = " in sql and "agents.did != " in sql and "agents.status != " in sql
    assert "agents.did NOT LIKE" in sql
    assert "ORDER BY coalesce(agents.liquid_balance" in sql and "DESC, agents.created_at ASC, agents.id ASC" in sql
    assert "LIMIT" in sql and so.CASCADE_MAX_AGENTS == 25


# ── the console's and the MCP's doors ───────────────────────────────────────────────────────────────────────────────

def test_the_slash_order_has_its_admin_mcp_tools():
    from agentvault_registry.mcp import server_admin, tool_categories, tools_admin
    for name, fn, method in (("theprotocol_getSlashOrder", "get_slash_order", "GET"),
                             ("theprotocol_updateSlashOrder", "update_slash_order", "PUT")):
        assert server_admin.ADMIN_TOOL_DISPATCH[name] is getattr(tools_admin, fn)
        assert tool_categories.get_category(name, is_admin=True) == "enforcement-security"
        assert any(t["name"] == name for t in tools_admin.ADMIN_TOOL_SCHEMAS)
    upd = next(t for t in tools_admin.ADMIN_TOOL_SCHEMAS if t["name"] == "theprotocol_updateSlashOrder")
    assert set(upd["inputSchema"]["required"]) == {"order", "reason"}


def test_the_mcp_tools_call_the_policy_section(monkeypatch):
    from agentvault_registry.mcp import tools_admin
    calls = []

    async def _get(auth, path, params=None, **k):
        calls.append(("GET", path))
        return {"section": "slash_waterfall", "value": []}

    async def _put(auth, path, json_body=None, **k):
        calls.append(("PUT", path, json_body))
        return {"version": 3}
    monkeypatch.setattr(tools_admin, "_admin_get", _get)
    monkeypatch.setattr(tools_admin, "_admin_put", _put)
    _run(tools_admin.get_slash_order(object()))
    order = [{"source": "liquid", "max_percent": 100}]
    _run(tools_admin.update_slash_order(object(), order, "the cascade waits"))
    assert calls == [("GET", "/api/v1/admin/enforcement/policy/section/slash_waterfall"),
                     ("PUT", "/api/v1/admin/enforcement/policy/section/slash_waterfall",
                      {"value": order, "reason": "the cascade waits"})]
