"""V0660 (b): acceptance tests on the rails that already settle work, a Guild work order's verify step and a contracts
v2 milestone's release step (services/quantum_acceptance.py, routers/quantum_acceptance.py). No new money rail.

- off (the source default) is byte-inert: the gate at verify and release returns before it reads anything, the three
  routes answer 403 and stay out of the OpenAPI schema;
- the payer names the acceptance test before the run (an open order, a milestone not yet accepted), once;
- a party hands in the receipt chain and the evidence after delivery; the registry checks every key against the keys
  registered here (or pinned in the agreement), recomputes the verdict and records hashes and the verdict, once;
- the verify and release steps settle such work only on a passing verdict under on (409 otherwise); shadow reports and
  lets them through; the reject step is untouched.

The agent card extension reads the same catalog: a card that offers one of the registry's templates under another rung
or method is told so.

RED on c533c1d11: none of these modules exist and neither step calls a gate. RED on 27494b422 (the review): the
agreement's event name is longer than guild_order_events.event_type; any party could sign any step; a pin could add a
key to a local agent; one agreement could settle two pieces of work; the legacy approve-completion route skipped the
gate; under off a malformed body was parsed before the switch refused.
RED on 2217ebc44 (the second review): the recorded agreement did not name the work it settles, so two orders with the
same agreement text shared one digest and a chain made for one could be handed in on the other (the digest refusal
only kept the second order from taking the same text at all). The registry now writes the work (rail, ref, milestone)
into the agreement it records, and the hand-in checks the agreement names the work it is handed in for.
"""
from __future__ import annotations

import ast
import asyncio
import json
import logging
import pathlib
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from agentvault_registry.services import quantum_receipts as qr

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"

POSTER = "did:theprotocol:poster-0001"
WORKER = "did:theprotocol:worker-0001"
VERIFIER = "did:theprotocol:verifier-0001"
STRANGER = "did:theprotocol:stranger-0001"
OID = "gwo_" + "a" * 24
CID = "ctr_" + "b" * 24
OID2 = "gwo_" + "c" * 24
REMOTE = "did:theprotocol:remote-provider-0001"   # a provider on another registry: no agent here
# the agreement's event name: guild_order_events.event_type is VARCHAR(24) (migration 0114)
AGREED_EVENT = "quantum_test_agreed"


@pytest.fixture
def mode(monkeypatch):
    monkeypatch.delenv("QUANTUM_WORKLOADS_MODE", raising=False)
    monkeypatch.setenv("GUILD_ENABLED", "true")
    monkeypatch.setenv("CONTRACTS_V2_ENABLED", "true")

    def set_mode(value):
        monkeypatch.setenv("QUANTUM_WORKLOADS_MODE", value)
    return set_mode


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ── a database that holds the rows the two rails keep ────────────────────────────────────────────────────────────────

class _Res:
    def __init__(self, rows=None, scalar=None):
        self._rows, self._scalar = rows or [], scalar

    def mappings(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)

    def scalar(self):
        return self._scalar


class _Db:
    """The tables the gate and the routes read and write, matched on their own SQL."""

    def __init__(self, *, order=None, contract=None, milestone=None, keys=None):
        self.order, self.contract, self.milestone = order, contract, milestone
        self.events = []                          # (table, ref, seq, type, actor, payload)
        self.keys = keys or {}                    # did -> jwk
        self.reads = 0
        self.commits = 0

    async def execute(self, stmt, params=None):
        self.reads += 1
        sql, p = " ".join(str(stmt).split()), params or {}
        if sql.startswith("SELECT * FROM guild_work_orders"):
            return _Res([self.order] if self.order and self.order["id"] == p["r"] else [])
        if sql.startswith("SELECT * FROM contracts WHERE"):
            return _Res([self.contract] if self.contract and self.contract["id"] == p["r"] else [])
        if sql.startswith("SELECT * FROM contract_milestones"):
            return _Res([self.milestone] if self.milestone and self.milestone["seq"] == p["s"] else [])
        if "FROM guild_order_events WHERE order_id = :r" in sql or "FROM contract_events WHERE contract_id = :r" in sql:
            table = "guild" if "guild_order_events" in sql else "contract"
            rows = [(e[3], json.dumps(e[5])) for e in sorted(self.events, key=lambda e: e[2])
                    if e[0] == table and e[1] == p["r"] and e[3] in (p["a"], p["v"])
                    and (table == "guild" or str(e[5].get("milestone")) == p["s"])]
            return _Res(rows)
        if "COALESCE(MAX(seq),0)+1 FROM guild_order_events" in sql or "COALESCE(MAX(seq),0)+1 FROM contract_events" in sql:
            return _Res(scalar=1 + len(self.events))
        if sql.startswith("INSERT INTO guild_order_events") or sql.startswith("INSERT INTO contract_events"):
            table = "guild" if "guild_order_events" in sql else "contract"
            self.events.append((table, p.get("o") or p.get("c"), p["q"], p["e"], p["a"], json.loads(p["p"])))
            return _Res()
        if sql.startswith("SELECT did FROM agents WHERE did IN"):
            return _Res([(d,) for d in p["d"] if d in self.keys])
        if "pg_advisory_xact_lock" in sql:
            return _Res()
        if sql.startswith("SELECT 1 FROM guild_order_events WHERE event_type") \
                or sql.startswith("SELECT 1 FROM contract_events WHERE event_type"):
            table = "guild" if "guild_order_events" in sql else "contract"
            hit = [e for e in self.events if e[0] == table and e[3] == p["a"]
                   and e[5].get("acceptance_digest") == p["d"]]
            return _Res([(1,)] if hit else [])
        if "FROM agents WHERE did IN" in sql:
            return _Res([(d, self.keys[d]) for d in p["d"] if d in self.keys])
        if "FROM agent_signing_keys" in sql:
            return _Res([])
        raise AssertionError(f"unexpected statement: {sql[:160]}")

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass


class _Blind:
    """A database the gate must never touch."""

    async def execute(self, *a, **k):
        raise AssertionError("read under QUANTUM_WORKLOADS_MODE=off")


@pytest.fixture(scope="module")
def keys():
    return {d: qr.new_signing_key() for d in (POSTER, WORKER, VERIFIER, STRANGER, REMOTE)}


FACTOR = {"template": "answer-check/v1.0", "problem": "factorisation", "params": {"n": "21"}, "verifier": VERIFIER}


def _work(rail="guild_work_order", ref=OID, seq=None):
    return {"rail": rail, "ref": ref, **({"seq": seq} if seq is not None else {})}


def _bound(agreement, **work):
    """The agreement as the registry records it: with the piece of work it settles."""
    return {**agreement, "work": _work(**work)}


def _job(keys, agreement, factors, passed, *, provider=WORKER, provider_key=None, submitter=POSTER,
         verifier=VERIFIER, work=None, bind=True):
    """A job run under the agreement as recorded for `work` (order A by default; bind=False: the bare agreement)."""
    if bind:
        agreement = {**agreement, "work": work or _work()}
    result = {"factors": factors}
    counts = {"circuits": {"main": {"10101": 64}}}
    k = provider_key or keys[provider]
    chain = qr.append_step([], job="job-q1", kind="circuit_submitted", participant=submitter,
                           role="client" if submitter == POSTER else "router",
                           body={"circuits_digest": qr.digest_of({"c": "shor-21"}), "format": "openqasm3", "shots": 64,
                                 "acceptance_digest": qr.digest_of(agreement)}, private_key=keys[submitter])
    chain = qr.append_step(chain, kind="backend_bound", participant=provider, role="provider",
                           body={"backend": "sim", "kind": "simulator", "calibration_digest": None}, private_key=k)
    chain = qr.append_step(chain, kind="run_executed", participant=provider, role="provider",
                           body={"shots": 64, "counts_digest": qr.digest_of(counts)}, private_key=k)
    chain = qr.append_step(chain, kind="result_reported", participant=provider, role="provider",
                           body={"from_counts_digest": qr.digest_of(counts), "result_digest": qr.digest_of(result)},
                           private_key=k)
    evidence = {"result": result}
    chain = qr.append_step(chain, kind="verdict", participant=verifier, role="verifier", body={
        "template": agreement["template"], "rung": 1, "passed": passed, "acceptance_digest": qr.digest_of(agreement),
        "evidence_digest": qr.digest_of(evidence), "false_accept_rate": None, "false_reject_rate": None},
        private_key=keys[verifier])
    return chain, evidence


def _registered(keys):
    return {d: qr.public_jwk(k) for d, k in keys.items() if d not in (STRANGER, REMOTE)}


def _order(status="open", spec=None, oid=OID):
    return {"id": oid, "poster_did": POSTER, "worker_did": WORKER, "status": status, "spec": spec}


def _agent(did):
    return SimpleNamespace(did=did)


# ── off is byte-inert ────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("rail,ref,seq", [("guild_work_order", OID, None), ("contract_milestone", CID, 1)])
def test_off_the_gate_reads_nothing(mode, rail, ref, seq):
    from agentvault_registry.services import quantum_acceptance as qa
    assert _run(qa.settlement_gate(_Blind(), rail, ref, seq)) is None


def test_off_the_routes_refuse_with_the_switchs_sentence(mode):
    from agentvault_registry.routers import quantum_acceptance as R
    from agentvault_registry.routers.quantum_agent_cards import require_quantum_workloads_served
    assert any(d.dependency is require_quantum_workloads_served for d in R.router.dependencies)
    with pytest.raises(HTTPException) as e:
        require_quantum_workloads_served()
    assert e.value.status_code == 403 and e.value.detail.startswith("quantum_workloads_off")


