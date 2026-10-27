"""§OPPROV (2026-09-27) — the cross-TEG fund-send's RESUME, the path an operator purge's drain depends on.

Integration test (real Postgres, real endpoint code) for endpoints_treasury.py::treasury_cross_teg_fund_send. Runs against
a THROWAWAY database whose URL comes from DATABASE_URL (CI's teg-tests job starts one); it never touches a production
schema. The peer TEG is a stand-in client: each scenario scripts what the peer answers.

An operator purge drains the operator TEG's whole treasury through this route, one correlation id per send; a send whose
peer call does not answer stays 'pending' with the treasury debited, and the drain re-sends it under the same id before
anything else (services/operator_drain.py, the frame runner's operator_purge). Three defects on that resume:

  1. the balance pre-flight applied to a resume that debits nothing: the drain had sent the whole balance, the treasury
     read 0 (its own debit) < the amount, and the stalled send could never be resumed;
  2. a retry was not bound to its row: the peer was paid the REQUEST's amount and target, and a completed id replayed with
     another amount answered "completed" though nothing of it moved;
  3. a 4xx on a resume re-credited the treasury: the receiver answers a replayed id with its prior success only after its
     own caller checks, so a check that changed since the first attempt (an operator certificate that expired after its
     revoke is answered 400 by nginx) refused a send the peer may already have credited, and the re-credit paid twice.

RED control: run against the pre-fix endpoints_treasury.py; the four fix scenarios fail there and the three controls pass.
Run:  python tests/test_fund_send_resume.py   (inside a container with the TEG deps; prints "<passed>/<total> passed")
"""
import asyncio
import os
import signal
import sys
from decimal import Decimal

sys.path.insert(0, "/app")

# Must be set before the settings-bound modules import.
os.environ.setdefault("AUDITED_BALANCE_ENABLED", "false")
os.environ.setdefault("TEG_HOME_FRAME_GUARD_ENABLED", "false")

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.teg_core_service.database.models import Base, AgentTEGProfile, SystemConfig, TEGTransaction
import src.teg_core_service.api.v1.endpoints_treasury as ep
import src.teg_core_service.api.cross_teg_router as ctr
from src.teg_core_service.core.error_handling import TEGException

TREASURY = "did:theprotocol:teg_system_treasury"
PEER, OTHER = "teg-parent", "teg-elsewhere"

_raw = os.environ.get("DATABASE_URL_SYNC") or os.environ["DATABASE_URL"]
# the sync driver NAMED (psycopg2), as the TEG names it (§DEPS sqla-driver-pin)
from src.teg_core_service.core.db_url import sync_engine_url  # noqa: E402
DB_URL = sync_engine_url(_raw)
engine = create_engine(DB_URL)
SessionLocal = sessionmaker(bind=engine)


async def _noop_async(*a, **k):
    return True


ep._emit_treasury_transfer_event = _noop_async      # no EventStore here


class Peer:
    """The peer TEG's answers, one per call, in order: "ok", "net" (no answer), or an HTTP status to refuse with."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    async def treasury_fund(self, amount, source_teg_id, correlation_id, reason="cross_teg_fund", auth_token=None):
        self.calls.append({"amount": Decimal(str(amount)), "correlation_id": correlation_id})
        act = self.answers.pop(0) if self.answers else "ok"
        if act == "ok":
            return {"transaction_id": f"peer-{correlation_id}", "status": "completed"}
        req = httpx.Request("POST", "https://peer.test/api/v1/cross-teg/treasury-fund")
        if act == "net":
            raise httpx.ConnectError("injected: the peer did not answer", request=req)
        raise httpx.HTTPStatusError(f"injected {act}", request=req,
                                    response=httpx.Response(int(act), text="injected refusal", request=req))


class Factory:
    def __init__(self):
        self.peer = None
        self.targets = []

    def get_client(self, teg_id, url):
        self.targets.append(teg_id)
        return self.peer


FACTORY = Factory()
ctr.teg_client_factory = FACTORY
ctr.resolve_partner_url = lambda teg_id, url_hint=None: url_hint or f"https://{teg_id}.test:8443"


def reset_db(treasury):
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = SessionLocal()
    db.add(AgentTEGProfile(agent_id=TREASURY, token_balance=Decimal(str(treasury)), audited_balance=Decimal(str(treasury)),
                           locked_balance=Decimal("0"), wrapped_balance=Decimal("0"), reputation_score=0,
                           account_status="active"))
    db.add(SystemConfig(key="teg_system_treasury_did", value=TREASURY))
    db.commit()
    return db


def treasury(db):
    db.expire_all()
    return db.query(AgentTEGProfile).filter(AgentTEGProfile.agent_id == TREASURY).first().token_balance


def row(db, cid):
    db.expire_all()
    r = db.query(TEGTransaction).filter(TEGTransaction.transaction_id == cid).first()
    return None if r is None else (str(getattr(r.status, "value", r.status)), r.amount, r.receiver_agent_id)


def send(db, peer, cid, amount, target=PEER):
    """(http status, response or error message): the route's answer, as the drain reads it."""
    FACTORY.peer = peer
    req = ep.CrossTEGFundSendRequest(amount=Decimal(str(amount)), target_teg_id=target, correlation_id=cid,
                                     reason="teardown_genesis_drain")
    try:
        resp = asyncio.run(ep.treasury_cross_teg_fund_send(request=req, is_admin=True, db=db))
        return 200, resp
    except TEGException as exc:
        return exc.status_code, str(getattr(exc, "message", "") or exc)


