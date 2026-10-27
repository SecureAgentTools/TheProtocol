"""§POCKETBRIDGE5 W-F — the three single-transfer treasury siblings' idempotency windows.

Integration test (real Postgres, real endpoint code) for treasury_transfer /
treasury_receive / fee_collector_distribute in endpoints_treasury.py. Runs
against a THROWAWAY database (DATABASE_URL) — never a production schema.
Harness: scratchpad/test_singleidem_harness.sh (clone of test_idemfix_harness.sh).

THE TWO WINDOWS (pre-fix), same class §IDEMFIX closed on reward_fund 2026-08-12:

  WINDOW A (double-pay): execute_transfer commits the money INTERNALLY, but
  `_moved` flipped only after the cosmetic label commit. A throw in that gap hit
  `if not _moved: _idem_fail` → the key was marked FAILED → check_and_create
  DELETES failed records and re-runs → a same-key retry RE-PAID.

  WINDOW B (stuck pending): a throw after `_moved=True` (balance reads, logging,
  response build) skipped both _idem_fail and _idem_complete → the key stayed
  `pending` → every same-key retry 409'd for the 24h TTL.

THE FIX: `_moved` flips the instant execute_transfer returns; the label commit is
best-effort; every post-money throw caches the COMPLETED response via
`_idem_cache_single` so a same-key retry REPLAYS it. Δ-irrelevant — pure
idempotency-record state, the money legs are untouched.

Mutation-verify: against the PRE-fix endpoints_treasury.py, scenario B fails with
a DOUBLE PAY and scenario C fails with a 409 retry. Runner exits non-zero on any
failure — a suite that cannot fail measures nothing.

Run:  python tests/test_single_transfer_idem.py   (inside a container with TEG deps)
"""
import os
import sys
import asyncio
from decimal import Decimal

sys.path.insert(0, "/app")

os.environ.setdefault("AUDITED_BALANCE_ENABLED", "false")
os.environ.setdefault("TEG_HOME_FRAME_GUARD_ENABLED", "false")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.teg_core_service.database.models import (
    Base, AgentTEGProfile, SystemConfig,
)
import src.teg_core_service.api.v1.endpoints_treasury as ep
from src.teg_core_service.core.idempotency import IdempotencyRecord
from src.teg_core_service.core.error_handling import TEGException

TREASURY = "did:theprotocol:teg_system_treasury"
FEECOLL = "teg:system:fee_collector"
TARGET = "did:theprotocol:singleidem-target"

_raw = os.environ.get("DATABASE_URL_SYNC") or os.environ["DATABASE_URL"]
# the sync driver NAMED (psycopg2), as the TEG names it (§DEPS sqla-driver-pin)
from src.teg_core_service.core.db_url import sync_engine_url  # noqa: E402
DB_URL = sync_engine_url(_raw)
engine = create_engine(DB_URL)
SessionLocal = sessionmaker(bind=engine)


async def _noop_async(*a, **k):
    return True

ep._emit_treasury_transfer_event = _noop_async
try:
    import src.teg_core_service.transfer_service_enhanced as tse
    tse._emit_transfer_event = _noop_async
except Exception:
    pass


def reset_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def seed(db):
    for aid, b in [(FEECOLL, 1000), (TREASURY, 1000), (TARGET, 100)]:
        db.add(AgentTEGProfile(
            agent_id=aid, token_balance=Decimal(str(b)), audited_balance=Decimal(str(b)),
            locked_balance=Decimal("0"), wrapped_balance=Decimal("0"),
            reputation_score=0, account_status="active",
        ))
    db.add(SystemConfig(key="treasury_did", value=TREASURY))
    db.add(SystemConfig(key="fee_collection_address", value=FEECOLL))
    db.commit()


def bal(db, aid):
    row = db.query(AgentTEGProfile).filter_by(agent_id=aid).one()
    db.refresh(row)
    return row.token_balance


def idem_status(db, key):
    row = db.query(IdempotencyRecord).filter_by(idempotency_key=key).one_or_none()
    return row.status if row else None


class Req:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def t_req(amount="25"):
    return Req(target_agent_id=TARGET, amount=Decimal(amount), reason="singleidem_test", reference_id="ref-si")


def r_req(amount="25"):
    return Req(source_agent_id=TARGET, amount=Decimal(amount), reason="singleidem_test", reference_id="ref-si")


_LOOP = None


def run(coro):
    """Every scenario's coroutines on ONE private event loop, as asyncio.get_event_loop() gave them until Python 3.14,
    which no longer makes a loop for a thread that has none (it raises "There is no current event loop")."""
    global _LOOP
    if _LOOP is None or _LOOP.is_closed():
        _LOOP = asyncio.new_event_loop()
    return _LOOP.run_until_complete(coro)


# ── Scenario A: happy path + same-key replay moves money ONCE ────────────────
def test_a_happy_and_replay():
    reset_db()
    db = SessionLocal(); seed(db)
    before = bal(db, TARGET)
    r1 = run(ep.treasury_transfer(request=t_req(), is_admin=True, db=db, idempotency_key="si-a"))
    assert str(r1.status) == "completed", f"first call not completed: {r1.status}"
    after1 = bal(db, TARGET)
    assert after1 - before == Decimal("25"), f"paid {after1 - before}, want 25"
    r2 = run(ep.treasury_transfer(request=t_req(), is_admin=True, db=db, idempotency_key="si-a"))
    assert r2.transaction_id == r1.transaction_id, "replay must return the SAME transaction"
    assert bal(db, TARGET) == after1, "replay moved money"
    db.close()