def test_main_mounts_the_router_documented_only_where_served():
    tree = ast.parse((_SRC / "main.py").read_text())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "include_router"
             and ast.unparse(n.args[0]) == "_quantum_acceptance_router.router"]
    assert len(calls) == 1
    kw = {k.arg: ast.unparse(k.value) for k in calls[0].keywords}
    assert kw.get("include_in_schema") == "_quantum_served()"


# ── the gate ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def _with_events(db, rail, ref, events):
    table = "guild" if rail == "guild_work_order" else "contract"
    for i, (etype, payload) in enumerate(events, start=1):
        db.events.append((table, ref, i, etype, "x", payload))
    return db


AGREED = {"acceptance_digest": qr.digest_of(_bound(FACTOR)), "template": FACTOR["template"], "rung": 1,
          "agreement": _bound(FACTOR)}


@pytest.mark.parametrize("events,code", [
    ([(AGREED_EVENT, AGREED)], "quantum_verdict_required"),
    ([(AGREED_EVENT, AGREED),
      ("quantum_verdict", {"acceptance_digest": AGREED["acceptance_digest"], "passed": False,
                           "template": "answer-check/v1.0", "reason": "the factors do not multiply to the number"})],
     "quantum_verdict_failed"),
])
def test_on_refuses_to_settle_without_a_passing_verdict(mode, events, code):
    from agentvault_registry.services import quantum_acceptance as qa
    mode("on")
    with pytest.raises(HTTPException) as e:
        _run(qa.settlement_gate(_with_events(_Db(), "guild_work_order", OID, events), "guild_work_order", OID))
    assert e.value.status_code == 409 and e.value.detail.startswith(code + ":")


def test_shadow_reports_what_on_would_refuse_and_lets_it_settle(mode, caplog):
    from agentvault_registry.services import quantum_acceptance as qa
    mode("shadow")
    db = _with_events(_Db(), "contract_milestone", CID, [(AGREED_EVENT, {**AGREED, "milestone": 1})])
    with caplog.at_level(logging.WARNING):
        assert _run(qa.settlement_gate(db, "contract_milestone", CID, 1)) is None
    assert "would be refused under QUANTUM_WORKLOADS_MODE=on: quantum_verdict_required" in caplog.text


def test_work_without_an_agreement_or_with_a_passing_verdict_settles(mode):
    from agentvault_registry.services import quantum_acceptance as qa
    mode("on")
    assert _run(qa.settlement_gate(_Db(), "guild_work_order", OID)) is None
    passed = [(AGREED_EVENT, AGREED),
              ("quantum_verdict", {"acceptance_digest": AGREED["acceptance_digest"], "passed": True})]
    assert _run(qa.settlement_gate(_with_events(_Db(), "guild_work_order", OID, passed), "guild_work_order", OID)) \
        is None
    # a verdict under another agreement's digest is no verdict for this one
    stale = [(AGREED_EVENT, AGREED),
             ("quantum_verdict", {"acceptance_digest": qr.digest_of({"other": 1}), "passed": True})]
    with pytest.raises(HTTPException) as e:
        _run(qa.settlement_gate(_with_events(_Db(), "guild_work_order", OID, stale), "guild_work_order", OID))
    assert e.value.detail.startswith("quantum_verdict_required")


def test_on_an_unreadable_test_refuses_shadow_lets_through(mode):
    from agentvault_registry.services import quantum_acceptance as qa

    class _Down:
        async def execute(self, *a, **k):
            raise RuntimeError("connection reset")
    mode("on")
    with pytest.raises(HTTPException) as e:
        _run(qa.settlement_gate(_Down(), "guild_work_order", OID))
    assert e.value.status_code == 503 and "connection reset" not in e.value.detail
    mode("shadow")
    assert _run(qa.settlement_gate(_Down(), "guild_work_order", OID)) is None


def _calls_before(fn: ast.AsyncFunctionDef, call: str, marker: str) -> bool:
    """Does `call` run in `fn` on a line before the first statement whose source holds `marker`?"""
    src = ast.unparse(fn)
    return call in src and marker in src and src.index(call) < src.index(marker)


