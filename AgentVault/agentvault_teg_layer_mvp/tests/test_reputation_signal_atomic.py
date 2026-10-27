"""§TRUSTCHAIN (2026-09-12) — the TEG reputation-signal LOST UPDATE, and the one implementation.

THE DEFECT (measured 2026-09-10, FINDINGS_2026-09-10_REPUTATION_SIGNAL.md §2): the live
`POST /token/{tx}/reputation-signal` read the receiver's score into Python, added the signal,
and wrote the sum back ABSOLUTELY, with no lock and no atomic increment. Two callers in flight
for one receiver both read N and both wrote N+1; 9 of 764 concurrent signals were lost and every
one of them answered 200 "applied" with somebody else's number. Two more handlers carried copies of
the same arithmetic, one of them with a per-PROCESS dedup dict on a nine-worker service.

THE FIX: `ReputationService.apply_signal` — the claim (`UPDATE teg_transactions SET
reputation_signal_applied = TRUE WHERE ... IS NOT TRUE`) and the score (`UPDATE agent_teg_profiles
SET reputation_score = GREATEST(0, reputation_score + :v) ... RETURNING reputation_score`) in ONE
database transaction, RETURNING as the caller's own answer; all three handlers call it.

Integration test: real Postgres, the real handler code. Runs against a THROWAWAY database
(DATABASE_URL) — never a production schema. Harness: scratchpad/trustchain/teg_signal_harness.sh.

⚠ A SEQUENTIAL TEST PASSES ON THE BROKEN CODE AND PROVES NOTHING. Scenario A drives N callers
CONCURRENTLY and asserts the score moved by exactly N. To make the pre-fix code fail
DETERMINISTICALLY rather than "sometimes", it gates the old code's read (`get_reputation`) behind a
barrier so every reader has read before any writer writes: the old code then lands at 1, not N.
The fixed handler never calls `get_reputation`, so the gate is inert on the fixed code.

Mutation-verify (the RED control): `SRC=<git archive of the pre-fix TEG tree>` in the harness runs
this file against the old code — A fails on the count, B/C error on the missing service, D fails on
the AST. Runner exits non-zero on any failure — a suite that cannot fail measures nothing.

Run:  python tests/test_reputation_signal_atomic.py   (inside a container with TEG deps)
"""
import ast
import asyncio
import os
import pathlib
import sys
import threading
from decimal import Decimal

sys.path.insert(0, "/app")

os.environ.setdefault("AUDITED_BALANCE_ENABLED", "false")
os.environ.setdefault("TEG_HOME_FRAME_GUARD_ENABLED", "false")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from src.teg_core_service.database.models import (
    Base, AgentTEGProfile, TEGTransaction, TransactionStatus,
)
from src.teg_core_service.database import crud as crud_mod
import src.teg_core_service.api.v1.endpoints_token as ep
from src.teg_core_service.api.v1.schemas import ReputationSignalRequest

RECEIVER = "did:theprotocol:sigatomic-receiver"
RECEIVER_ZERO = "did:theprotocol:sigatomic-receiver-zero"
SENDER = "did:theprotocol:sigatomic-sender-{i}"
N = int(os.environ.get("SIGATOMIC_N", "16"))

_raw = os.environ.get("DATABASE_URL_SYNC") or os.environ["DATABASE_URL"]
# the sync driver NAMED (psycopg2), as the TEG names it (§DEPS sqla-driver-pin)
from src.teg_core_service.core.db_url import sync_engine_url  # noqa: E402
DB_URL = sync_engine_url(_raw)
# NullPool: every worker thread opens its own connection, so N concurrent callers are N
# concurrent database sessions rather than N threads queueing on a five-connection pool.
engine = create_engine(DB_URL, poolclass=NullPool)
SessionLocal = sessionmaker(bind=engine)


