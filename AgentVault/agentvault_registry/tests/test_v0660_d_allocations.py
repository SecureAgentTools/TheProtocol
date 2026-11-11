"""V0660 (d): the allocation-frame profile for research consortia, with a cap per declared allocation.

A frame of a research centre declares its allocations in QUANTUM_ALLOCATION_PROFILE (a name, a version and, per
allocation, an id, the holder agent and a cap in the frame's unit). A treasury grant whose reason is `allocation:<id>`
draws on that allocation and is held against its cap before anything moves (services/quantum_workloads.
allocation_grant_hold, around the TEG call of routers/teg_integration._fund_agent_from_treasury_internal):

  off (the source default)  nothing is read, nothing is held: the funding rail is the one it was;
  shadow                    the decision is made and reported, the grant goes ahead and is counted;
  on                        a grant past the cap, for an allocation the profile does not declare or for another holder
                            is refused (403) before the TEG is called.

The amount granted under an allocation is counted in exchange_flags under a row lock, and given back only when the TEG
demonstrably moved nothing or says itself how much it moved: the ledger gate's refusal, a request that never left this
registry (it could not connect), or the TEG's own `exhausted` account (its funded amount stays counted, only the rest is
given back). A balance read never gives room back (a cached balance can be stale, and the waterfall can commit some legs
before it answers 400), so any other failure keeps the whole amount counted: the room left can only shrink, never grow,
and the cap is never exceeded. The grant's ledger event (memo treasury_fund:allocation:<id>) is asserted on a strict
emitter double, since the ledger is how a cap is checked from outside.

Review round (V0660 (d), on e47e5ba27): red there are the partial-leg and stale-balance tests (the room was given back
in full on the balance check), the refusal without the TEG's own account, the inconsistent exhausted answers, the
requests that never left (kept counted there), the padded profile name and the receipt assertion's emitter.

RED on 4b79322d7 (origin/v0658/cut): the module does not exist and the funding rail checks no allocation. The "off" and
"no allocation named" tests are the byte-inert guard (green on the base, they must stay green).
"""
from __future__ import annotations

import json
import logging
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from agentvault_registry.routers import teg_integration as ti
from agentvault_registry.services import ledger_unavailable as lu

HOLDER = "did:theprotocol:eu.example:0b0e7c1a-5a0e-4c39-9d43-1f0d6d2b7c01"
OTHER = "did:theprotocol:eu.example:6c1f0e0a-1f2b-4a55-8c3d-2a9e4d1b0f02"
PROFILE = {"name": "Example consortium, 2026 call", "version": 1, "unit": "QPU",
           "allocations": [{"id": "proj-017", "holder": HOLDER, "cap": "1000", "note": "QC chemistry, call 2026-1"},
                           {"id": "proj-018", "holder": OTHER, "cap": 250}]}
