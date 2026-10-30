"""D6-808 (2026-10-17): a repeated idempotency key on the two system-account movers is answered from the row it names.

/admin/exchange/move (exref:<key>) and /admin/fx/move (fxref:<key>) replay a COMPLETED row that carries the request's
key instead of moving again. Before the fix both answered that replay from the REQUEST's own from/to/amount and never
compared them with the row, so a key used a second time for a different move (another amount, source or target) was
answered "completed" while nothing moved. Both branches answer a replay: the lookup of a completed row, and the winner
of a concurrent attempt (the partial unique indexes of migrations 0004 and 0006, created here as the migrations
create them).

Integration test (real Postgres, real endpoint code) against a THROWAWAY database (DATABASE_URL), never a production
schema. Runner style (python tests/test_move_replay_key.py) so the CI job's "<passed>/<total> passed" gate reads it.

Mutation-verify: against 6f58e596's endpoints every *_refused scenario fails (the replay answers with the request's
values and the caller is told the move ran) and the stored-scale scenarios fail (the answer carries the request's
amount, not the amount the row moved).
"""
import os
import sys
import asyncio
import signal
from decimal import Decimal

sys.path.insert(0, "/app")

os.environ.setdefault("AUDITED_BALANCE_ENABLED", "false")
os.environ.setdefault("TEG_HOME_FRAME_GUARD_ENABLED", "false")

from sqlalchemy import create_engine, text                                  # noqa: E402
from sqlalchemy.orm import sessionmaker                                     # noqa: E402

from src.teg_core_service.database.models import (                         # noqa: E402
    Base, AgentTEGProfile, SystemConfig, TEGTransaction, TransactionStatus,
)
import src.teg_core_service.api.v1.endpoints_exchange_admin as ex           # noqa: E402
import src.teg_core_service.api.v1.endpoints_treasury as tr                 # noqa: E402
from src.teg_core_service.core.error_handling import TEGException, ErrorCode  # noqa: E402

ESCROW = ex.EXCHANGE_ESCROW_DID
RESERVE = tr._FX_RESERVE_DID
FEECOLL = "teg:system:fee_collector"
TREASURY = "did:theprotocol:teg_system_treasury"
BUYER = "did:theprotocol:replay-buyer"
OTHER = "did:theprotocol:replay-other"

_raw = os.environ.get("DATABASE_URL_SYNC") or os.environ["DATABASE_URL"]
from src.teg_core_service.core.db_url import sync_engine_url               # noqa: E402
engine = create_engine(sync_engine_url(_raw))
SessionLocal = sessionmaker(bind=engine)

# the two indexes the migrations build (0004_exref_unique, 0006_fxref_unique); create_all does not know them
LIVE_INDEXES = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_teg_tx_exref_live ON teg_transactions (attached_message) "
    "WHERE attached_message LIKE 'exref:%' AND status IN ('pending', 'completed') "
    "AND timestamp > '2026-06-13T01:45:00+00:00'",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_teg_tx_fxref_live ON teg_transactions (attached_message) "
    "WHERE attached_message LIKE 'fxref:%' AND status IN ('pending', 'completed') "
    "AND timestamp > '2026-06-13T00:00:00+00:00'",
)


async def _ledger_ok(*a, **k):
    return None

ex.require_ledger = _ledger_ok
tr.require_ledger = _ledger_ok


def reset_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with engine.begin() as c:
        for ddl in LIVE_INDEXES:
            c.execute(text(ddl))
    db = SessionLocal()
    try:
        for aid, b in [(BUYER, 100), (OTHER, 100), (ESCROW, 50), (RESERVE, 50), (FEECOLL, 0), (TREASURY, 1000)]:
            db.add(AgentTEGProfile(
                agent_id=aid, token_balance=Decimal(str(b)), audited_balance=Decimal(str(b)),
                locked_balance=Decimal("0"), wrapped_balance=Decimal("0"),
                reputation_score=0, account_status="active",
            ))
        db.add(SystemConfig(key="fee_collection_address", value=FEECOLL))
        db.add(SystemConfig(key="treasury_did", value=TREASURY))
        db.commit()
    finally:
        db.close()


def balances():
    db = SessionLocal()
    try:
        return {r.agent_id: r.token_balance for r in db.query(AgentTEGProfile).all()}
    finally:
        db.close()


def rows(ref):
    db = SessionLocal()
    try:
        return db.query(TEGTransaction).filter(TEGTransaction.attached_message == ref).all()
    finally:
        db.close()


