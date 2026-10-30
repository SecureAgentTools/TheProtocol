"""§2026-08-12 — reward_fund mid-waterfall idempotency sharp-edge.

Integration test (real Postgres, real endpoint code) for the fix in
endpoints_treasury.py::reward_fund. Runs against a THROWAWAY database whose URL
comes from DATABASE_URL (see scratchpad/rollout_idemfix_framec.sh) — it does NOT
touch any production schema.

THE BUG (pre-fix): when a leg's money has committed (_moved=True) and a LATER step
of the waterfall throws, the except-block skipped _idem_fail entirely, leaving the
idempotency record 'pending'. IdempotencyService.check_and_create then 409s every
same-key retry for the full 24h TTL — a one-time reward is stuck for a day.

THE FIX: on a post-money throw, cache the accumulated partial as COMPLETED (via the
existing exhausted path), so a same-key retry replays the partial (never re-runs →
never double-pays) instead of 409-ing. Δ-irrelevant — pure idempotency-record state.

Mutation-verify: run this file against the PRE-fix endpoints_treasury.py →
test_midwaterfall_partial_cached_not_pending FAILS (record stays 'pending', retry
raises 409). Runner exits non-zero on any failure.

Run:  python tests/test_reward_fund_idem.py   (inside a container with the TEG deps)
"""
import os
import sys
import json
import asyncio
from decimal import Decimal

sys.path.insert(0, "/app")

# Must be set before the settings-bound modules import.
os.environ.setdefault("AUDITED_BALANCE_ENABLED", "false")
os.environ.setdefault("TEG_HOME_FRAME_GUARD_ENABLED", "false")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.responses import JSONResponse

from src.teg_core_service.database.models import (
    Base, AgentTEGProfile, SystemConfig, TransactionStatus,
)
import src.teg_core_service.api.v1.endpoints_treasury as ep
from src.teg_core_service.core.idempotency import IdempotencyRecord
from src.teg_core_service.core.error_handling import TEGException

TREASURY = "did:theprotocol:teg_system_treasury"
FEECOLL = "teg:system:fee_collector"

_raw = os.environ.get("DATABASE_URL_SYNC") or os.environ["DATABASE_URL"]
# the sync driver NAMED (psycopg2), as the TEG names it (§DEPS sqla-driver-pin)
from src.teg_core_service.core.db_url import sync_engine_url  # noqa: E402
DB_URL = sync_engine_url(_raw)
engine = create_engine(DB_URL)
SessionLocal = sessionmaker(bind=engine)


async def _noop_async(*a, **k):
    return True


# No EventStore in the test — the reward leg awaits _emit_treasury_transfer_event and
# execute_transfer fire-and-forgets _emit_transfer_event; both would hang on the ES HTTP.
ep._emit_treasury_transfer_event = _noop_async
try:
    import src.teg_core_service.transfer_service_enhanced as tse
    tse._emit_transfer_event = _noop_async
except Exception:
    pass


def reset_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def seed(db, fee_bal, treas_bal, target):
    for aid, b in [(FEECOLL, fee_bal), (TREASURY, treas_bal), (target, 0)]:
        db.add(AgentTEGProfile(
            agent_id=aid, token_balance=Decimal(str(b)), audited_balance=Decimal(str(b)),
            locked_balance=Decimal("0"), wrapped_balance=Decimal("0"),
            reputation_score=0, account_status="active",
        ))
    db.add(SystemConfig(key="teg_system_treasury_did", value=TREASURY))
    db.add(SystemConfig(key="fee_collection_address", value=FEECOLL))
    db.add(SystemConfig(key="reward_funding_waterfall",
                        value=json.dumps({"default": ["fee_collector", "treasury"]})))
    db.add(SystemConfig(key="teg_transfer_fee", value="0"))
    db.commit()


def bal(db, aid):
    db.expire_all()
    r = db.query(AgentTEGProfile).filter(AgentTEGProfile.agent_id == aid).first()
    return r.token_balance if r else Decimal("0")


def idem_status(db, key):
    db.expire_all()
    r = db.query(IdempotencyRecord).filter(IdempotencyRecord.idempotency_key == key).first()
    return r.status if r else None


def req(target, amount, reason="genesis_grant"):
    return ep.RewardFundRequest(target_agent_id=target, amount=Decimal(str(amount)), reason=reason)


def _run(target, amount, key, db):
    return asyncio.run(ep.reward_fund(request=req(target, amount), is_admin=True, db=db, idempotency_key=key))


# ── Scenario A: happy path completes, retry returns cached, no double-pay ────────
def test_happy_path_and_cached_retry():
    reset_db()
    db = SessionLocal()
    try:
        target = "did:test:happy"
        seed(db, 30, 1000, target)                 # 30 from fee_collector + 70 from treasury = 100
        key = "idem-happy"
        resp = _run(target, 100, key, db)
        assert getattr(resp, "status", None) == "completed", f"got {resp}"
        assert bal(db, target) == Decimal("100"), bal(db, target)
        assert idem_status(db, key) == "completed", idem_status(db, key)
        before = bal(db, target)
        resp2 = _run(target, 100, key, db)
        assert getattr(resp2, "status", None) == "completed"
        assert bal(db, target) == before, "retry DOUBLE-PAID the happy path"
    finally:
        db.close()


