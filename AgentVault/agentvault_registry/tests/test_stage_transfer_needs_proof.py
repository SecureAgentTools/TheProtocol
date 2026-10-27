"""§DOCSFIX D6-776 (2026-10-17): a stage-through-the-payer transfer whose outcome is not known is held, never undone.

Three sites stage a payout through the payer under a fresh escrow key, then send it on with the payer's own POST
/api/v1/teg/cross-registry-transfer under a stable key: services/contract_settlement.drive_release (a milestone release
to a provider on another registry) and routers/guild.py's verify and dispute payout (a worker on another registry).
After a failure each took the staged units back into escrow and reopened the step when that deposit succeeded, judging
the transfer reversed if the payer still held the units. A payer may hold units of its own, so a transfer that paid
and then timed out, or answered that its outcome is not known, was undone and reopened: the next release staged a
second payout, and once the endpoint's 24 hours under the stable key had passed the transfer ran again and paid the
payee twice.

Now the staged units go back only after an answer that PROVES nothing moved (payout_outcome.stage_failure_outcome): the
connection was never made, a "failed" or an error that says nothing moved, a 402, or a refusal made before the endpoint
ran (401, an IRONKEY 403 naming the payer's missing permission, 429, a validation 422). Everything else holds the step
for an administrator. The endpoint's own refusal of a receiver whose currency it cannot resolve says so now (it is
raised before anything is sent).

The guild's two sites also read the 2xx answer's status, as D6-456 made the contract release do: the endpoint answers a
transfer the TEGs did not complete with HTTP 200 and "status": "failed", which the guild recorded as paid.

RED on the pre-change tree (37): the outcome table and its paid case (the function did not exist), the five held
releases (a read timeout, two 5xx, an answer whose outcome is not known, a claimed key: each was undone and reopened),
the currency refusal's sentence, the guild's answer reader and its three structure pins. The controls are green before
and after: the five releases whose answers prove nothing moved, a completed transfer, a "failed" that says nothing
moved.
"""
from __future__ import annotations

import ast
import asyncio
import pathlib
import types
from decimal import Decimal

import httpx
import pytest

from agentvault_registry.services import contract_settlement as cs
from agentvault_registry.services import deal_thread_events as dte
from agentvault_registry.services import escrow
from agentvault_registry.services import payout_outcome as po

_ROOT = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"


class _Resp:
    def __init__(self, status_code, body=None, text=None):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.text = text if text is not None else str(self._body)

    def json(self):
        return self._body


# ── the reading itself ───────────────────────────────────────────────────────────────────────────────────────────────

_REQ = httpx.Request("POST", "http://localhost:8000/api/v1/teg/cross-registry-transfer")


@pytest.mark.parametrize("response,error,kind", [
    # proof that nothing moved
    (None, httpx.ConnectError("refused", request=_REQ), po.RETRY),
    (_Resp(200, {"status": "failed", "error_message": "Insufficient balance (no funds moved)"}), None, po.RETRY),
    (_Resp(503, text='{"detail":"TEG cross-transfer service unreachable (no funds moved)"}'), None, po.RETRY),
    (_Resp(402, text='{"detail":"Insufficient balance"}'), None, po.RETRY),
    (_Resp(401, text='{"detail":"Could not validate credentials"}'), None, po.RETRY),
    (_Resp(403, text='{"detail":"Agent lacks required permission: teg.transfer"}'), None, po.RETRY),
    (_Resp(429, text='{"detail":"Rate limit exceeded"}'), None, po.RETRY),
    (_Resp(422, text='{"detail":[{"loc":["body","amount"],"msg":"field required"}]}'), None, po.RETRY),
    (_Resp(409, text='{"detail":"Cannot resolve the settlement currency ... is unset (no funds moved)."}'), None,
     po.RETRY),
    (_Resp(409, text='{"detail":"FX route did not settle (route_id=x): it returned this payment (origin refunded) '
                     '(nothing reached the receiver)."}'), None, po.RETRY),
    # no proof: held
    (None, httpx.ReadTimeout("timed out", request=_REQ), po.HOLD),
    (None, RuntimeError("boom"), po.HOLD),
    (None, None, po.HOLD),
    (_Resp(200, {"status": "failed", "error_message": "Commit failed on target TEG"}), None, po.HOLD),
    (_Resp(503, text='{"detail":"Cross-registry transfer service unavailable"}'), None, po.HOLD),
    (_Resp(503, text='{"detail":"Cross-registry transfer service unavailable (outcome not known): an earlier '
                     'attempt may have reached the TEG"}'), None, po.HOLD),
    (_Resp(500, text='{"detail":"The request failed after it was sent on (outcome not known): it may have moved"}'),
     None, po.HOLD),
    (_Resp(409, text='{"detail":"FX route did not settle (route_id=x): it returned this payment (origin refunded)."}'),
     None, po.HOLD),
    (_Resp(409, text='{"detail":"FX route did not settle and the gateway did not report a refund; the ingress is '
                     'parked at the gateway: x"}'), None, po.HOLD),
    (_Resp(422, text="{\"detail\":\"Idempotency-Key 'k' is claimed on this endpoint by an earlier request that is "
                     "still in progress\"}"), None, po.HOLD),
    (_Resp(422, text="{\"detail\":\"Idempotency-Key 'k' was already used with a different request payload\"}"), None,
     po.HOLD),
    (_Resp(403, text='{"detail":"Only the owner may do this"}'), None, po.HOLD),
    # a 503 that quotes a proof sentence but also says nobody knows: the doubt wins
    (_Resp(503, text='{"detail":"unavailable (outcome not known) after (no funds moved) on a far side"}'), None,
     po.HOLD),
])
def test_only_proof_lets_the_staged_units_go_back(response, error, kind):
    assert po.stage_failure_outcome(response, error).kind == kind