def test_the_verify_and_release_steps_ask_the_gate_before_they_claim_the_money():
    guild = ast.parse((_SRC / "routers" / "guild.py").read_text())
    verify = next(n for n in ast.walk(guild) if isinstance(n, ast.AsyncFunctionDef) and n.name == "verify")
    src = ast.unparse(verify)
    gate = "settlement_gate(db, 'guild_work_order', oid)"
    assert src.count(gate) == 1
    assert src.index("if not body.accept:") < src.index(gate) < src.index("SET status='settling'"), \
        "after the reject branch (a dispute is never gated), before the claim"
    c2 = ast.parse((_SRC / "routers" / "contracts_v2.py").read_text())
    release = next(n for n in ast.walk(c2) if isinstance(n, ast.AsyncFunctionDef) and n.name == "release_milestone")
    assert _calls_before(release, "settlement_gate(db, 'contract_milestone', cid, seq)", "SET status='releasing'")
    reject = next(n for n in ast.walk(c2) if isinstance(n, ast.AsyncFunctionDef) and n.name == "reject_milestone")
    assert "settlement_gate" not in ast.unparse(reject)
    # the legacy approve-completion route releases milestone 1 of a ctr_ contract too: it asks the same gate
    c1 = ast.parse((_SRC / "routers" / "contracts.py").read_text())
    approve = next(n for n in ast.walk(c1)
                   if isinstance(n, ast.AsyncFunctionDef) and n.name == "approve_contract_completion")
    assert _calls_before(approve, "settlement_gate(db, 'contract_milestone', c['id'], 1)", "SET status='releasing'")
    assert ast.unparse(approve).count("settlement_gate") == 1


# ── the agreement, before the run ────────────────────────────────────────────────────────────────────────────────────

def test_the_poster_names_the_test_of_an_open_order_once(mode):
    from agentvault_registry.routers import quantum_acceptance as R
    mode("on")
    db = _Db(order=_order("open"))
    body = R.AgreeIn(rail="guild_work_order", ref=OID, agreement=FACTOR)
    out = _run(R.agree(body, agent=_agent(POSTER), db=db))
    assert out["acceptance_digest"] == qr.digest_of(_bound(FACTOR)) and out["rung"] == 1
    assert out["agreement"] == _bound(FACTOR), "the payer gets back the exact bytes the run is bound to"
    assert [(e[3], e[5]["acceptance_digest"], e[5]["agreement"]) for e in db.events] == [
        (AGREED_EVENT, qr.digest_of(_bound(FACTOR)), _bound(FACTOR))]
    with pytest.raises(HTTPException) as e:
        _run(R.agree(body, agent=_agent(POSTER), db=db))
    assert e.value.status_code == 409 and e.value.detail.startswith("quantum_acceptance_recorded")


@pytest.mark.parametrize("who,order,agreement,status_code,text", [
    (WORKER, _order("open"), FACTOR, 403, "Only the poster"),
    (POSTER, _order("awarded"), FACTOR, 409, "before the work is awarded"),
    (POSTER, _order("open", spec="eval_bounty://3/0.9\nfind it"), FACTOR, 409, "eval bounty"),
    (POSTER, _order("open"), {**FACTOR, "false_accept_rate": "0.1"}, 422, "quantum_acceptance_invalid"),
])
def test_an_agreement_out_of_turn_or_invalid_is_refused(mode, who, order, agreement, status_code, text):
    from agentvault_registry.routers import quantum_acceptance as R
    mode("shadow")
    db = _Db(order=order)
    with pytest.raises(HTTPException) as e:
        _run(R.agree(R.AgreeIn(rail="guild_work_order", ref=OID, agreement=agreement), agent=_agent(who), db=db))
    assert e.value.status_code == status_code and text in e.value.detail
    assert db.events == []


def test_a_contract_milestone_takes_its_test_while_the_offer_stands(mode):
    from agentvault_registry.routers import quantum_acceptance as R
    mode("on")
    contract = {"id": CID, "client_did": POSTER, "provider_did": None, "status": "offered", "legacy_ruc_id": None}
    db = _Db(contract=contract, milestone={"seq": 1, "status": "pending"})
    out = _run(R.agree(R.AgreeIn(rail="contract_milestone", ref=CID, seq=1, agreement=FACTOR),
                       agent=_agent(POSTER), db=db))
    assert out["seq"] == 1 and db.events[0][0] == "contract" and db.events[0][5]["milestone"] == 1
    assert db.events[0][5]["agreement"]["work"] == _work("contract_milestone", CID, 1)
    agreed = _Db(contract={**contract, "status": "agreed"}, milestone={"seq": 1, "status": "pending"})
    with pytest.raises(HTTPException) as e:
        _run(R.agree(R.AgreeIn(rail="contract_milestone", ref=CID, seq=1, agreement=FACTOR),
                     agent=_agent(POSTER), db=agreed))
    assert e.value.status_code == 409 and "before the provider accepts" in e.value.detail


# ── the verdict, after delivery ──────────────────────────────────────────────────────────────────────────────────────

def _agreed_order(keys, status="submitted"):
    db = _Db(order=_order(status), keys=_registered(keys))
    return _with_events(db, "guild_work_order", OID, [(AGREED_EVENT, AGREED)])


