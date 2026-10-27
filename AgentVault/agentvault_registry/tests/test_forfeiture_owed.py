"""§LEDGERGATE (V0599, 2026-10-11): an account deletion's forfeiture that moved no money is OWED and drained later with its
own key, never stranded on the revoked agent for good.

Read on V0598 (fe/batch-v0598 4afe37cf; FINDINGS_2026-10-11_TEG_NONNEGATIVE_AND_OUTBOX_GATE.md §9 S3): the anonymization
drains each agent's liquid balance best-effort (the GDPR clock must not stall on the TEG), and a drain that failed left
the balance on the revoked agent: "a forfeiture that moved no money leaves a balance stranded on a revoked agent, and
nothing retries it" (account_deletion_worker). The ledger gate makes an outage a common cause.

  1. the drain says why it moved nothing (word): the gate's refusal, any other refusal, the transport; it still counts
     the two reasons it always counted (test_account_deletion_drain_transport pins them);
  2. the owed forfeiture goes into the anonymization's OWN session (it commits with it or not at all), keyed by the
     forfeiture's own Idempotency-Key;
  3. the worker's decision: drained closes the row; the gate's refusal, a 409, a 403, a 5xx and the transport wait
     longer each time; a 400/404/422 parks it at once; so does the budget;
  4. one worker cycle drains a due row with the row's id as the key and the forfeiture's reason;
  5. the deletion worker fails its cycle only for a failed drain that is NOT owed; the AccountAnonymized payload carries
     the owed count; the worker runs with the registry; the migration is the next revision.
RED on fe/batch-v0598 4afe37cf: all of them (no word, no owed table, no worker, no migration).
"""
from __future__ import annotations

import ast
import asyncio
import contextlib
import datetime
import inspect
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentvault_registry.background_tasks import forfeiture_retry as fr
from agentvault_registry.routers import account_deletion as ad
from agentvault_registry.services import escrow as _escrow
from agentvault_registry.services import ledger_unavailable as lu

NOW = datetime.datetime(2026, 10, 11, 18, 0, tzinfo=datetime.timezone.utc)
SENTENCE_DETAIL = f"{lu.MARKER} {lu.SENTENCE}"
SRC = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("raise_,why", [
    (lambda: _escrow.EscrowError(503, SENTENCE_DETAIL, headers={"Retry-After": "30"}), "ledger_unavailable"),
    (lambda: _escrow.EscrowError(403, "mTLS identity required"), "teg_refused"),
    (lambda: ConnectionError("CERTIFICATE_VERIFY_FAILED"), "transport"),
])
def test_the_drain_says_why_it_moved_nothing(monkeypatch, raise_, why):
    async def failing(*a, **k):
        raise raise_()
    monkeypatch.setattr(_escrow, "escrow_deposit", failing)
    word: dict = {}
    ok = asyncio.run(ad._teg_drain_to_treasury("did:theprotocol:gone-0001", Decimal("7"), "del-1", word=word))
    assert ok is False and word["why"] == why and word["error"]


def test_the_owed_forfeiture_rides_the_anonymizations_own_session():
    added = []
    db = SimpleNamespace(add=added.append)
    ad._owe_forfeiture(db, "did:theprotocol:gone-0001", 42, Decimal("7"), "del-1", "ledger_unavailable", "503: x")
    (row,) = added
    assert row.id == ad._forfeit_ref("del-1", "did:theprotocol:gone-0001") == "acctdel-forfeit-del-1-did:theprotocol:gone-0001"
    assert (row.agent_did, row.developer_id, row.deletion_id, row.amount, row.reason) == (
        "did:theprotocol:gone-0001", 42, "del-1", Decimal("7"), "ledger_unavailable")
    # and the anonymization calls it with ITS session, in the branch where the drain moved nothing
    tree = ast.parse(inspect.getsource(ad.anonymize_developer))
    calls = [c for c in ast.walk(tree) if isinstance(c, ast.Call) and getattr(c.func, "id", None) == "_owe_forfeiture"]
    assert len(calls) == 1 and isinstance(calls[0].args[0], ast.Name) and calls[0].args[0].id == "db"
    src = ast.unparse(tree)
    owed_count = "report['teg_drain_owed'] = int(report['teg_drain_owed']) + 1"
    assert src.index("word=drain_word") < src.index("_owe_forfeiture(db") < src.index(owed_count)