# ── Scenario B: exhausted caches + retry replays (regression guard, pre-existing) ─
def test_exhausted_cached_and_replayed():
    reset_db()
    db = SessionLocal()
    try:
        target = "did:test:exhausted"
        seed(db, 30, 50, target)                   # only 80 available for a 100 request
        key = "idem-exhausted"
        r1 = _run(target, 100, key, db)
        assert isinstance(r1, JSONResponse) and r1.status_code == 400, f"expected exhausted 400, got {r1}"
        assert Decimal(json.loads(r1.body)["funded_amount"]) == Decimal("80")
        assert bal(db, target) == Decimal("80")
        assert idem_status(db, key) == "completed"
        before = bal(db, target)
        r2 = _run(target, 100, key, db)
        assert isinstance(r2, JSONResponse) and r2.status_code == 400
        assert bal(db, target) == before, "retry DOUBLE-PAID the exhausted partial"
    finally:
        db.close()


# ── Scenario C: THE FIX — a later leg throws → partial cached COMPLETED, not pending ─
def test_midwaterfall_partial_cached_not_pending():
    reset_db()
    db = SessionLocal()
    real_exec = ep.TransferService.execute_transfer
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 2:                        # leg 1 commits for real, leg 2 blows up
            raise RuntimeError("injected mid-waterfall failure on leg 2")
        return real_exec(*a, **k)

    ep.TransferService.execute_transfer = staticmethod(flaky)
    try:
        target = "did:test:midwaterfall"
        seed(db, 30, 1000, target)                 # leg1=30 (drains fee_collector), leg2 would cover 70
        key = "idem-mid"
        raised = None
        try:
            _run(target, 100, key, db)
        except TEGException as e:
            raised = e
        assert raised is not None, "first call should surface the injected error"
        # leg 1's money DID move; leg 2 did not
        assert bal(db, target) == Decimal("30"), f"leg1 should have moved 30, target={bal(db, target)}"
        # THE FIX: record is 'completed' (cached partial), NOT 'pending' (the 24h-409 bug)
        st = idem_status(db, key)
        assert st == "completed", (
            f"FIX FAILED: idem status={st!r} — 'pending' is the mid-waterfall bug "
            f"(check_and_create 409s every retry for 24h)"
        )
    finally:
        ep.TransferService.execute_transfer = staticmethod(real_exec)

    # retry with the SAME key: replays the cached partial (400 exhausted), NO 409, NO re-pay
    before = bal(db, target)
    r2 = None
    err2 = None
    try:
        r2 = _run(target, 100, key, db)
    except TEGException as e:
        err2 = e
    assert err2 is None, f"FIX FAILED: retry raised {getattr(err2, 'status_code', None)} (409 = the bug)"
    assert isinstance(r2, JSONResponse) and r2.status_code == 400, f"expected cached partial 400, got {r2}"
    body = json.loads(r2.body)
    assert Decimal(body.get("funded_amount", "0")) == Decimal("30"), \
        f"cached partial should report the 30 that moved, got {body}"
    assert bal(db, target) == before, "retry DOUBLE-PAID after the mid-waterfall error"
    db.close()


# ── Scenario D: §REWARDRACE — a concurrent funding drains the source under the leg ──
def test_a_source_drained_under_the_leg_rolls_to_the_next():
    """§REWARDRACE (2026-10-06, measured on sbx-alpha: two 50 fundings 7 ms apart, the second refused "Insufficient
    balance" while the treasury held plenty). The waterfall reads the fee collector at 60; before its leg debits, another
    funding (its own session, committed) takes 50; the leg re-reads 10, takes it, and the treasury covers the other 40.
    Pre-fix: the leg's ValueError fails the whole funding 400 ("Reward fund failed" then, "Payout funding failed" since) and nothing reaches the target."""
    reset_db()
    db = SessionLocal()
    real_exec = ep.TransferService.execute_transfer
    calls = {"n": 0}

    def racing(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:                        # the concurrent funding commits between the read and this debit
            other = SessionLocal()
            try:
                real_exec(other, FEECOLL, "did:test:concurrent", Decimal("50"), fee_amount=Decimal("0"),
                          entry_type="reward_test_concurrent")
            finally:
                other.close()
        return real_exec(*a, **k)

    ep.TransferService.execute_transfer = staticmethod(racing)
    try:
        target = "did:test:race"
        seed(db, 60, 1000, target)                 # the waterfall reads 60 in the fee collector
        resp = _run(target, 50, "idem-race", db)
        assert getattr(resp, "status", None) == "completed", f"FIX FAILED: the funding did not complete: {resp}"
        assert bal(db, target) == Decimal("50"), bal(db, target)
        assert bal(db, FEECOLL) == Decimal("0"), bal(db, FEECOLL)          # 10 left by the other funding, re-read and taken
        assert bal(db, TREASURY) == Decimal("960"), bal(db, TREASURY)      # the remaining 40 from the next source
        legs = [(l["source"], Decimal(l["amount"])) for l in resp.legs]
        assert legs == [("fee_collector", Decimal("10")), ("treasury", Decimal("40"))], legs
        assert idem_status(db, "idem-race") == "completed", idem_status(db, "idem-race")
    finally:
        ep.TransferService.execute_transfer = staticmethod(real_exec)
        db.close()


TESTS = [
    test_happy_path_and_cached_retry,
    test_exhausted_cached_and_replayed,
    test_midwaterfall_partial_cached_not_pending,
    test_a_source_drained_under_the_leg_rolls_to_the_next,
]

if __name__ == "__main__":
    failed = 0
    for t in TESTS:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:
            failed += 1
            import traceback
            print(f"FAIL  {t.__name__}: {e}")
            traceback.print_exc()
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    sys.exit(1 if failed else 0)