def test_a_checked_chain_records_hashes_and_the_verdict_once_and_then_settles(mode, keys):
    from agentvault_registry.routers import quantum_acceptance as R
    from agentvault_registry.services import quantum_acceptance as qa
    mode("on")
    db = _agreed_order(keys)
    chain, evidence = _job(keys, FACTOR, ["3", "7"], True)
    out = _run(R.hand_in_verdict(R.VerdictIn(rail="guild_work_order", ref=OID, chain=chain, evidence=evidence),
                                 agent=_agent(WORKER), db=db))
    assert out["recorded"] and out["ok"] and out["verdict"]["passed"] is True
    assert out["chain"]["key_binding"] == "pinned" and out["verdict"]["head"] == qr.step_digest(chain[-1])
    recorded = db.events[-1]
    assert recorded[3] == "quantum_verdict" and recorded[5]["passed"] is True
    stored = json.dumps(recorded[5])
    assert "shor-21" not in stored and '"factors"' not in stored and "10101" not in stored, "hashes and verdicts only"
    assert _run(qa.settlement_gate(db, "guild_work_order", OID)) is None
    with pytest.raises(HTTPException) as e:
        _run(R.hand_in_verdict(R.VerdictIn(rail="guild_work_order", ref=OID, chain=chain, evidence=evidence),
                               agent=_agent(POSTER), db=db))
    assert e.value.status_code == 409 and e.value.detail.startswith("quantum_verdict_recorded")


def test_a_failed_verdict_is_recorded_and_holds_the_money(mode, keys):
    from agentvault_registry.routers import quantum_acceptance as R
    from agentvault_registry.services import quantum_acceptance as qa
    mode("on")
    db = _agreed_order(keys)
    chain, evidence = _job(keys, FACTOR, ["1", "21"], False)
    out = _run(R.hand_in_verdict(R.VerdictIn(rail="guild_work_order", ref=OID, chain=chain, evidence=evidence),
                                 agent=_agent(POSTER), db=db))
    assert out["verdict"]["passed"] is False
    with pytest.raises(HTTPException) as e:
        _run(qa.settlement_gate(db, "guild_work_order", OID))
    assert e.value.detail.startswith("quantum_verdict_failed") and "not a factorisation" in e.value.detail


def test_a_key_not_registered_for_its_participant_is_refused_and_nothing_recorded(mode, keys):
    from agentvault_registry.routers import quantum_acceptance as R
    mode("on")
    db = _agreed_order(keys)
    chain, evidence = _job(keys, FACTOR, ["3", "7"], True, provider_key=keys[STRANGER])
    before = list(db.events)
    with pytest.raises(HTTPException) as e:
        _run(R.hand_in_verdict(R.VerdictIn(rail="guild_work_order", ref=OID, chain=chain, evidence=evidence),
                               agent=_agent(WORKER), db=db))
    assert e.value.status_code == 422 and e.value.detail.startswith("quantum_receipt_refused")
    assert "participant_key_unknown" in e.value.detail
    assert db.events == before


@pytest.mark.parametrize("who,status,code,text", [
    (STRANGER, "submitted", 403, "Only a party"),
    (WORKER, "awarded", 409, "a verdict follows its delivery"),
])
def test_a_verdict_from_outside_or_before_delivery_is_refused(mode, keys, who, status, code, text):
    from agentvault_registry.routers import quantum_acceptance as R
    mode("on")
    chain, evidence = _job(keys, FACTOR, ["3", "7"], True)
    with pytest.raises(HTTPException) as e:
        _run(R.hand_in_verdict(R.VerdictIn(rail="guild_work_order", ref=OID, chain=chain, evidence=evidence),
                               agent=_agent(who), db=_agreed_order(keys, status)))
    assert e.value.status_code == code and text in e.value.detail


def test_the_read_returns_the_agreement_and_the_verdict(mode, keys):
    from agentvault_registry.routers import quantum_acceptance as R
    mode("on")
    out = _run(R.read_acceptance(rail="guild_work_order", ref=OID, seq=None, db=_agreed_order(keys)))
    assert out["agreement"] == _bound(FACTOR) and out["verdict"] is None
    with pytest.raises(HTTPException) as e:
        _run(R.read_acceptance(rail="guild_work_order", ref=OID, seq=None, db=_Db()))
    assert e.value.status_code == 404 and e.value.detail.startswith("no_quantum_acceptance")


# ── the agent card extension reads the same catalog ──────────────────────────────────────────────────────────────────

def test_a_card_that_offers_a_catalog_template_under_another_rung_is_told(mode):
    from agentvault_registry.services import quantum_agent_card as qac
    card = json.loads(json.dumps(qac.schema()["examples"][0]))
    full = {"name": "q", "extensions": [card,
                                        {"uri": qac.PAYMENT_EXTENSION_URI, "params": {"base_rate": "1", "currency": "X"}}]}
    assert qac.check(full) == []
    card["params"]["evidence"]["acceptance_tests"][0]["template"] = "independent-repeat/v1.0"
    card["params"]["evidence"]["acceptance_tests"][1]["template"] = "answer-check/v1.0"
    card["params"]["evidence"]["acceptance_tests"][1]["method"] = "test_circuits"
    problems = qac.check(full)
    assert any("independent-repeat/v1.0 is a rung 2 independent_repeat test" in p for p in problems), problems


