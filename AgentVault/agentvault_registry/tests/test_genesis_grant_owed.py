"""§LEDGERGATE (V0598, 2026-10-11): a first agent's genesis grant the TEG could not pay is OWED, not lost.

Read on V0597 (FINDINGS_2026-10-11_TEG_NONNEGATIVE_AND_OUTBOX_GATE.md §9 S3): onboarding's `mint_genesis_grant` turned any
TEG failure into `initial_funding_status: failed` and nothing retried it. Now the creation records the grant in
genesis_grants_owed (migration 0188) and answers `deferred`, and background_tasks/genesis_grant_retry pays it with the
creation's own idempotency key once the ledger records again.

  1. the worker's pure decision: completed and exhausted close the row (completed / partial), a failure waits longer each
     time (30 s, 1, 2, 5, then 10 min), past the budget the row is parked, never deleted;
  2. the creation: the gate's refusal (as the TEG client reports it) is owed as `ledger_unavailable` and answers
     `deferred`; any other TEG failure is owed as `teg_error`; if the owed row cannot be written, the old `failed`;
  3. one worker cycle pays a due row through the reward waterfall with `genesis-{agent_did}` and closes it;
  4. the worker starts and stops with the registry, and the migration is the next revision with a short id.
RED on fe/batch-v0597 edee13f7: all of them (no table, no worker, `failed` on every TEG failure).
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

from agentvault_registry.background_tasks import genesis_grant_retry as ggr

NOW = datetime.datetime(2026, 10, 11, 17, 0, tzinfo=datetime.timezone.utc)
REFUSED = ('fund_reward failed for did:x: HTTP 503 — {"detail":"ledger_unavailable: The ledger cannot record this right '
           'now. Nothing was moved. Try again shortly.","code":"ledger_unavailable"}')


def test_the_workers_decision():
    assert ggr.next_state(0, {"status": "completed", "first_transaction_id": "tx1"}, 288, NOW) == {
        "granted_at": NOW, "funding_status": "completed", "transaction_id": "tx1"}
    assert ggr.next_state(3, {"status": "exhausted", "first_transaction_id": None}, 288, NOW)["funding_status"] == "partial"
    waits = [ggr.next_state(n, {"error": "x"}, 288, NOW)["next_attempt_at"] - NOW for n in range(0, 6)]
    assert [int(w.total_seconds()) for w in waits] == [30, 60, 120, 300, 600, 600]
    dead = ggr.next_state(287, {"error": "TEGClientError: x"}, 288, NOW)
    assert dead["dead_at"] == NOW and dead["attempts"] == 288 and "granted_at" not in dead


class _Recorder:
    def __init__(self, fail=False):
        self.fail, self.statements, self.commits = fail, [], 0

    async def execute(self, stmt):
        if self.fail:
            raise RuntimeError("database refused")
        self.statements.append(stmt)

    async def commit(self):
        self.commits += 1


def _ctx(rec):
    @contextlib.asynccontextmanager
    async def ctx():
        yield rec
    return ctx


def _owed_values(rec):
    from sqlalchemy.dialects import postgresql
    (stmt,) = rec.statements
    return {k: v.value for k, v in stmt.compile(dialect=postgresql.dialect()).binds.items()}


@pytest.mark.parametrize("error,reason", [
    (REFUSED, "ledger_unavailable"),
    ("Failed to connect to TEG Layer for fund_reward: ConnectError", "teg_error"),
])
def test_a_failed_grant_is_owed_and_deferred(monkeypatch, error, reason):
    from agentvault_registry import database
    from agentvault_registry.routers import onboarding
    from agentvault_registry.teg_client import TEGClientError
    rec = _Recorder()
    monkeypatch.setattr(database, "get_db_context", _ctx(rec))

    async def refused(*a, **kw):
        raise TEGClientError(error)
    monkeypatch.setattr("agentvault_registry.services.reward_funding.fund_reward_via_waterfall", refused)
    status, ref = asyncio.run(onboarding.mint_genesis_grant("did:theprotocol:first-agent-0001"))
    assert (status, ref) == ("deferred", f"deferred_{reason}")
    vals = _owed_values(rec)
    assert vals["agent_did"] == "did:theprotocol:first-agent-0001" and vals["reason"] == reason
    assert Decimal(str(vals["amount"])) > 0 and rec.commits == 1


def test_an_owed_row_that_cannot_be_written_answers_failed_as_before(monkeypatch):
    from agentvault_registry import database
    from agentvault_registry.routers import onboarding
    from agentvault_registry.teg_client import TEGClientError
    monkeypatch.setattr(database, "get_db_context", _ctx(_Recorder(fail=True)))

    async def refused(*a, **kw):
        raise TEGClientError(REFUSED)
    monkeypatch.setattr("agentvault_registry.services.reward_funding.fund_reward_via_waterfall", refused)
    status, ref = asyncio.run(onboarding.mint_genesis_grant("did:theprotocol:first-agent-0002"))
    assert status == "failed" and ref.startswith("treasury_failed_")


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

    async def execute(self, stmt):
        return _Rows(self.rows)

    async def commit(self):
        self.commits += 1


def test_one_cycle_pays_a_due_row_with_the_creations_own_key(monkeypatch):
    row = SimpleNamespace(agent_did="did:theprotocol:first-agent-0003", amount=Decimal("1000"), attempts=2,
                          granted_at=None, dead_at=None, funding_status=None, transaction_id=None, last_error="x",
                          next_attempt_at=NOW)
    db = _CycleDb([row])
    monkeypatch.setattr(ggr, "get_db_context", _ctx(db))
    calls = []

    async def pay(_db, **kw):
        calls.append(kw)
        return {"status": "completed", "first_transaction_id": "tx-paid"}
    monkeypatch.setattr("agentvault_registry.services.reward_funding.fund_reward_via_waterfall", pay)
    asyncio.run(ggr.GenesisGrantRetry()._cycle_once())
    assert calls == [{"target_agent_did": row.agent_did, "amount": "1000", "reason": "genesis_grant",
                      "reference_id": f"onboard-{row.agent_did}", "idempotency_key": f"genesis-{row.agent_did}"}]
    assert row.granted_at is not None and row.funding_status == "completed" and row.transaction_id == "tx-paid"
    assert db.commits == 1


def test_the_worker_runs_with_the_registry_and_the_migration_is_next():
    from agentvault_registry import main
    src = inspect.getsource(main)
    assert "await get_genesis_grant_retry().start()" in src and "await get_genesis_grant_retry().stop()" in src
    mig = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0188_genesis_grant_owed.py"
    text = mig.read_text()
    assert 'revision = "0188_genesis_grant_owed"' in text and 'down_revision = "0187_template_unit_prose"' in text
    assert len("0188_genesis_grant_owed") <= 32