# ── the fix ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_drain_of_the_whole_treasury_resumes():
    """1: the drain sent the whole balance, the peer did not answer; the resume debits nothing and completes."""
    db = reset_db(1)
    try:
        code, _ = send(db, Peer("net"), "td-opprovs-0000aaaa-1", 1)
        assert code == 503, f"the first send should stay uncertain (503), got {code}"
        assert treasury(db) == Decimal("0") and row(db, "td-opprovs-0000aaaa-1")[0] == "pending"
        peer = Peer("ok")
        code, resp = send(db, peer, "td-opprovs-0000aaaa-1", 1)
        assert code == 200 and resp.status == "completed", f"FIX FAILED: the resume answered {code} {resp}"
        assert treasury(db) == Decimal("0"), f"a resume must not debit again: treasury {treasury(db)}"
        assert [c["amount"] for c in peer.calls] == [Decimal("1")], peer.calls
        assert row(db, "td-opprovs-0000aaaa-1")[0] == "completed"
    finally:
        db.close()


def test_a_resume_naming_another_amount_is_refused():
    """2: the row was debited 1; a retry naming 2 would pay the peer a value the ledger never debited."""
    db = reset_db(10)
    try:
        send(db, Peer("net"), "td-opprovs-0000aaaa-2", 1)
        peer = Peer("ok")
        code, msg = send(db, peer, "td-opprovs-0000aaaa-2", 2)
        assert code == 409, f"FIX FAILED: a resume naming another amount answered {code} ({msg})"
        assert peer.calls == [], f"nothing may be sent: {peer.calls}"
        assert treasury(db) == Decimal("9") and row(db, "td-opprovs-0000aaaa-2")[:2] == ("pending", Decimal("1"))
    finally:
        db.close()


def test_a_resume_naming_another_partner_is_refused():
    """2: one debit, one peer: a retry naming another partner would pay a second peer for the same debit."""
    db = reset_db(10)
    try:
        send(db, Peer("net"), "td-opprovs-0000aaaa-3", 1)
        peer = Peer("ok")
        code, msg = send(db, peer, "td-opprovs-0000aaaa-3", 1, target=OTHER)
        assert code == 409, f"FIX FAILED: a resume naming another partner answered {code} ({msg})"
        assert peer.calls == [], f"nothing may be sent: {peer.calls}"
        assert treasury(db) == Decimal("9") and row(db, "td-opprovs-0000aaaa-3")[0] == "pending"
    finally:
        db.close()


