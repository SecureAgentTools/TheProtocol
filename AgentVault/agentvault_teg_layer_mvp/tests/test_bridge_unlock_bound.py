"""SEC-03 (2026-10-17): POST /bridge/unlock releases one bridge lock this TEG made, once, by the lock's own record.

The TEG trusted its admin-token caller: an unlock moved any amount the agent held as locked_balance back to liquid,
whatever had locked it, and its only once-guard was a 24 h idempotency record. The registry binds an unlock to its own
lock record since V0619; the TEG now also asks the lock's own row in the balance journal (written by the trigger in the
lock's transaction: entry_type 'bridge_lock', entry_ref its bridge_tx_id): the same agent, the same amount, no release of
it before. Anything else is refused and nothing is unlocked.

Integration test (real Postgres, real endpoint code, the journal and its trigger applied from the TEG's own
migrations/balance_journal.sql as its startup applies them) against a THROWAWAY database (DATABASE_URL), never a
production schema. Runner style (python tests/test_bridge_unlock_bound.py) for the CI job's "<passed>/<total> passed".
Mutation-verify: against 6f58e596's endpoints_bridge.py the four refusal scenarios fail (each unlock goes through and
releases units no bridge lock of that id holds); the two others pass on both.
"""
import os
import sys
import signal
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, "/app")

os.environ.setdefault("AUDITED_BALANCE_ENABLED", "false")
os.environ.setdefault("TEG_HOME_FRAME_GUARD_ENABLED", "false")

from fastapi import HTTPException                                       # noqa: E402
from sqlalchemy import create_engine, text                              # noqa: E402
from sqlalchemy.orm import sessionmaker                                 # noqa: E402

from src.teg_core_service.database.models import Base, AgentTEGProfile  # noqa: E402
import src.teg_core_service.api.v1.endpoints_bridge as eb               # noqa: E402

ALICE = "did:theprotocol:bridge-alice"
BOB = "did:theprotocol:bridge-bob"

_raw = os.environ.get("DATABASE_URL_SYNC") or os.environ["DATABASE_URL"]
from src.teg_core_service.core.db_url import sync_engine_url           # noqa: E402
engine = create_engine(sync_engine_url(_raw))
SessionLocal = sessionmaker(bind=engine)


def _journal_sql() -> str:
    here = Path(__file__).resolve().parents[1]
    for cand in (here / "src" / "teg_core_service" / "migrations" / "balance_journal.sql",
                 Path("/app/src/teg_core_service/migrations/balance_journal.sql")):
        if cand.exists():
            return cand.read_text()
    raise AssertionError("balance_journal.sql not found in the repo or image layout")


def reset_db():
    with engine.begin() as c:
        c.execute(text("DROP TABLE IF EXISTS balance_ledger_journal"))
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with engine.begin() as c:
        c.exec_driver_sql(_journal_sql())          # the table, its indexes and the trigger, as the TEG's startup applies them
    db = SessionLocal()
    try:
        for aid in (ALICE, BOB):
            db.add(AgentTEGProfile(
                agent_id=aid, token_balance=Decimal("100"), audited_balance=Decimal("100"),
                locked_balance=Decimal("0"), wrapped_balance=Decimal("0"),
                reputation_score=0, account_status="active",
            ))
        db.commit()
    finally:
        db.close()


def held_by_another_mechanism(agent, amount):
    """Units locked by something that is not the bridge (an escrow, a cross-TEG leg), journaled under its own type."""
    with engine.begin() as c:
        c.execute(text("SELECT set_config('teg.entry_type','escrow_lock',true), set_config('teg.entry_ref','other-1',true)"))
        c.execute(text("UPDATE agent_teg_profiles SET token_balance = token_balance - :a, locked_balance = locked_balance + :a, "
                       "audited_balance = token_balance - :a WHERE agent_id = :g"), {"a": Decimal(str(amount)), "g": agent})


def balances(agent):
    db = SessionLocal()
    try:
        p = db.query(AgentTEGProfile).filter(AgentTEGProfile.agent_id == agent).one()
        return p.token_balance, p.locked_balance
    finally:
        db.close()