KEY = "quantum_alloc:proj-017"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k in ("QUANTUM_WORKLOADS_MODE", "QUANTUM_ALLOCATION_PROFILE", "GUILD_ENABLED", "CONTRACTS_V2_ENABLED"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("FRAME_CURRENCY", "QPU")


@pytest.fixture(autouse=True)
def emitter(monkeypatch):
    """The funding helper's emitter: strict (the real signatures) and recording, so a grant's ledger event is asserted."""
    from agentvault_registry import event_emitter
    from tests._doubles import StrictEmitter
    strict = StrictEmitter()
    monkeypatch.setattr(event_emitter, "get_event_emitter", lambda: strict)
    return strict


def _qw():
    from agentvault_registry.services import quantum_workloads
    return quantum_workloads


# ── the profile ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_valid_profile_parses_and_is_summarised_by_its_hash(monkeypatch):
    qw = _qw()
    assert qw.validate_profile(PROFILE, "QPU") == []
    monkeypatch.setenv("QUANTUM_ALLOCATION_PROFILE", json.dumps(PROFILE))
    summary = qw.allocation_profile_summary()
    assert summary == {"state": "declared", "name": PROFILE["name"], "version": 1, "allocation_count": 2,
                       "profile_hash": qw.profile_hash(PROFILE)}
    assert qw.profile_hash(PROFILE).startswith("sha256:") and len(qw.profile_hash(PROFILE)) == 71
    # the hash is over the canonical document, so key order does not move it
    assert qw.profile_hash(json.loads(json.dumps(PROFILE, sort_keys=True))) == qw.profile_hash(PROFILE)


def _with(**changes):
    doc = json.loads(json.dumps(PROFILE))
    for path, value in changes.items():
        cursor = doc
        parts = path.split("__")
        for p in parts[:-1]:
            cursor = cursor[int(p)] if p.isdigit() else cursor[p]
        last = parts[-1]
        if value is _DROP:
            del cursor[int(last) if last.isdigit() else last]
        else:
            cursor[int(last) if last.isdigit() else last] = value
    return doc


_DROP = object()


@pytest.mark.parametrize("doc,needle", [
    ([], "object"),
    (_with(name=_DROP), "name"),
    (_with(name=""), "name"),
    (_with(name="   "), "name"),
    (_with(name="  " + "n" * 120), "name"),           # the card publishes the name as written: 122 characters
    (_with(version=0), "version"),
    (_with(version=True), "version"),
    (_with(unit="ECU"), "unit"),
    (_with(colour="blue"), "colour"),
    (_with(allocations=[]), "allocations"),
    (_with(allocations__0__id="Proj 17"), "id"),
    (_with(allocations__1__id="proj-017"), "twice"),
    (_with(allocations__0__holder="someone"), "holder"),
    (_with(allocations__0__cap="0"), "cap"),
    (_with(allocations__0__cap="-5"), "cap"),
    (_with(allocations__0__cap="lots"), "cap"),
    (_with(allocations__0__cap="NaN"), "cap"),
    (_with(allocations__0__cap=True), "cap"),
    (_with(allocations__0__share="1"), "share"),
])
def test_an_invalid_profile_says_what_is_wrong_and_publishes_as_invalid(monkeypatch, doc, needle):
    qw = _qw()
    errors = qw.validate_profile(doc, "QPU")
    assert errors and any(needle in e for e in errors), errors
    monkeypatch.setenv("QUANTUM_ALLOCATION_PROFILE", json.dumps(doc))
    assert qw.allocation_profile_summary() == {"state": "invalid"}


def test_too_many_allocations_is_invalid():
    qw = _qw()
    doc = _with(allocations=[{"id": f"p{i:04d}", "holder": HOLDER, "cap": "1"} for i in range(qw.MAX_ALLOCATIONS + 1)])
    assert any("allocations" in e for e in qw.validate_profile(doc, "QPU"))


def test_no_profile_and_a_text_that_is_not_json(monkeypatch):
    qw = _qw()
    assert qw.allocation_profile_summary() is None
    monkeypatch.setenv("QUANTUM_ALLOCATION_PROFILE", "   ")
    assert qw.allocation_profile_summary() is None
    monkeypatch.setenv("QUANTUM_ALLOCATION_PROFILE", "{allocations: 1}")
    assert qw.allocation_profile_summary() == {"state": "invalid"}


# ── the decision ──────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("profile,allocation,holder,amount,granted,code", [
    (None, "proj-017", HOLDER, "1", "0", "allocation_profile_missing"),
    (PROFILE, "proj-099", HOLDER, "1", "0", "allocation_unknown"),
    (PROFILE, "proj-017", OTHER, "1", "0", "allocation_holder_mismatch"),
    (PROFILE, "proj-017", HOLDER, "200", "900", "allocation_cap_exceeded"),
    (PROFILE, "proj-017", HOLDER, "100", "900", None),          # exactly the cap is within it
    (PROFILE, "proj-018", OTHER, "250", "0", None),
    (PROFILE, "proj-018", OTHER, "250.000001", "0", "allocation_cap_exceeded"),
])
def test_the_decision(profile, allocation, holder, amount, granted, code):
    allowed, got, sentence = _qw().evaluate_grant(profile, allocation, holder, Decimal(amount), Decimal(granted))
    assert got == code and allowed is (code is None)
    assert isinstance(sentence, str) and sentence
    if code == "allocation_cap_exceeded":
        assert allocation in sentence and "cap" in sentence


def test_a_reason_names_an_allocation_only_by_its_prefix():
    qw = _qw()
    assert qw.allocation_named_by("allocation:proj-017") == "proj-017"
    for reason in ("admin_grant", "genesis_grant", "allocation", "allocations:proj-017", "", None, "x allocation:a"):
        assert qw.allocation_named_by(reason) is None


# ── the tally ─────────────────────────────────────────────────────────────────────────────────────────────────────────

class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        assert self.value is not None, "the row the insert made is gone"
        return self.value

    def scalar_one_or_none(self):
        return self.value