# ── the review of 27494b422: the rails' columns, who signs which step, pins, one agreement per piece of work ───────

def test_the_event_names_fit_the_rails_event_type_columns():
    """guild_order_events.event_type is VARCHAR(24) (0114), contract_events.event_type VARCHAR(32) (0129): a longer
    name fails the INSERT on a real database, which the fakes here cannot see."""
    import re
    from agentvault_registry.services import quantum_acceptance as qa
    versions = _SRC.parents[1] / "alembic" / "versions"
    widths = {}
    for name, table in (("0114_guild_work_exchange.py", "guild_order_events"), ("0129_contract_spine.py",
                                                                               "contract_events")):
        src = (versions / name).read_text()
        block = src[src.index(f"CREATE TABLE IF NOT EXISTS {table}"):]
        widths[table] = int(re.search(r"event_type\s+VARCHAR\((\d+)\)", block).group(1))
    assert widths == {"guild_order_events": 24, "contract_events": 32}
    altered = [f.name for f in versions.glob("*.py") if re.search(
        r"ALTER TABLE (guild_order_events|contract_events)[^;]*event_type", f.read_text())]
    assert altered == [], "a later migration changed the width: read it"
    assert qa.AGREED_EVENT == AGREED_EVENT
    for name in (qa.AGREED_EVENT, qa.VERDICT_EVENT):
        assert len(name) <= 24, name


def _agreed(keys, agreement, status="submitted", *, bind=True):
    db = _Db(order=_order(status), keys=_registered(keys))
    agreement = _bound(agreement) if bind else agreement
    return _with_events(db, "guild_work_order", OID, [(AGREED_EVENT, {
        "acceptance_digest": qr.digest_of(agreement), "template": agreement["template"],
        "rung": qr.TEMPLATES[agreement["template"]]["rung"], "agreement": agreement})])


def _refused(db, chain, evidence, who):
    from agentvault_registry.routers import quantum_acceptance as R
    before = list(db.events)
    with pytest.raises(HTTPException) as e:
        _run(R.hand_in_verdict(R.VerdictIn(rail="guild_work_order", ref=OID, chain=chain, evidence=evidence),
                               agent=_agent(who), db=db))
    assert db.events == before, "nothing is recorded"
    assert e.value.status_code == 422 and e.value.detail.startswith("quantum_receipt_refused"), e.value.detail
    return e.value.detail


def _recorded(db, chain, evidence, who):
    from agentvault_registry.routers import quantum_acceptance as R
    return _run(R.hand_in_verdict(R.VerdictIn(rail="guild_work_order", ref=OID, chain=chain, evidence=evidence),
                                  agent=_agent(who), db=db))


def test_the_payer_cannot_sign_the_providers_steps(mode, keys):
    """The review's probe: the poster signs the provider's steps with its own registered key and hands in a failed
    verdict before the worker hands in its pass. The keys are all real; the roles are not the parties of record."""
    mode("on")
    chain, evidence = _job(keys, FACTOR, ["1", "21"], False, provider=POSTER)
    detail = _refused(_agreed(keys, FACTOR), chain, evidence, POSTER)
    assert "quantum_receipt_role" in detail and "the worker of record" in detail and POSTER in detail


def test_the_worker_does_not_submit_the_circuits_it_is_judged_on(mode, keys):
    mode("on")
    chain, evidence = _job(keys, FACTOR, ["3", "7"], True, submitter=WORKER)
    detail = _refused(_agreed(keys, FACTOR), chain, evidence, WORKER)
    assert "quantum_receipt_role" in detail and "circuit_submitted" in detail and "the payer" in detail


def test_with_no_verifier_named_only_a_party_signs_the_verdict(mode, keys):
    mode("on")
    open_check = {k: v for k, v in FACTOR.items() if k != "verifier"}
    chain, evidence = _job(keys, open_check, ["3", "7"], True, verifier=VERIFIER)
    detail = _refused(_agreed(keys, open_check), chain, evidence, WORKER)
    assert "quantum_receipt_role" in detail and "names no verifier" in detail
    chain, evidence = _job(keys, open_check, ["3", "7"], True, verifier=WORKER)
    out = _recorded(_agreed(keys, open_check), chain, evidence, WORKER)
    assert out["recorded"] and out["verdict"]["passed"] is True and out["verdict"]["verifier"] == WORKER


