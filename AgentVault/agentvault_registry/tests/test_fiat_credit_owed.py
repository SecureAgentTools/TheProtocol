"""§LEDGERGATE (V0599, 2026-10-11): a paid direct-flow fiat purchase whose credit did not land is OWED and retried with the
purchase's own key, never failed and forgotten; an exhausted waterfall is the partial it committed, never a failure.

Read on V0598 (fe/batch-v0598 4afe37cf; FINDINGS_2026-10-11_TEG_NONNEGATIVE_AND_OUTBOX_GATE.md §9 S3, corrected): the
webhook answers 200 at once and credits in a background task, through a private call of /admin/reward-fund with NO
Idempotency-Key and no TokensTransferred per leg; any non-200 (the ledger gate's refusal, a TEG error, AND an exhausted
waterfall whose partial legs are committed) marked the purchase failed "reward_fund_failed", for an admin replay that
would pay again in full.

  1. the worker's wait: 30 s, 1, 2, 5, then 10 min;
  2. a completed credit rides the shared rail with fiat-credit-<id>, the purchase marked owed BEFORE the call (intent
     first), then completed with its transaction and finished (FiatPurchaseSettled, the receipt);
  3. the gate's refusal is owed as ledger_unavailable, a connection failure as teg_error, both due again; past the budget
     the purchase is failed "reward_fund_failed" (the human path); nothing is finished, nothing emitted;
  4. an exhausted waterfall is failed "reward_fund_partial: ..." with its first transaction, never retried;
  5. a purchase that is not pending or processing is left alone (no credit);
  6. one worker cycle asks every due purchase with its own provider ids;
  7. the instruments: the scanner and the stuck-funds board name a partial, the board names the owed, the worker runs
     with the registry, the private call is gone, the migration is the next revision and hands owed rows to the human
     path on a downgrade.
RED on fe/batch-v0598 4afe37cf: all of them (no _credit_and_complete, no worker, no columns, no migration).
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime
import inspect
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentvault_registry.background_tasks import fiat_credit_retry as fcr
from agentvault_registry.routers import fiat_onramp as fo

REFUSED = ('fund_reward failed for did:x: HTTP 503 — {"detail":"ledger_unavailable: The ledger cannot record this right '
           'now. Nothing was moved. Try again shortly.","code":"ledger_unavailable"}')
SRC = Path(__file__).resolve().parents[1]


def test_the_workers_wait():
    assert [fcr.credit_backoff_seconds(n) for n in range(0, 7)] == [30, 30, 60, 120, 300, 600, 600]


def _purchase(**kw):
    p = SimpleNamespace(id="fp-0001", status="pending", agent_did="did:theprotocol:buyer-0001", developer_id=None,
                        amount_avt=Decimal("2000"), amount_eur=Decimal("1.00"), tier_label="tier-1", anonymous_flow=False,
                        created_at=None, failure_reason=None, credit_attempts=0, credit_next_attempt_at=None,
                        avt_transfer_tx_id=None, completed_at=None, routed=False)
    for k, v in kw.items():
        setattr(p, k, v)
    return p


class _Db:
    def __init__(self, purchase):
        self.purchase, self.commits = purchase, 0

    async def get(self, _model, pid):
        return self.purchase if self.purchase is not None and pid == self.purchase.id else None

    async def commit(self):
        self.commits += 1

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


@pytest.fixture()
def rig(monkeypatch):
    """The router's collaborators recorded: the session, the shared rail, the finishing steps."""
    st = SimpleNamespace(calls=[], seen_at_call=[], emitted=[], mailed=[], flare=[], prov=[], failed=[], db=None, answer=None)

    def use(purchase, answer):
        st.db, st.answer = _Db(purchase), answer
        monkeypatch.setattr(fo, "AsyncSessionLocal", lambda: st.db)

        async def fund(_db, **kw):
            st.calls.append(kw)
            st.seen_at_call.append((purchase.status, purchase.failure_reason, st.db.commits))
            if isinstance(st.answer, Exception):
                raise st.answer
            return st.answer
        monkeypatch.setattr("agentvault_registry.services.reward_funding.fund_reward_via_waterfall", fund)

        async def emit(**kw):
            st.emitted.append(kw)

        async def mail(*a):
            st.mailed.append(a)

        async def flare(**kw):
            st.flare.append(kw)

        async def prov(**kw):
            st.prov.append(kw)
        monkeypatch.setattr(fo, "_emit", emit)
        monkeypatch.setattr(fo, "_send_purchase_email", mail)
        monkeypatch.setattr(fo, "_grant_flare", flare)
        monkeypatch.setattr(fo, "_grant_provisioning_credit", prov)
        monkeypatch.setattr(fo, "_inc_purchase_failed", lambda provider, reason: st.failed.append(reason))
        return st
    return use