class _Tally:
    """exchange_flags as the hold's own sessions see it: writes land at commit, a rollback drops them."""

    def __init__(self, rows=None):
        self.rows = dict(rows or {})
        self.sessions = 0
        self.locked = []

    def factory(self):
        tally = self

        class _Session:
            def __init__(self):
                self.pending = {}

            async def __aenter__(self):
                tally.sessions += 1
                return self

            async def __aexit__(self, *a):
                self.pending = {}
                return False

            async def execute(self, stmt):
                compiled = stmt.compile(dialect=postgresql.dialect())
                params = compiled.params
                key = params.get("key") or next(v for n, v in params.items() if n.startswith("key"))
                if stmt.is_insert:
                    if key not in tally.rows and key not in self.pending:
                        self.pending[key] = params["value"]
                    return _Result(None)
                if stmt.is_select:
                    assert "FOR UPDATE" in str(compiled), "a tally is read under its row lock"
                    tally.locked.append(key)
                    return _Result(self.pending.get(key, tally.rows.get(key)))
                if stmt.is_update:
                    self.pending[key] = params["value"]
                    return _Result(None)
                raise AssertionError(f"unexpected statement {compiled}")

            async def commit(self):
                tally.rows.update(self.pending)
                self.pending = {}

            async def rollback(self):
                self.pending = {}

        return _Session


def _no_session():
    raise AssertionError("the hold opened a session")


def test_the_tally_statements_lock_the_row_and_never_duplicate_it():
    qw = _qw()
    insert = str(qw._tally_insert(KEY).compile(dialect=postgresql.dialect()))
    select = str(qw._tally_select(KEY).compile(dialect=postgresql.dialect()))
    update = qw._tally_update(KEY, Decimal("1E+3")).compile(dialect=postgresql.dialect())
    assert "INSERT INTO exchange_flags" in insert and "ON CONFLICT (key) DO NOTHING" in insert
    assert select.startswith("SELECT exchange_flags.value") and select.endswith("FOR UPDATE")
    assert "UPDATE exchange_flags SET value=" in str(update) and "updated_at=now()" in str(update)
    assert update.params["value"] == "1000"                    # never an exponent on the wire (1E+3)
    assert qw.tally_key("proj-017") == KEY and len(qw.tally_key("a" * 48)) <= 64   # exchange_flags.key is 64 wide


# ── the funding rail ──────────────────────────────────────────────────────────────────────────────────────────────────

def _ok(balance="400"):
    return httpx.Response(200, json={"transaction_id": "tx-1", "new_target_balance": balance,
                                     "new_treasury_balance": "99000"})


def _gate():
    return httpx.Response(503, json={"detail": f"{lu.MARKER} {lu.SENTENCE}", "code": lu.CODE, "status": 503},
                          headers={"Retry-After": "20"})


def _teg(monkeypatch, *answers):
    """httpx.AsyncClient for the funding helper: each call takes the next answer (a response, or an exception to raise)."""
    queue, calls = list(answers), []

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def _next(self, method, url):
            calls.append((method, url))
            answer = queue.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer

        async def post(self, url, json=None, headers=None, timeout=None):
            return await self._next("POST", url)

        async def get(self, url, headers=None, timeout=None):
            return await self._next("GET", url)

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    return calls


class _Rows:
    def __init__(self, agent):
        self.agent = agent

    def scalar_one_or_none(self):
        return self.agent


class _FundDb:
    def __init__(self, agent=None):
        self.agent = agent

    async def execute(self, *a, **k):
        return _Rows(self.agent)

    async def commit(self):
        pass


def _grant(amount, reason="allocation:proj-017", target=HOLDER):
    return ti.TreasuryFundAgentRequest(target_agent_did=target, amount=amount, reason=reason)


async def _fund(db, request):
    return await ti._fund_agent_from_treasury_internal(db, request, actor_label="admin@frame.example")


def _arm(monkeypatch, mode, tally):
    if mode is not None:
        monkeypatch.setenv("QUANTUM_WORKLOADS_MODE", mode)
    monkeypatch.setenv("QUANTUM_ALLOCATION_PROFILE", json.dumps(PROFILE))
    monkeypatch.setattr(_qw(), "_session_factory", tally.factory if tally is not None else _no_session)