def test_a_2xx_that_says_it_went_out_reads_paid():
    assert po.stage_failure_outcome(_Resp(200, {"status": "completed", "transfer_id": "xf-1"}), None).kind == po.PAID


# ── the contract release ─────────────────────────────────────────────────────────────────────────────────────────────

CLIENT = "did:theprotocol:eu.theprotocol.cloud:client-0000"
PROVIDER = "did:theprotocol:asia.theprotocol.cloud:provider-0000"
CONTRACT = {"id": "ctr_1", "counterparty_home_registry": "asia", "client_did": CLIENT, "provider_did": PROVIDER,
            "payee_did": None, "total_amount": Decimal("10"), "currency": "ECU"}
MILESTONE = {"seq": 1, "amount": Decimal("10")}


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Db:
    def __init__(self):
        self.sql = []

    async def execute(self, stmt, params=None):
        self.sql.append(str(stmt))
        return types.SimpleNamespace(rowcount=1, scalar=lambda: 1)

    async def commit(self):
        pass


def _setup(monkeypatch, response=None, error=None):
    rec = types.SimpleNamespace(moves=[], audits=[], db=_Db())

    async def _legs(db, c, m):
        return Decimal("0"), [(PROVIDER, Decimal("10"), "m1:settle")]

    async def _payout(db, did, amount, ref, reason=None):
        rec.moves.append("payout")

    async def _deposit(did, amount, ref, reason=None):
        rec.moves.append("deposit")

    async def _audit(db, cid, seq, etype, actor, data):
        rec.audits.append((etype, data))

    async def _seq(db, cid):
        return 1

    async def _posted(*a, **k):
        return None

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            rec.moves.append("transfer")
            if error is not None:
                raise error
            return response
    monkeypatch.setattr(cs, "compute_release_legs", _legs)
    monkeypatch.setattr(escrow, "escrow_payout", _payout)
    monkeypatch.setattr(escrow, "escrow_deposit", _deposit)
    monkeypatch.setattr(cs, "audit", _audit)
    monkeypatch.setattr(cs, "next_seq", _seq)
    monkeypatch.setattr(cs, "emit", lambda *a, **k: None)
    monkeypatch.setattr(cs, "announce_release", lambda *a, **k: None)
    monkeypatch.setattr(dte, "post_settled", _posted)
    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    return rec


def _drive(rec):
    return _run(cs.drive_release(rec.db, CONTRACT, MILESTONE, actor_did=CLIENT, auth_header="Bearer client"))


def _reopened(rec):
    return any("SET status='submitted'" in s for s in rec.db.sql)


def _released(rec):
    return any("SET status='released'" in s for s in rec.db.sql)


@pytest.mark.parametrize("response,error", [
    (None, httpx.ReadTimeout("timed out", request=_REQ)),
    (_Resp(503, text='{"detail":"Cross-registry transfer service unavailable (outcome not known): an earlier '
                     'attempt may have reached the TEG"}'), None),
    (_Resp(503, text='{"detail":"Cross-registry transfer service unavailable"}'), None),
    (_Resp(500, text='{"detail":"The request failed after it was sent on (outcome not known)"}'), None),
    (_Resp(422, text="{\"detail\":\"Idempotency-Key 'k' is claimed on this endpoint by an earlier request\"}"), None),
])
def test_a_release_whose_transfer_may_have_paid_is_held_and_nothing_goes_back(monkeypatch, response, error):
    rec = _setup(monkeypatch, response, error)
    with pytest.raises(escrow.EscrowError) as e:
        _drive(rec)
    assert e.value.status_code == 502 and "held for admin review" in e.value.message
    assert rec.moves == ["payout", "transfer"]          # staged and sent; nothing taken back into escrow
    assert not _reopened(rec) and not _released(rec)
    [(etype, data)] = rec.audits
    assert etype == "release_failed" and data["outcome_unknown"] is True and data["held_for"] == "admin"
    assert data["outcome"]