def journal(ref):
    with engine.connect() as c:
        return [tuple(r) for r in c.execute(text(
            "SELECT entry_type, agent_id, delta_locked FROM balance_ledger_journal WHERE entry_ref = :r ORDER BY id"), {"r": ref})]


def lock(agent, amount, tx):
    db = SessionLocal()
    try:
        return eb.bridge_lock(req=eb.LockReq(agent_id=agent, amount=Decimal(str(amount)), bridge_tx_id=tx),
                              is_admin=True, db=db, idempotency_key=None)
    finally:
        db.close()


def unlock(agent, amount, tx, key=None):
    db = SessionLocal()
    try:
        return eb.bridge_unlock(req=eb.LockReq(agent_id=agent, amount=Decimal(str(amount)), bridge_tx_id=tx),
                                is_admin=True, db=db, idempotency_key=key)
    finally:
        db.close()


def refused(status, agent, amount, tx, key=None):
    before = balances(agent)
    try:
        unlock(agent, amount, tx, key)
    except HTTPException as e:
        assert e.status_code == status, f"status {e.status_code}: {e.detail}"
        assert "nothing unlocked" in str(e.detail), e.detail
        assert balances(agent) == before, "a refused unlock must move nothing"
        return e
    raise AssertionError("the unlock went through")


def test_an_unlock_releases_its_own_lock():
    reset_db()
    lock(ALICE, 5, "btx-0001")
    assert balances(ALICE) == (Decimal("95"), Decimal("5"))
    r = unlock(ALICE, 5, "btx-0001")
    assert r["status"] == "unlocked"
    assert balances(ALICE) == (Decimal("100"), Decimal("0"))
    kinds = [(t, a) for t, a, _ in journal("btx-0001")]
    assert kinds == [("bridge_lock", ALICE), ("bridge_unlock", ALICE)], kinds


def test_a_replayed_unlock_is_answered_once():
    reset_db()
    lock(ALICE, 5, "btx-0002")
    first = unlock(ALICE, 5, "btx-0002")
    again = unlock(ALICE, 5, "btx-0002")                    # the same key (bridge:unlock:<id>): the cached answer
    assert again == first
    assert balances(ALICE) == (Decimal("100"), Decimal("0"))


def test_no_bridge_lock_of_that_id_unlocks_nothing():
    reset_db()
    held_by_another_mechanism(ALICE, 7)                     # 7 locked, but not by the bridge
    refused(404, ALICE, 7, "btx-0003")
    assert balances(ALICE) == (Decimal("93"), Decimal("7")), "units another mechanism locked stay locked"


def test_another_amount_than_the_lock_unlocks_nothing():
    reset_db()
    held_by_another_mechanism(ALICE, 10)
    lock(ALICE, 5, "btx-0004")
    refused(409, ALICE, 8, "btx-0004")                      # 15 locked in all: enough for 8, but the lock was 5


def test_a_lock_is_released_once_whatever_the_key():
    reset_db()
    held_by_another_mechanism(ALICE, 10)
    lock(ALICE, 5, "btx-0005")
    unlock(ALICE, 5, "btx-0005")
    e = refused(409, ALICE, 5, "btx-0005", key="another-key-for-the-same-lock")
    assert "already released" in str(e.detail)
    assert balances(ALICE) == (Decimal("90"), Decimal("10"))


def test_another_agents_lock_unlocks_nothing():
    reset_db()
    held_by_another_mechanism(BOB, 5)
    lock(ALICE, 5, "btx-0006")
    refused(404, BOB, 5, "btx-0006")                        # Bob holds 5 locked, but the lock is Alice's
    assert balances(ALICE) == (Decimal("95"), Decimal("5"))


TESTS = [
    test_an_unlock_releases_its_own_lock,
    test_a_replayed_unlock_is_answered_once,
    test_no_bridge_lock_of_that_id_unlocks_nothing,
    test_another_amount_than_the_lock_unlocks_nothing,
    test_a_lock_is_released_once_whatever_the_key,
    test_another_agents_lock_unlocks_nothing,
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