def ex_move(from_did, to_did, amount, key):
    db = SessionLocal()
    try:
        req = ex.ExchangeMoveRequest(from_did=from_did, to_did=to_did, amount=Decimal(str(amount)),
                                     reason="test", idempotency_key=key)
        return asyncio.run(ex.exchange_move(request=req, is_admin=True, db=db))
    finally:
        db.close()


def fx_move(from_did, to_did, amount, key):
    db = SessionLocal()
    try:
        req = tr.FxMoveRequest(from_did=from_did, to_did=to_did, amount=Decimal(str(amount)),
                               reason="test", idempotency_key=key)
        return asyncio.run(tr.fx_move(request=req, is_admin=True, db=db))
    finally:
        db.close()


def refused(call, *args):
    """The move is refused as a different move under a used key: 422, IDEM_CONFLICTING_REQUEST, nothing moved."""
    before = balances()
    try:
        call(*args)
    except TEGException as e:
        assert e.status_code == 422, f"status {e.status_code}: {e.message}"
        assert e.error_code == ErrorCode.IDEM_CONFLICTING_REQUEST, e.error_code
        assert "nothing moved" in e.message, e.message
        assert balances() == before, "a refused move must move nothing"
        return e
    raise AssertionError("a different move under a used key was answered, not refused")


def winner_inserted_by_a_concurrent_attempt(module, ref, sender, receiver, amount):
    """Stands in for a concurrent attempt under the same key: after the endpoint's replay lookup found nothing, the
    other attempt's row (COMPLETED) lands, so this attempt's own row hits the partial unique index (IntegrityError) and
    the endpoint serves the winner. The row is written through its own session; no balance moves here."""
    state = {}

    async def _insert(*a, **k):
        db = SessionLocal()
        try:
            t = TEGTransaction(sender_agent_id=sender, receiver_agent_id=receiver, amount=Decimal(str(amount)),
                               fee_amount=Decimal("0"), status=TransactionStatus.COMPLETED,
                               transaction_type="transfer", attached_message=ref)
            db.add(t)
            db.commit()
            state["txid"] = t.transaction_id
        finally:
            db.close()

    module.require_ledger = _insert
    return state


# ── /admin/exchange/move (exref:) ──────────────────────────────────────────────────────────────────────────────────

def test_exchange_replay_is_answered_from_the_row():
    reset_db()
    first = ex_move(BUYER, "@exchange_escrow", 5, "ex-key-0001")
    assert first.idempotent_replay is False and first.status == "completed"
    after_first = balances()
    assert after_first[BUYER] == Decimal("95") and after_first[ESCROW] == Decimal("55")
    again = ex_move(BUYER, "@exchange_escrow", 5, "ex-key-0001")
    assert again.idempotent_replay is True and again.transaction_id == first.transaction_id
    assert (again.from_did, again.to_did, again.amount) == (BUYER, ESCROW, Decimal("5"))
    assert balances() == after_first, "a replay moves nothing"
    assert len(rows("exref:ex-key-0001")) == 1


def test_exchange_other_amount_under_a_used_key_is_refused():
    reset_db()
    first = ex_move(BUYER, "@exchange_escrow", 5, "ex-key-0002")
    e = refused(ex_move, BUYER, "@exchange_escrow", 6, "ex-key-0002")
    assert first.transaction_id in e.message, "the refusal names the transaction the key holds"
    assert len(rows("exref:ex-key-0002")) == 1


def test_exchange_other_source_or_target_under_a_used_key_is_refused():
    reset_db()
    ex_move(BUYER, "@exchange_escrow", 5, "ex-key-0003")
    refused(ex_move, OTHER, "@exchange_escrow", 5, "ex-key-0003")      # another source
    refused(ex_move, "@exchange_escrow", BUYER, 5, "ex-key-0003")      # the move turned round: another source and target
    assert len(rows("exref:ex-key-0003")) == 1


def test_exchange_amount_is_compared_as_the_row_stores_it():
    reset_db()
    first = ex_move(BUYER, "@exchange_escrow", "2.0000000000000000001", "ex-key-0004")   # 19 places: stored as 2.000..0
    again = ex_move(BUYER, "@exchange_escrow", "2.0000000000000000001", "ex-key-0004")
    assert again.idempotent_replay is True and again.transaction_id == first.transaction_id
    assert again.amount == Decimal("2.000000000000000000"), f"the row's amount, not the request's: {again.amount}"


def test_exchange_concurrent_winner_with_the_same_move_is_replayed():
    reset_db()
    st = winner_inserted_by_a_concurrent_attempt(ex, "exref:ex-key-0005", BUYER, ESCROW, 5)
    before = balances()
    try:
        r = ex_move(BUYER, "@exchange_escrow", 5, "ex-key-0005")
    finally:
        ex.require_ledger = _ledger_ok
    assert r.idempotent_replay is True and r.transaction_id == st["txid"], "the winner is served"
    assert balances() == before, "the losing attempt moved nothing"