@pytest.mark.parametrize("mode", [None, "off", "maybe"])
async def test_off_reads_nothing_and_the_grant_goes_ahead(monkeypatch, mode):
    if mode is not None:
        monkeypatch.setenv("QUANTUM_WORKLOADS_MODE", mode)
    monkeypatch.setenv("QUANTUM_ALLOCATION_PROFILE", json.dumps(PROFILE))
    try:
        monkeypatch.setattr(_qw(), "_session_factory", _no_session)
    except ImportError:        # the base has no module: nothing to read anyway
        pass
    calls = _teg(monkeypatch, _ok())
    out = await _fund(_FundDb(), _grant("5000"))          # five times the cap: off checks nothing
    assert out["transaction_id"] == "tx-1" and [m for m, _ in calls] == ["POST"]


async def test_a_grant_naming_no_allocation_is_not_held(monkeypatch):
    monkeypatch.setenv("QUANTUM_WORKLOADS_MODE", "on")
    try:
        monkeypatch.setattr(_qw(), "_session_factory", _no_session)
    except ImportError:
        pass
    calls = _teg(monkeypatch, _ok())
    out = await _fund(_FundDb(), _grant("5000", reason="admin_grant"))
    assert out["transaction_id"] == "tx-1" and len(calls) == 1


async def test_on_refuses_a_grant_past_the_cap_before_the_teg_is_called(monkeypatch):
    tally = _Tally({KEY: "900"})
    _arm(monkeypatch, "on", tally)
    calls = _teg(monkeypatch, _ok())
    with pytest.raises(HTTPException) as e:
        await _fund(_FundDb(), _grant("200"))
    assert e.value.status_code == 403 and str(e.value.detail).startswith("allocation_cap_exceeded:")
    assert "proj-017" in e.value.detail and "1000" in e.value.detail
    assert calls == [] and tally.rows == {KEY: "900"} and tally.locked == [KEY]


async def test_on_lets_a_grant_within_the_cap_through_and_counts_it(monkeypatch, emitter):
    tally = _Tally()
    _arm(monkeypatch, "on", tally)
    calls = _teg(monkeypatch, _ok())
    await _fund(_FundDb(), _grant("400"))
    assert len(calls) == 1 and tally.rows == {KEY: "400"}
    # the ledger records the grant with the allocation in its memo: that is how a cap is checked from outside
    moves = [r for r in emitter.received if r["_method"] == "emit_tokens_transferred"]
    assert len(moves) == 1, emitter.received
    assert moves[0]["memo"] == "treasury_fund:allocation:proj-017" and moves[0]["amount"] == "400"
    assert moves[0]["to_agent"] == HOLDER and moves[0]["transaction_id"] == "tx-1"
    calls = _teg(monkeypatch, _ok())
    await _fund(_FundDb(), _grant("600"))                  # 400 + 600 is the cap exactly
    assert tally.rows == {KEY: "1000"}
    calls = _teg(monkeypatch, _ok())
    with pytest.raises(HTTPException):
        await _fund(_FundDb(), _grant("0.000001"))
    assert calls == [] and tally.rows == {KEY: "1000"}


@pytest.mark.parametrize("reason,target,code", [
    ("allocation:proj-099", HOLDER, "allocation_unknown"),
    ("allocation:proj-017", OTHER, "allocation_holder_mismatch"),
    ("allocation:Not An Id", HOLDER, "allocation_unknown"),
])
async def test_on_refuses_an_undeclared_allocation_or_another_holder_without_a_tally(monkeypatch, reason, target, code):
    _arm(monkeypatch, "on", None)                          # no session may open
    calls = _teg(monkeypatch, _ok())
    with pytest.raises(HTTPException) as e:
        await _fund(_FundDb(), _grant("1", reason=reason, target=target))
    assert e.value.status_code == 403 and str(e.value.detail).startswith(code + ":") and calls == []


async def test_on_with_no_profile_refuses_a_grant_that_names_an_allocation(monkeypatch):
    monkeypatch.setenv("QUANTUM_WORKLOADS_MODE", "on")
    monkeypatch.setattr(_qw(), "_session_factory", _no_session)
    calls = _teg(monkeypatch, _ok())
    with pytest.raises(HTTPException) as e:
        await _fund(_FundDb(), _grant("1"))
    assert str(e.value.detail).startswith("allocation_profile_missing:") and calls == []
    monkeypatch.setenv("QUANTUM_ALLOCATION_PROFILE", "{broken")
    with pytest.raises(HTTPException) as e:
        await _fund(_FundDb(), _grant("1"))
    assert str(e.value.detail).startswith("allocation_profile_invalid:") and calls == []