def reset_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def _profile(agent_id, score=0):
    return AgentTEGProfile(
        agent_id=agent_id, token_balance=Decimal("0"), audited_balance=Decimal("0"),
        locked_balance=Decimal("0"), wrapped_balance=Decimal("0"),
        reputation_score=score, account_status="active",
    )


def _completed_transfer(tx_id, sender, receiver):
    return TEGTransaction(
        transaction_id=tx_id, sender_agent_id=sender, receiver_agent_id=receiver,
        amount=Decimal("1"), fee_amount=Decimal("0"), status=TransactionStatus.COMPLETED,
        transaction_type="transfer", reputation_signal_applied=False,
    )


def seed(db, n):
    db.add(_profile(RECEIVER, 0))
    db.add(_profile(RECEIVER_ZERO, 0))
    for i in range(n):
        db.add(_profile(SENDER.format(i=i), 0))
        db.add(_completed_transfer(f"sig-{i}", SENDER.format(i=i), RECEIVER))
    db.add(_completed_transfer("sig-zero", SENDER.format(i=0), RECEIVER_ZERO))
    db.add(_completed_transfer("sig-cap", SENDER.format(i=1), RECEIVER))
    db.commit()


def score_of(agent_id):
    db = SessionLocal()
    try:
        row = db.query(AgentTEGProfile).filter_by(agent_id=agent_id).one()
        db.refresh(row)
        return row.reputation_score
    finally:
        db.close()


def signal_via_handler(tx_id, sender, value=1):
    """Drive the REAL handler on its own session and its own event loop (one per thread)."""
    db = SessionLocal()
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(ep.apply_reputation_signal(
            transaction_id=tx_id, request=ReputationSignalRequest(signal_value=value),
            agent_id=sender, db=db,
        ))
    finally:
        db.close()
        loop.close()


# ── Scenario A: N concurrent signals move the score by exactly N ────────────────
def test_a_concurrent_signals_lose_nothing():
    reset_db()
    db = SessionLocal(); seed(db, N); db.close()

    # The gate that makes the OLD code fail deterministically: every reader reads before any
    # writer writes. The fixed handler never calls get_reputation, so this is inert on it.
    barrier = threading.Barrier(N)
    real_get = crud_mod.ReputationService.get_reputation

    def gated_get(db_, agent_id):
        out = real_get(db_, agent_id)
        try:
            barrier.wait(timeout=20)
        except threading.BrokenBarrierError:
            pass
        return out

    crud_mod.ReputationService.get_reputation = staticmethod(gated_get)
    results, errors = [], []

    def worker(i):
        try:
            results.append(signal_via_handler(f"sig-{i}", SENDER.format(i=i)))
        except Exception as e:  # noqa: BLE001
            errors.append(f"{type(e).__name__}: {e}")

    try:
        threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
    finally:
        crud_mod.ReputationService.get_reputation = staticmethod(real_get)

    assert not errors, f"{len(errors)} of {N} callers errored: {errors[:3]}"
    assert len(results) == N, f"only {len(results)} of {N} callers returned"
    assert all(r.status == "applied" for r in results), "a caller was not told 'applied'"
    final = score_of(RECEIVER)
    assert final == N, f"{N} signals applied, score moved to {final}: {N - final} LOST"
    told = sorted(r.new_receiver_reputation for r in results)
    assert told == list(range(1, N + 1)), (
        f"callers were told {told}; each must receive its OWN increment, not a re-read of the row"
    )


# ── Scenario B: the claim is the dedup, on the wire and underneath it ───────────
def test_b_second_signal_on_one_transaction_is_refused_and_moves_nothing():
    before = score_of(RECEIVER)
    try:
        signal_via_handler("sig-0", SENDER.format(i=0))
        raise AssertionError("a second signal on sig-0 was accepted by the handler")
    except AssertionError:
        raise
    except Exception as e:  # noqa: BLE001 — the handler raises its own TEGException
        assert "already applied" in str(getattr(e, "message", e)).lower(), f"wrong refusal: {e}"
    # Underneath the handler's Python check sits the atomic claim; it must refuse on its own.
    db = SessionLocal()
    try:
        try:
            crud_mod.ReputationService.apply_signal(db, "sig-1", RECEIVER, 1)
            raise AssertionError("apply_signal claimed an already-claimed transaction")
        except crud_mod.ReputationSignalAlreadyApplied:
            pass
    finally:
        db.close()
    assert score_of(RECEIVER) == before, "a refused signal moved the score"