def test_exchange_concurrent_winner_with_another_move_is_refused():
    reset_db()
    st = winner_inserted_by_a_concurrent_attempt(ex, "exref:ex-key-0006", BUYER, ESCROW, 7)
    try:
        e = refused(ex_move, BUYER, "@exchange_escrow", 5, "ex-key-0006")
    finally:
        ex.require_ledger = _ledger_ok
    assert st["txid"] in e.message
    assert len(rows("exref:ex-key-0006")) == 1


# ── /admin/fx/move (fxref:) ────────────────────────────────────────────────────────────────────────────────────────

def test_fx_replay_is_answered_from_the_row():
    reset_db()
    first = fx_move(BUYER, "@fx_reserve", 5, "fx-key-0001")
    after_first = balances()
    assert after_first[BUYER] == Decimal("95") and after_first[RESERVE] == Decimal("55")
    again = fx_move(BUYER, "@fx_reserve", 5, "fx-key-0001")
    assert again.idempotent_replay is True and again.transaction_id == first.transaction_id
    assert (again.from_did, again.to_did, again.amount) == (BUYER, RESERVE, Decimal("5"))
    assert balances() == after_first, "a replay moves nothing"


def test_fx_other_move_under_a_used_key_is_refused():
    reset_db()
    first = fx_move(BUYER, "@fx_reserve", 5, "fx-key-0002")
    e = refused(fx_move, BUYER, "@fx_reserve", 6, "fx-key-0002")                  # another amount
    assert first.transaction_id in e.message
    refused(fx_move, OTHER, "@fx_reserve", 5, "fx-key-0002")                      # another source
    refused(fx_move, "@fx_reserve", BUYER, 5, "fx-key-0002")                      # turned round
    assert len(rows("fxref:fx-key-0002")) == 1


def test_fx_amount_is_compared_as_the_row_stores_it():
    reset_db()
    first = fx_move(BUYER, "@fx_reserve", "3.0000000000000000004", "fx-key-0003")
    again = fx_move(BUYER, "@fx_reserve", "3.0000000000000000004", "fx-key-0003")
    assert again.idempotent_replay is True and again.transaction_id == first.transaction_id
    assert again.amount == Decimal("3.000000000000000000"), f"the row's amount, not the request's: {again.amount}"


def test_fx_concurrent_winner_with_the_same_move_is_replayed():
    reset_db()
    st = winner_inserted_by_a_concurrent_attempt(tr, "fxref:fx-key-0004", BUYER, RESERVE, 5)
    before = balances()
    try:
        r = fx_move(BUYER, "@fx_reserve", 5, "fx-key-0004")
    finally:
        tr.require_ledger = _ledger_ok
    assert r.idempotent_replay is True and r.transaction_id == st["txid"]
    assert balances() == before


def test_fx_concurrent_winner_with_another_move_is_refused():
    reset_db()
    st = winner_inserted_by_a_concurrent_attempt(tr, "fxref:fx-key-0005", BUYER, RESERVE, 9)
    try:
        e = refused(fx_move, BUYER, "@fx_reserve", 5, "fx-key-0005")
    finally:
        tr.require_ledger = _ledger_ok
    assert st["txid"] in e.message
    assert len(rows("fxref:fx-key-0005")) == 1


TESTS = [
    test_exchange_replay_is_answered_from_the_row,
    test_exchange_other_amount_under_a_used_key_is_refused,
    test_exchange_other_source_or_target_under_a_used_key_is_refused,
    test_exchange_amount_is_compared_as_the_row_stores_it,
    test_exchange_concurrent_winner_with_the_same_move_is_replayed,
    test_exchange_concurrent_winner_with_another_move_is_refused,
    test_fx_replay_is_answered_from_the_row,
    test_fx_other_move_under_a_used_key_is_refused,
    test_fx_amount_is_compared_as_the_row_stores_it,
    test_fx_concurrent_winner_with_the_same_move_is_replayed,
    test_fx_concurrent_winner_with_another_move_is_refused,
]


def _alarm(signum, frame):
    raise TimeoutError("scenario exceeded 60 s (a hang is the failure)")


if __name__ == "__main__":
    failed = 0
    signal.signal(signal.SIGALRM, _alarm)
    for t in TESTS:
        signal.alarm(60)
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            import traceback
            print(f"FAIL  {t.__name__}: {e}")
            traceback.print_exc()
        finally:
            signal.alarm(0)
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    sys.exit(1 if failed else 0)