async def test_a_grant_the_ledger_gate_refused_gives_its_room_back(monkeypatch):
    tally = _Tally({KEY: "100"})
    _arm(monkeypatch, "on", tally)
    _teg(monkeypatch, _gate())
    with pytest.raises(HTTPException) as e:
        await _fund(_FundDb(), _grant("300"))
    assert e.value.status_code == 503 and e.value.detail.startswith(lu.MARKER)
    assert tally.rows == {KEY: "100"} and tally.locked == [KEY, KEY]      # reserved, then given back


def _exhausted(funded, legs, total="1000"):
    """The TEG's own account of a waterfall it could not finish (endpoints_treasury.reward_fund): 400, the legs it
    committed and the amount they moved."""
    return httpx.Response(400, json={"status": "exhausted", "target_agent_id": HOLDER, "total_amount": total,
                                     "funded_amount": funded, "shortfall": "0", "legs": legs,
                                     "detail": "Funding exhausted."})


_LEG = [{"source": "fee_collector", "amount": "500", "transaction_id": "tx-leg-1"}]


async def test_an_exhausted_answer_with_a_partial_leg_keeps_what_moved_counted(monkeypatch, emitter):
    tally = _Tally()
    _arm(monkeypatch, "on", tally)
    # cap 1000: the first grant of 1000 moves 500 (one leg committed) and answers 400 exhausted; the balance read
    # shows 500 arrived, under the 90% the recovery path asks for
    _teg(monkeypatch, _exhausted("500", _LEG), httpx.Response(200, json={"balance": "500"}))
    with pytest.raises(HTTPException) as e:
        await _fund(_FundDb(SimpleNamespace(liquid_balance=Decimal("0"))), _grant("1000"))
    assert e.value.status_code == 400
    assert tally.rows == {KEY: "500"}                      # what moved stays counted, only the shortfall is given back
    calls = _teg(monkeypatch, _ok())
    with pytest.raises(HTTPException) as e:                # so a second grant of 1000 cannot pass the cap
        await _fund(_FundDb(), _grant("1000"))
    assert e.value.status_code == 403 and str(e.value.detail).startswith("allocation_cap_exceeded:") and calls == []


async def test_an_exhausted_answer_that_moved_nothing_gives_the_room_back(monkeypatch):
    tally = _Tally({KEY: "100"})
    _arm(monkeypatch, "on", tally)
    _teg(monkeypatch, _exhausted("0", []), httpx.Response(200, json={"balance": "0"}))
    with pytest.raises(HTTPException) as e:
        await _fund(_FundDb(SimpleNamespace(liquid_balance=Decimal("0"))), _grant("300"))
    assert e.value.status_code == 400
    assert tally.rows == {KEY: "100"}


@pytest.mark.parametrize("funded,legs", [
    ("0", _LEG),                     # nothing funded, yet a leg committed
    ("301", _LEG),                   # more than the grant
    ("-1", []),
    ("lots", []),
    ("NaN", []),
    (None, []),
])
async def test_an_exhausted_answer_that_does_not_add_up_keeps_the_whole_amount_counted(monkeypatch, funded, legs):
    tally = _Tally({KEY: "100"})
    _arm(monkeypatch, "on", tally)
    _teg(monkeypatch, _exhausted(funded, legs, total="300"), httpx.Response(200, json={"balance": "0"}))
    with pytest.raises(HTTPException):
        await _fund(_FundDb(SimpleNamespace(liquid_balance=Decimal("0"))), _grant("300"))
    assert tally.rows == {KEY: "400"}


async def test_a_refusal_without_the_tegs_own_account_keeps_the_room_counted(monkeypatch):
    tally = _Tally({KEY: "100"})
    _arm(monkeypatch, "on", tally)
    # the TEG answers 400 with no account of what it moved; the balance read shows the holder at 0, but a balance read
    # is not evidence that nothing moved (the waterfall commits legs before it answers, a cached balance can be stale)
    _teg(monkeypatch, httpx.Response(400, json={"detail": "Insufficient treasury"}),
         httpx.Response(200, json={"balance": "0"}))
    with pytest.raises(HTTPException) as e:
        await _fund(_FundDb(SimpleNamespace(liquid_balance=Decimal("0"))), _grant("300"))
    assert e.value.status_code == 400
    assert tally.rows == {KEY: "400"}