@pytest.mark.parametrize("response,error", [
    (None, httpx.ConnectError("refused", request=_REQ)),
    (_Resp(503, text='{"detail":"TEG cross-transfer service unreachable (no funds moved)"}'), None),
    (_Resp(401, text='{"detail":"Could not validate credentials"}'), None),
    (_Resp(402, text='{"detail":"Insufficient balance"}'), None),
    (_Resp(409, text='{"detail":"Cannot resolve the settlement currency of receiver x\'s home frame (no funds '
                     'moved)."}'), None),
])
def test_control_a_release_whose_transfer_moved_nothing_goes_back_and_reopens(monkeypatch, response, error):
    rec = _setup(monkeypatch, response, error)
    with pytest.raises(escrow.EscrowError) as e:
        _drive(rec)
    assert e.value.status_code == 502 and "held for admin review" not in e.value.message
    assert rec.moves == ["payout", "transfer", "deposit"]
    assert _reopened(rec) and not _released(rec)
    [(etype, data)] = rec.audits
    assert etype == "release_failed" and data["compensated"] is True and "outcome_unknown" not in data


def test_the_currency_refusal_says_it_moved_nothing():
    src = (_ROOT / "routers/teg_integration.py").read_text()
    assert "is missing or its trust domain is unset {NO_FUNDS_MOVED}." in src


# ── the guild's two sites ────────────────────────────────────────────────────────────────────────────────────────────

def test_the_guild_reads_a_200_failed_as_no_payment():
    from agentvault_registry.routers import guild
    assert guild._xf_answer(_Resp(200, {"status": "failed", "error_message": "Commit failed"})) == (
        False, "status failed: Commit failed")
    assert guild._xf_answer(_Resp(503, text="down"))[0] is False
    assert guild._xf_answer(_Resp(200, {"status": "completed", "transfer_id": "xf-1"})) == (True, "")


def _calls(tree, fragment):
    """Every call whose source contains `fragment` (an escrow_deposit with its leg name)."""
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call) and fragment in ast.unparse(n)]


def _retry_guards(tree):
    """Line ranges of every `if _xo.kind == _po.RETRY:` body: found by parsing, never by grep."""
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.If) and ast.unparse(n.test) == "_xo.kind == _po.RETRY":
            out.append((min(b.lineno for b in n.body), max(getattr(b, "end_lineno", b.lineno) for b in n.body)))
    return out


@pytest.mark.parametrize("leg", ['leg=f"xf_stage_return:{nonce}"', 'leg=f"xfd_stage_return:{nonce}"'])
def test_the_guild_takes_the_staged_units_back_only_inside_the_proof(leg):
    tree = ast.parse((_ROOT / "routers/guild.py").read_text())
    calls = [c for c in _calls(tree, "escrow_deposit") if leg.replace('"', "'") in ast.unparse(c)
             or leg in ast.unparse(c)]
    assert len(calls) == 1, f"expected one compensating deposit with {leg}, found {len(calls)}"
    guards = _retry_guards(tree)
    assert len(guards) == 2, f"expected the proof guard at both guild sites, found {len(guards)}"
    assert any(lo <= calls[0].lineno <= hi for lo, hi in guards), f"{leg}: the deposit runs without proof"


def test_each_guild_site_reads_the_answer_it_got_and_the_error_it_caught():
    src = (_ROOT / "routers/guild.py").read_text()
    assert src.count("xf_ok, xf_err = _xf_answer(xr)") == 2
    assert src.count("_xo = _po.stage_failure_outcome(xr if xf_exc is None else None, xf_exc)") == 2
    assert src.count('xf_err = str(e); xf_exc = e') == 2


# ── controls: green before and after ─────────────────────────────────────────────────────────────────────────────

def test_control_a_completed_transfer_releases_the_milestone(monkeypatch):
    rec = _setup(monkeypatch, _Resp(200, {"transfer_id": "xf-1", "status": "completed"}))
    _drive(rec)
    assert rec.moves == ["payout", "transfer"] and _released(rec) and not _reopened(rec)


def test_control_a_failed_answer_that_says_nothing_moved_goes_back(monkeypatch):
    rec = _setup(monkeypatch, _Resp(200, {"transfer_id": "xf-1", "status": "failed",
                                          "error_message": "Insufficient balance (no funds moved)"}))
    with pytest.raises(escrow.EscrowError):
        _drive(rec)
    assert rec.moves == ["payout", "transfer", "deposit"] and _reopened(rec)