def _run(pid="fp-0001"):
    async def go():
        out = await fo._credit_and_complete(pid, provider="stripe", event_id="evt_1", session_id="cs_1")
        await asyncio.sleep(0)   # the receipt mail is a created task
        return out
    return asyncio.run(go())


def test_a_completed_credit_rides_the_shared_rail_with_the_purchases_key(rig):
    p = _purchase()
    st = rig(p, {"status": "completed", "first_transaction_id": "tx-1", "funded_amount": "2000", "shortfall": "0"})
    assert _run() == "completed"
    assert st.calls == [{"target_agent_did": p.agent_did, "amount": Decimal("2000"), "reason": "fiat_purchase",
                         "reference_id": "fiat-fp-0001", "idempotency_key": "fiat-credit-fp-0001"}]
    # intent first: the purchase was owed and committed BEFORE the TEG call
    assert st.seen_at_call == [("processing", "credit_owed: in_flight", 1)]
    assert (p.status, p.avt_transfer_tx_id, p.failure_reason, p.credit_next_attempt_at) == ("completed", "tx-1", None, None)
    assert p.completed_at is not None and st.db.commits == 2
    assert [e["event_type"] for e in st.emitted] == ["FiatPurchaseSettled"]
    assert st.emitted[0]["data"]["tx_id"] == "tx-1" and st.emitted[0]["data"]["stripe_event_id"] == "evt_1"
    assert len(st.mailed) == 1 and len(st.flare) == 1 and len(st.prov) == 1


@pytest.mark.parametrize("error,why", [
    ("refused", "ledger_unavailable"),
    ("connect", "teg_error"),
])
def test_a_credit_that_did_not_land_is_owed_and_due_again(rig, error, why):
    from agentvault_registry.teg_client import TEGClientError
    p = _purchase()
    exc = TEGClientError(REFUSED) if error == "refused" else ConnectionError("Failed to connect to the TEG")
    st = rig(p, exc)
    t0 = datetime.datetime.now(datetime.timezone.utc)
    assert _run() == "processing"
    assert p.failure_reason.startswith(f"credit_owed: {why}: ") and p.credit_attempts == 1
    wait = (p.credit_next_attempt_at - t0).total_seconds()
    assert 25 <= wait <= 35, wait
    assert not st.emitted and not st.mailed and not st.flare and p.avt_transfer_tx_id is None


def test_past_the_budget_the_purchase_takes_the_human_path(rig, monkeypatch):
    from agentvault_registry.teg_client import TEGClientError
    monkeypatch.setenv("FIAT_CREDIT_MAX_ATTEMPTS", "288")
    p = _purchase(status="processing", failure_reason="credit_owed: ledger_unavailable: x", credit_attempts=287)
    st = rig(p, TEGClientError(REFUSED))
    assert _run() == "failed"
    assert (p.failure_reason, p.credit_attempts, p.credit_next_attempt_at) == ("reward_fund_failed", 288, None)
    assert st.failed == ["reward_fund_failed"] and not st.emitted