async def test_a_stale_cached_balance_never_gives_room_back(monkeypatch):
    tally = _Tally({KEY: "100"})
    _arm(monkeypatch, "on", tally)
    # a leg committed and the TEG then raised (500); the cached balance (1000) is stale-high, so the balance check reads
    # 300 < 1000 + 270 and calls it a genuine failure although 300 arrived
    _teg(monkeypatch, httpx.Response(500, json={"detail": "Payout funding failed"}),
         httpx.Response(200, json={"balance": "300"}))
    with pytest.raises(HTTPException):
        await _fund(_FundDb(SimpleNamespace(liquid_balance=Decimal("1000"))), _grant("300"))
    assert tally.rows == {KEY: "400"}


@pytest.mark.parametrize("lost", [httpx.ReadTimeout("no answer"), httpx.ReadError("the answer broke off"),
                                  httpx.RemoteProtocolError("the answer broke off")])
async def test_a_lost_answer_keeps_the_room_counted(monkeypatch, lost):
    tally = _Tally({KEY: "100"})
    _arm(monkeypatch, "on", tally)
    _teg(monkeypatch, lost)
    with pytest.raises(HTTPException) as e:
        await _fund(_FundDb(), _grant("300"))
    assert e.value.status_code == 503
    assert tally.rows == {KEY: "400"}                      # it may have moved: the room left can only shrink


@pytest.mark.parametrize("never_sent", [httpx.ConnectError("the TEG did not answer"), httpx.ConnectTimeout("no route"),
                                        httpx.PoolTimeout("no free connection")])
async def test_a_request_that_never_left_gives_the_room_back(monkeypatch, never_sent):
    tally = _Tally({KEY: "100"})
    _arm(monkeypatch, "on", tally)
    _teg(monkeypatch, never_sent)
    with pytest.raises(HTTPException) as e:
        await _fund(_FundDb(), _grant("300"))
    assert e.value.status_code == 503
    assert tally.rows == {KEY: "100"}                      # no connection, no request: nothing could move


async def test_shadow_reports_a_grant_past_the_cap_and_lets_it_through(monkeypatch, caplog):
    tally = _Tally({KEY: "900"})
    _arm(monkeypatch, "shadow", tally)
    calls = _teg(monkeypatch, _ok())
    with caplog.at_level(logging.WARNING):
        out = await _fund(_FundDb(), _grant("200"))
    assert out["transaction_id"] == "tx-1" and len(calls) == 1
    assert tally.rows == {KEY: "1100"}                     # counted as granted, past the cap
    assert any("decision=DENY" in r.getMessage() and "mode=shadow" in r.getMessage()
               and "allocation_cap_exceeded" in r.getMessage() for r in caplog.records)


async def test_shadow_lets_an_undeclared_allocation_through_and_reports_it(monkeypatch, caplog):
    tally = _Tally()
    _arm(monkeypatch, "shadow", tally)
    calls = _teg(monkeypatch, _ok())
    with caplog.at_level(logging.WARNING):
        await _fund(_FundDb(), _grant("5", reason="allocation:proj-099"))
    assert len(calls) == 1 and tally.rows == {"quantum_alloc:proj-099": "5"}
    assert any("allocation_unknown" in r.getMessage() and "mode=shadow" in r.getMessage() for r in caplog.records)


async def test_shadow_never_blocks_on_an_unreadable_tally(monkeypatch):
    def _down():
        raise ConnectionError("database down")

    monkeypatch.setenv("QUANTUM_WORKLOADS_MODE", "shadow")
    monkeypatch.setenv("QUANTUM_ALLOCATION_PROFILE", json.dumps(PROFILE))
    monkeypatch.setattr(_qw(), "_session_factory", _down)
    calls = _teg(monkeypatch, _ok())
    await _fund(_FundDb(), _grant("5"))
    assert len(calls) == 1


async def test_on_refuses_when_the_tally_cannot_be_read(monkeypatch):
    def _down():
        raise ConnectionError("database down")

    monkeypatch.setenv("QUANTUM_WORKLOADS_MODE", "on")
    monkeypatch.setenv("QUANTUM_ALLOCATION_PROFILE", json.dumps(PROFILE))
    monkeypatch.setattr(_qw(), "_session_factory", _down)
    calls = _teg(monkeypatch, _ok())
    with pytest.raises(HTTPException) as e:
        await _fund(_FundDb(), _grant("5"))
    assert e.value.status_code == 503 and e.value.detail.startswith("allocation_tally_unavailable:")
    assert "database down" not in e.value.detail and calls == []