def test_a_4xx_on_a_resume_does_not_recredit():
    """3: the first attempt's outcome is unknown; a refusal of the resume must not re-credit a value the peer may hold."""
    db = reset_db(10)
    try:
        send(db, Peer("net"), "td-opprovs-0000aaaa-4", 1)
        code, msg = send(db, Peer(400), "td-opprovs-0000aaaa-4", 1)
        assert code == 409, f"FIX FAILED: a 4xx on a resume answered {code} ({msg}); 502 is the re-credit"
        assert treasury(db) == Decimal("9"), f"FIX FAILED: the treasury was re-credited to {treasury(db)}"
        assert row(db, "td-opprovs-0000aaaa-4")[0] == "pending", row(db, "td-opprovs-0000aaaa-4")
        code, resp = send(db, Peer("ok"), "td-opprovs-0000aaaa-4", 1)   # the peer answers again: the send completes
        assert code == 200 and resp.status == "completed" and treasury(db) == Decimal("9")
    finally:
        db.close()


def test_a_completed_id_replayed_with_another_amount_is_refused():
    """2: a replay of a completed id answered "completed" whatever amount it named; nothing of a new amount moved."""
    db = reset_db(10)
    try:
        send(db, Peer("ok"), "td-opprovs-0000aaaa-5", 1)
        peer = Peer("ok")
        code, msg = send(db, peer, "td-opprovs-0000aaaa-5", 3)
        assert code == 409, f"FIX FAILED: a completed id replayed with another amount answered {code} ({msg})"
        assert peer.calls == [] and treasury(db) == Decimal("9")
    finally:
        db.close()


# ── controls: what did not change ────────────────────────────────────────────────────────────────────────────────────

def test_control_a_4xx_on_a_first_send_still_reverses():
    """A first send's 4xx is the peer's deterministic refusal: re-credited, 'reversed', 502 (unchanged)."""
    db = reset_db(10)
    try:
        code, _ = send(db, Peer(400), "td-opprovs-0000aaaa-6", 1)
        assert code == 502, f"a first send's 4xx must still reverse (502), got {code}"
        assert treasury(db) == Decimal("10") and row(db, "td-opprovs-0000aaaa-6")[0] == "reversed"
        peer = Peer("ok")                                              # a retry after 'reversed' debits again, once
        code, resp = send(db, peer, "td-opprovs-0000aaaa-6", 1)
        assert code == 200 and resp.status == "completed" and treasury(db) == Decimal("9"), (code, treasury(db))
        assert len(peer.calls) == 1
    finally:
        db.close()


def test_control_a_completed_replay_returns_its_prior_success():
    """A replay of a completed id with the same amount and partner answers its prior success and sends nothing."""
    db = reset_db(10)
    try:
        send(db, Peer("ok"), "td-opprovs-0000aaaa-7", 1)
        peer = Peer("ok")
        code, resp = send(db, peer, "td-opprovs-0000aaaa-7", "1.000000000000000000")
        assert code == 200 and resp.status == "completed", (code, resp)
        assert peer.calls == [] and treasury(db) == Decimal("9")
    finally:
        db.close()


def test_control_a_new_send_is_still_checked_against_the_balance():
    """A send that debits is refused when the treasury cannot cover it (unchanged), and nothing is written."""
    db = reset_db(1)
    try:
        peer = Peer("ok")
        code, msg = send(db, peer, "td-opprovs-0000aaaa-8", 2)
        assert code == 400 and "Insufficient" in msg, (code, msg)
        assert peer.calls == [] and treasury(db) == Decimal("1") and row(db, "td-opprovs-0000aaaa-8") is None
    finally:
        db.close()


TESTS = [
    test_a_drain_of_the_whole_treasury_resumes,
    test_a_resume_naming_another_amount_is_refused,
    test_a_resume_naming_another_partner_is_refused,
    test_a_4xx_on_a_resume_does_not_recredit,
    test_a_completed_id_replayed_with_another_amount_is_refused,
    test_control_a_4xx_on_a_first_send_still_reverses,
    test_control_a_completed_replay_returns_its_prior_success,
    test_control_a_new_send_is_still_checked_against_the_balance,
]


def _alarm(signum, frame):
    raise TimeoutError("scenario exceeded 60 s (a hang IS the failure)")


if __name__ == "__main__":
    signal.signal(signal.SIGALRM, _alarm)
    failed = 0
    for t in TESTS:
        signal.alarm(60)
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:
            failed += 1
            import traceback
            print(f"FAIL  {t.__name__}: {e}")
            traceback.print_exc()
        finally:
            signal.alarm(0)
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    sys.exit(1 if failed else 0)