# ── Scenario C: the clamps live in the database expression, the claim is still consumed ──
def test_c_clamps_are_in_the_statement():
    db = SessionLocal()
    try:
        # negative signal on a zero score stays at zero (GREATEST)
        got = crud_mod.ReputationService.apply_signal(db, "sig-zero", RECEIVER_ZERO, -1)
        assert got == 0, f"GREATEST(0, 0 - 1) returned {got}"
        # the service-token route's historical cap (LEAST) — receiver sits at N after scenario A
        got = crud_mod.ReputationService.apply_signal(db, "sig-cap", RECEIVER, 1, cap=N)
        assert got == N, f"LEAST({N}, {N} + 1) returned {got}"
        # a clamped signal still consumed its claim
        try:
            crud_mod.ReputationService.apply_signal(db, "sig-cap", RECEIVER, 1, cap=N)
            raise AssertionError("a clamped signal left its transaction claimable")
        except crud_mod.ReputationSignalAlreadyApplied:
            pass
    finally:
        db.close()
    assert score_of(RECEIVER) == N and score_of(RECEIVER_ZERO) == 0


# ── Scenario D: ONE implementation — every handler calls the service, none does the arithmetic ──
HANDLERS = {
    "api/v1/endpoints_token.py": "apply_reputation_signal",
    "api/v1/endpoints_token_jwt_svid.py": "apply_reputation_signal",
    "api/v1/endpoints_reputation_signal.py": "submit_reputation_signal",
}


def _handler_body(path: pathlib.Path, name: str) -> ast.AST:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{path.name}: no handler named {name}")


def test_d_one_implementation_by_ast():
    src = pathlib.Path(os.environ.get("TEG_SRC_DIR", "/app/src/teg_core_service"))
    for rel, name in HANDLERS.items():
        fn = _handler_body(src / rel, name)
        calls = [
            n for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "apply_signal"
            and isinstance(n.func.value, ast.Name) and n.func.value.id == "ReputationService"
        ]
        assert calls, f"{rel}::{name} does not call ReputationService.apply_signal"
        for n in ast.walk(fn):
            if isinstance(n, ast.Attribute) and n.attr == "reputation_score" and isinstance(
                getattr(n, "ctx", None), ast.Store
            ):
                raise AssertionError(f"{rel}::{name} still assigns reputation_score in Python")
            if isinstance(n, ast.Compare) and any(
                isinstance(c, ast.Name) and c.id == "reputation_signals" for c in n.comparators
            ):
                raise AssertionError(f"{rel}::{name} still consults the per-process dict")


TESTS = [
    test_a_concurrent_signals_lose_nothing,
    test_b_second_signal_on_one_transaction_is_refused_and_moves_nothing,
    test_c_clamps_are_in_the_statement,
    test_d_one_implementation_by_ast,
]

if __name__ == "__main__":
    # Per-scenario ALARM (the §TEGTESTS shape): a hang IS the failure, never a stuck harness.
    import signal

    def _alarm(signum, frame):
        raise TimeoutError("scenario exceeded 90s — a hang IS the failure")

    signal.signal(signal.SIGALRM, _alarm)
    failed = 0
    for t in TESTS:
        signal.alarm(90)
        try:
            t()
            print(f"PASS  {t.__name__}", flush=True)
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {t.__name__} — {e}", flush=True)
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"ERROR {t.__name__} — {type(e).__name__}: {e}", flush=True)
        finally:
            signal.alarm(0)
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed", flush=True)
    sys.exit(1 if failed else 0)