def test_an_agreement_cannot_pin_a_key_for_an_agent_of_this_registry(mode, keys):
    """A pin adds a key for a DID with none here (a provider on another registry); it never adds one to a local agent,
    or the poster could sign in its worker's name."""
    from agentvault_registry.routers import quantum_acceptance as R
    mode("on")
    in_worker_name = {**FACTOR, "participants": {WORKER: qr.public_jwk(keys[POSTER])}}
    db = _Db(order=_order("open"), keys=_registered(keys))
    with pytest.raises(HTTPException) as e:
        _run(R.agree(R.AgreeIn(rail="guild_work_order", ref=OID, agreement=in_worker_name), agent=_agent(POSTER),
                     db=db))
    assert e.value.status_code == 422 and e.value.detail.startswith("quantum_acceptance_invalid")
    assert WORKER in e.value.detail and "registered here" in e.value.detail
    assert db.events == []
    # and an agreement that carries such a pin is refused at hand-in too, before any key is merged
    chain, evidence = _job(keys, in_worker_name, ["1", "21"], False, provider_key=keys[POSTER])
    detail = _refused(_agreed(keys, in_worker_name), chain, evidence, POSTER)
    assert WORKER in detail and "registered here" in detail


def test_a_provider_on_another_registry_signs_with_the_key_the_agreement_pins(mode, keys):
    mode("on")
    pinned = {**FACTOR, "participants": {REMOTE: qr.public_jwk(keys[REMOTE])}}
    chain, evidence = _job(keys, pinned, ["3", "7"], True, provider=REMOTE)
    out = _recorded(_agreed(keys, pinned), chain, evidence, WORKER)
    assert out["recorded"] and out["verdict"]["passed"] is True and out["chain"]["key_binding"] == "pinned"
    # unpinned, that provider is neither the worker of record nor named by the agreement
    chain, evidence = _job(keys, FACTOR, ["3", "7"], True, provider=REMOTE)
    detail = _refused(_agreed(keys, FACTOR), chain, evidence, WORKER)
    assert "the worker of record" in detail and REMOTE in detail


def _repeat(keys, provider):
    sub = qr.append_step([], job="job-q1-repeat", kind="circuit_submitted", participant=POSTER, role="client",
                         body={"circuits_digest": qr.digest_of({"c": "shor-21"}), "format": "openqasm3", "shots": 64,
                               "acceptance_digest": qr.digest_of({"x": 1})}, private_key=keys[POSTER])
    return qr.append_step(sub, kind="run_executed", participant=provider, role="provider",
                          body={"shots": 64, "counts_digest": qr.digest_of({"circuits": {}})},
                          private_key=keys[provider])


@pytest.mark.parametrize("provider,refused", [(POSTER, True), (WORKER, True), (REMOTE, False)])
def test_an_independent_repeat_runs_at_neither_party(keys, provider, refused):
    from agentvault_registry.services import quantum_acceptance as qa
    repeat = {"template": "independent-repeat/v1.0", "verifier": VERIFIER}
    chain, _ = _job(keys, repeat, ["3", "7"], True)
    problems = qa.role_problems(repeat, chain, {"repeat_chain": _repeat(keys, provider)}, payer=POSTER, worker=WORKER)
    assert bool(problems) is refused, problems
    if refused:
        assert any("repeat_chain" in p and "neither party" in p for p in problems), problems


def test_a_chain_made_for_one_piece_of_work_is_refused_for_any_other(mode, keys):
    """The second review: the same agreement text on two orders (a factorisation of the same n) and on a milestone.
    The registry records each with the work it settles, so the digests differ, and a chain made for order A is
    refused on order B and on the milestone, and accepted on A."""
    from agentvault_registry.routers import quantum_acceptance as R
    mode("on")
    a = _Db(order=_order("open", oid=OID), keys=_registered(keys))
    b = _Db(order=_order("open", oid=OID2), keys=_registered(keys))
    contract = {"id": CID, "client_did": POSTER, "provider_did": None, "status": "offered", "legacy_ruc_id": None}
    m = _Db(contract=contract, milestone={"seq": 1, "status": "pending"}, keys=_registered(keys))
    out_a = _run(R.agree(R.AgreeIn(rail="guild_work_order", ref=OID, agreement=FACTOR), agent=_agent(POSTER), db=a))
    out_b = _run(R.agree(R.AgreeIn(rail="guild_work_order", ref=OID2, agreement=FACTOR), agent=_agent(POSTER), db=b))
    out_m = _run(R.agree(R.AgreeIn(rail="contract_milestone", ref=CID, seq=1, agreement=FACTOR), agent=_agent(POSTER),
                         db=m))
    assert len({out_a["acceptance_digest"], out_b["acceptance_digest"], out_m["acceptance_digest"]}) == 3
    assert out_b["agreement"] == _bound(FACTOR, ref=OID2)
    assert out_m["agreement"] == _bound(FACTOR, rail="contract_milestone", ref=CID, seq=1)
    a.order["status"] = b.order["status"] = "submitted"
    contract["provider_did"], m.milestone["status"] = WORKER, "submitted"
    chain, evidence = _job(keys, FACTOR, ["3", "7"], True)          # made for order A
    for db, rail, ref, seq in ((b, "guild_work_order", OID2, None), (m, "contract_milestone", CID, 1)):
        before = list(db.events)
        with pytest.raises(HTTPException) as e:
            _run(R.hand_in_verdict(R.VerdictIn(rail=rail, ref=ref, seq=seq, chain=chain, evidence=evidence),
                                   agent=_agent(WORKER), db=db))
        assert e.value.status_code == 422 and e.value.detail.startswith("quantum_receipt_refused"), e.value.detail
        assert "not submitted under this agreement" in e.value.detail, e.value.detail
        assert db.events == before
    out = _run(R.hand_in_verdict(R.VerdictIn(rail="guild_work_order", ref=OID, chain=chain, evidence=evidence),
                                 agent=_agent(WORKER), db=a))
    assert out["recorded"] and out["verdict"]["passed"] is True
    assert out["verdict"]["acceptance_digest"] == out_a["acceptance_digest"]