def test_an_exhausted_waterfall_is_the_partial_it_committed(rig):
    p = _purchase()
    st = rig(p, {"status": "exhausted", "first_transaction_id": "tx-part", "funded_amount": "1500", "shortfall": "500"})
    assert _run() == "failed"
    assert p.failure_reason.startswith("reward_fund_partial: funded 1500 of 2000, shortfall 500")
    assert p.avt_transfer_tx_id == "tx-part" and p.credit_next_attempt_at is None
    assert st.failed == ["reward_fund_partial"] and not st.emitted and not st.mailed


@pytest.mark.parametrize("status", ["completed", "refunded", "failed"])
def test_a_purchase_that_is_not_open_is_left_alone(rig, status):
    p = _purchase(status=status)
    st = rig(p, {"status": "completed", "first_transaction_id": "tx-x"})
    assert _run() == status
    assert st.calls == [] and st.db.commits == 0 and not st.emitted


class _Rows:
    def __init__(self, rows=None, count=0):
        self.rows, self.count = rows or [], count

    def all(self):
        return self.rows

    def scalar(self):
        return self.count


class _CycleDb:
    def __init__(self, answer):
        self.answer = answer

    async def execute(self, _stmt):
        return self.answer


def test_one_cycle_asks_every_due_purchase_with_its_own_ids(monkeypatch):
    rows = [SimpleNamespace(id="fp-a", payment_provider="stripe", provider_event_id="evt_a", provider_session_id="cs_a"),
            SimpleNamespace(id="fp-b", payment_provider=None, provider_event_id="evt_b", provider_session_id=None)]
    answers = iter([_Rows(rows=rows), _Rows(count=1)])

    @contextlib.asynccontextmanager
    async def ctx():
        yield _CycleDb(next(answers))
    monkeypatch.setattr(fcr, "get_db_context", ctx)
    calls = []

    async def credit(pid, **kw):
        calls.append((pid, kw))
        return "completed" if pid == "fp-a" else "processing"
    monkeypatch.setattr(fo, "_credit_and_complete", credit)
    w = fcr.FiatCreditRetry()
    asyncio.run(w._cycle_once())
    assert calls == [("fp-a", {"provider": "stripe", "event_id": "evt_a", "session_id": "cs_a"}),
                     ("fp-b", {"provider": "stripe", "event_id": "evt_b", "session_id": None})]
    assert w._last_stats() == {"asked_this_cycle": 2, "outcomes": {"completed": 1, "processing": 1}, "owed_now": 1}


def test_the_instruments_the_worker_and_the_migration():
    src = inspect.getsource(fo)
    assert "/api/v1/admin/reward-fund" not in src and "_fund_via_reward_waterfall(" not in src
    assert "await _credit_and_complete(purchase.id, provider=event.provider, event_id=event_id, session_id=session_id)" \
        in inspect.getsource(fo._handle_checkout_completed)
    from agentvault_registry.background_tasks import forensic_scanner
    from agentvault_registry.routers import admin_health
    assert "failure_reason LIKE 'reward_fund_partial:%'" in inspect.getsource(forensic_scanner)
    board = inspect.getsource(admin_health)
    assert "failure_reason LIKE 'reward_fund_partial:%'" in board and 'cls="paid_credit_owed"' in board
    from agentvault_registry import main
    m = inspect.getsource(main)
    assert "await get_fiat_credit_retry().start()" in m and "await get_fiat_credit_retry().stop()" in m
    text = (SRC / "alembic" / "versions" / "0189_fiat_credit_owed.py").read_text()
    assert 'revision = "0189_fiat_credit_owed"' in text and 'down_revision = "0188_genesis_grant_owed"' in text
    assert "SET status = 'failed', failure_reason = 'reward_fund_failed'" in text and len("0189_fiat_credit_owed") <= 32