@pytest.mark.parametrize("outcome,final", [
    ({"status": 503, "why": "ledger_unavailable", "error": "503: ledger_unavailable: ..."}, False),
    ({"status": 409, "why": "teg_refused", "error": "409: in flight"}, False),
    ({"status": 403, "why": "teg_refused", "error": "403: mTLS identity required"}, False),
    ({"status": 502, "why": "teg_refused", "error": "502: bad gateway"}, False),
    ({"status": None, "why": "transport", "error": "ConnectError"}, False),
    ({"status": 400, "why": "teg_refused", "error": "400: insufficient balance"}, True),
    ({"status": 404, "why": "teg_refused", "error": "404: agent not found"}, True),
])
def test_the_workers_decision(outcome, final):
    assert fr.next_state(0, {"moved": True}, 288, NOW) == {"done_at": NOW}
    st = fr.next_state(2, outcome, 288, NOW)
    assert st["attempts"] == 3 and st["last_error"] == outcome["error"]
    if final:
        assert st["dead_at"] == NOW and "next_attempt_at" not in st
    else:
        assert "dead_at" not in st and st["next_attempt_at"] - NOW == datetime.timedelta(seconds=120)
    assert fr.next_state(287, outcome, 288, NOW)["dead_at"] == NOW   # the budget parks anything


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return SimpleNamespace(all=lambda: self.rows)

    def scalar(self):
        return 0


class _CycleDb:
    def __init__(self, rows):
        self.rows, self.commits = rows, 0

    async def execute(self, _stmt):
        return _Rows(self.rows)

    async def commit(self):
        self.commits += 1


def test_one_cycle_drains_a_due_row_with_its_own_key(monkeypatch):
    row = SimpleNamespace(id="acctdel-forfeit-del-1-did:theprotocol:gone-0001", agent_did="did:theprotocol:gone-0001",
                          amount=Decimal("7"), attempts=1, done_at=None, dead_at=None, last_error="x",
                          next_attempt_at=NOW, created_at=NOW)
    db = _CycleDb([row])

    @contextlib.asynccontextmanager
    async def ctx():
        yield db
    monkeypatch.setattr(fr, "get_db_context", ctx)
    seen = []

    async def deposit(source_did, amount, ref, *, reason):
        seen.append((source_did, amount, ref, reason))
        return {"status": "ok"}
    monkeypatch.setattr(_escrow, "escrow_deposit", deposit)
    w = fr.ForfeitureRetry()
    asyncio.run(w._cycle_once())
    assert seen == [(row.agent_did, Decimal("7"), row.id, "account_deletion_forfeit")]
    assert row.done_at is not None and db.commits == 1
    assert w._last_stats() == {"drained_this_cycle": 1, "retried_this_cycle": 0, "dead_this_cycle": 0, "open_now": 0}


def test_the_deletion_worker_fails_only_an_unowed_drain_and_the_payload_carries_the_owed():
    import textwrap
    from agentvault_registry.background_tasks import account_deletion_worker as adw
    run = textwrap.dedent(inspect.getsource(adw.AccountDeletionWorker.run_forever))
    assert 'if int(summary["drain_failures"]) > int(summary.get("drain_owed") or 0):' in run
    scan = inspect.getsource(adw.AccountDeletionWorker._scan_and_anonymize)
    assert scan.count('"drain_owed"') == 2   # both returns carry it
    assert '"teg_drain_owed": int(report["teg_drain_owed"])' in inspect.getsource(ad.anonymize_developer)


def test_the_worker_runs_with_the_registry_and_the_migration_is_next():
    from agentvault_registry import main
    m = inspect.getsource(main)
    assert "await get_forfeiture_retry().start()" in m and "await get_forfeiture_retry().stop()" in m
    text = (SRC / "alembic" / "versions" / "0190_forfeiture_owed.py").read_text()
    assert 'revision = "0190_forfeiture_owed"' in text and 'down_revision = "0189_fiat_credit_owed"' in text
    assert len("0190_forfeiture_owed") <= 32