def test_an_agreement_that_names_other_work_is_refused(mode):
    from agentvault_registry.routers import quantum_acceptance as R
    mode("on")
    db = _Db(order=_order("open", oid=OID2))
    with pytest.raises(HTTPException) as e:
        _run(R.agree(R.AgreeIn(rail="guild_work_order", ref=OID2, agreement=_bound(FACTOR, ref=OID)),
                     agent=_agent(POSTER), db=db))
    assert e.value.status_code == 422 and e.value.detail.startswith("quantum_acceptance_invalid")
    assert "names other work" in e.value.detail and OID2 in e.value.detail, e.value.detail
    assert db.events == []
    # naming its own work is the same agreement the registry would record
    out = _run(R.agree(R.AgreeIn(rail="guild_work_order", ref=OID2, agreement=_bound(FACTOR, ref=OID2)),
                       agent=_agent(POSTER), db=db))
    assert out["acceptance_digest"] == qr.digest_of(_bound(FACTOR, ref=OID2))


def test_an_agreement_recorded_without_its_work_settles_nothing(mode, keys):
    """An agreement recorded before the binding names no work: a chain run under it is refused at hand-in."""
    mode("on")
    chain, evidence = _job(keys, FACTOR, ["3", "7"], True, bind=False)
    assert qr.check_job(FACTOR, chain, evidence).ok, "the chain itself is sound"
    detail = _refused(_agreed(keys, FACTOR, bind=False), chain, evidence, WORKER)
    assert "names no work" in detail, detail


def test_off_a_body_is_not_read_before_the_switch_refuses(mode):
    """Under off the routes answer the switch's 403 before the body is parsed: a malformed body gets 403, not 422."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from agentvault_registry.routers import quantum_acceptance as R
    app = FastAPI()
    app.include_router(R.router)
    client = TestClient(app)
    for path in ("/api/v1/quantum/verdicts", "/api/v1/quantum/acceptance"):
        r = client.post(path, content='{"rail": "x"', headers={"content-type": "application/json"})
        assert r.status_code == 403 and r.json()["detail"].startswith("quantum_workloads_off"), (path, r.text)
    r = client.get("/api/v1/quantum/acceptance/no_such_rail/x")
    assert r.status_code == 403 and r.json()["detail"].startswith("quantum_workloads_off"), r.text


@pytest.mark.parametrize("method,path,kwargs", [
    ("post", "/api/v1/quantum/verdicts", {"content": '{"rail": "x"', "headers": {"content-type": "application/json"}}),
    ("post", "/api/v1/quantum/verdicts", {"content": "not json", "headers": {"content-type": "application/json"}}),
    ("post", "/api/v1/quantum/acceptance", {"content": '{"rail": "x"', "headers": {"content-type": "application/json"}}),
    ("post", "/api/v1/quantum/acceptance", {"content": "[1,", "headers": {"content-type": "text/plain"}}),
    ("get", "/api/v1/quantum/acceptance/no_such_rail/x?seq=abc", {}),
])
def test_off_each_route_refuses_a_malformed_request_with_the_switchs_403_in_the_registrys_app(mode, method, path,
                                                                                              kwargs):
    """The second review's item 2, through the app main.py builds (its middleware and error handlers), not a bare
    router: under off every route answers the switch's 403 whatever is sent, never a 422 that says the route is there.
    Green on 2217ebc44: c4a6b49ab already asks the switch before the body, the path or the query is parsed."""
    from fastapi.testclient import TestClient
    from agentvault_registry.main import app
    r = getattr(TestClient(app, raise_server_exceptions=False), method)(path, **kwargs)
    assert r.status_code == 403, (path, r.status_code, r.text[:300])
    assert "quantum_workloads_off" in r.text, r.text[:300]