# ── Scenario B: WINDOW A — throw at the label commit must not enable a re-pay ─
def test_b_label_commit_throw_never_double_pays():
    reset_db()
    db = SessionLocal(); seed(db)
    before = bal(db, TARGET)

    real_execute = ep.TransferService.execute_transfer
    real_commit = db.commit
    state = {"armed": False, "thrown": False}

    def wrapped_execute(*a, **k):
        tx = real_execute(*a, **k)
        state["armed"] = True          # the NEXT commit is the label commit
        return tx

    def wrapped_commit(*a, **k):
        if state["armed"] and not state["thrown"]:
            state["thrown"] = True
            state["armed"] = False
            raise RuntimeError("injected: label-commit failure (Window A)")
        return real_commit(*a, **k)

    ep.TransferService.execute_transfer = staticmethod(wrapped_execute)
    db.commit = wrapped_commit
    try:
        try:
            r1 = run(ep.treasury_transfer(request=t_req(), is_admin=True, db=db, idempotency_key="si-b"))
            first_tx = r1.transaction_id           # fixed code: succeeds despite the label failure
        except TEGException:
            first_tx = None                        # pre-fix code: the request 400s
        assert state["thrown"], "the injection never fired — the scenario measured nothing"
        paid1 = bal(db, TARGET) - before
        assert paid1 == Decimal("25"), f"after call 1 paid {paid1}, want exactly 25"

        # Same-key retry. Pre-fix: the key was marked FAILED → deleted → RE-PAID.
        r2 = run(ep.treasury_transfer(request=t_req(), is_admin=True, db=db, idempotency_key="si-b"))
        paid2 = bal(db, TARGET) - before
        assert paid2 == Decimal("25"), f"DOUBLE PAY: after retry paid {paid2}, want exactly 25"
        if first_tx is not None:
            assert r2.transaction_id == first_tx, "retry must replay the same transaction"
    finally:
        ep.TransferService.execute_transfer = real_execute
        db.commit = real_commit
        db.close()


# ── Scenario C: WINDOW B — post-money throw must cache COMPLETED, not pending ─
def test_c_postmoney_throw_caches_completed():
    reset_db()
    db = SessionLocal(); seed(db)
    before = bal(db, TARGET)

    real_logtx = ep.log_transaction

    def boom(*a, **k):
        raise RuntimeError("injected: post-money step failure (Window B)")

    ep.log_transaction = boom
    try:
        try:
            run(ep.treasury_transfer(request=t_req(), is_admin=True, db=db, idempotency_key="si-c"))
            raised = False
        except TEGException:
            raised = True
        assert raised, "the injection never surfaced — the scenario measured nothing"
        assert bal(db, TARGET) - before == Decimal("25"), "the money leg must be durable"
        st = idem_status(db, "si-c")
        assert st == "completed", f"record is {st!r}, want completed (pre-fix: pending → 24h of 409s)"
    finally:
        ep.log_transaction = real_logtx

    # retry with logging healthy again: replays, never re-pays, never 409s
    r2 = run(ep.treasury_transfer(request=t_req(), is_admin=True, db=db, idempotency_key="si-c"))
    assert str(r2.status) == "completed"
    assert bal(db, TARGET) - before == Decimal("25"), "retry moved money"
    db.close()


# ── Scenario D: WINDOW B on treasury_receive (the reverse direction) ─────────
def test_d_receive_postmoney_throw():
    reset_db()
    db = SessionLocal(); seed(db)
    before = bal(db, TARGET)

    real_logtx = ep.log_transaction

    def boom(*a, **k):
        raise RuntimeError("injected: post-money step failure (receive)")

    ep.log_transaction = boom
    try:
        try:
            run(ep.treasury_receive(request=r_req(), is_admin=True, db=db, idempotency_key="si-d"))
        except TEGException:
            pass
        assert before - bal(db, TARGET) == Decimal("25"), "the clawback leg must be durable"
        st = idem_status(db, "si-d")
        assert st == "completed", f"record is {st!r}, want completed"
    finally:
        ep.log_transaction = real_logtx
    r2 = run(ep.treasury_receive(request=r_req(), is_admin=True, db=db, idempotency_key="si-d"))
    assert str(r2.status) == "completed"
    assert before - bal(db, TARGET) == Decimal("25"), "retry moved money"
    db.close()


TESTS = [
    test_a_happy_and_replay,
    test_b_label_commit_throw_never_double_pays,
    test_c_postmoney_throw_caches_completed,
    test_d_receive_postmoney_throw,
]

if __name__ == "__main__":
    # Per-scenario ALARM: the pre-fix code can HANG scenario B (the aborted
    # label-commit transaction keeps its connection wedged and a later
    # statement blocks forever). A mutation run must FAIL legibly, not hang
    # the harness — 60s per scenario is 20x the healthy runtime.
    import signal

    def _alarm(signum, frame):
        raise TimeoutError("scenario exceeded 60s — a hang IS the failure")

    signal.signal(signal.SIGALRM, _alarm)
    failed = 0
    for t in TESTS:
        signal.alarm(60)
        try:
            t()
            print(f"PASS  {t.__name__}", flush=True)
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {t.__name__} — {e}", flush=True)
        except Exception as e:
            failed += 1
            print(f"ERROR {t.__name__} — {type(e).__name__}: {e}", flush=True)
        finally:
            signal.alarm(0)
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed", flush=True)
    sys.exit(1 if failed else 0)
