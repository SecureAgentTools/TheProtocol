"""§DOCSFIX D6-673 (2026-10-16): a paid eval suite pays each agent once per run.

The single-leg payment's idempotency key was `eval-roy-eval:<suite key>`: no agent, no run. The TEG keeps a reward-fund
key for 24 hours with its parameters (target, amount, reason), so inside that window a second agent's payment was
refused as a conflicting request (409) and the same agent's next run was answered from the first payment without
moving units: a paid suite paid out at most once per 24 hours. The key names the run, the agent and the leg now, so
each run pays each passing agent once, and a retry of one leg is still answered from its first payment.

The fake funding rail below keeps keys as the TEG does: a key reused with other parameters raises (the 409), a key
reused with the same parameters answers its first result and pays nothing.

§DOCSFIX review: the run in the key is the run's pay slot, never a random run id. A run id is new each time a run is
executed, so a run executed twice was paid twice: by two workers (the leader lease is 30 s and a tick can last longer,
so a second worker runs a suite whose next_run_at the first has not committed), and above all by a run the payee starts
itself (POST /forge/evals/run runs a suite against the caller, and a run with a passing task pays it from the treasury:
an agent could pay itself again and again). A scheduled run is keyed by its due time, so each scheduled run pays and two
executions of one run pay once; a run started on demand is keyed by the UTC day, so it pays a passing agent once a day
per suite.

RED on the pre-change tree: "one run pays every passing agent" and "each scheduled run pays". RED before the review:
"two workers ... pay once" and "runs an agent starts itself ... once a day". The controls are green before and after.
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime
import types
from decimal import Decimal

import pytest

from agentvault_registry.background_tasks import eval_runner as er
from agentvault_registry.background_tasks import push_notify
from agentvault_registry.routers import teg_integration as ti
from agentvault_registry.services import forge_royalty

A = "did:theprotocol:eu.theprotocol.cloud:agent-aaaa"
B = "did:theprotocol:eu.theprotocol.cloud:agent-bbbb"
ORG = "did:theprotocol:orgtreasury-lineage"
SUITE = types.SimpleNamespace(id=1, key="uptime", pay_per_task=Decimal("2"), emit_reputation_signal=False,
                              task_type="http_probe")
TASK = types.SimpleNamespace(id=11, scorer="status_ok", expected=None, weight=1.0, input={})


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Db:
    async def execute(self, *a, **k):
        return types.SimpleNamespace(scalars=lambda: types.SimpleNamespace(all=lambda: [TASK]))

    def add(self, obj):
        pass

    async def commit(self):
        pass


@pytest.fixture
def teg(monkeypatch):
    rail = types.SimpleNamespace(keys={}, paid=[])

    async def _fund(db, req, actor_label, idempotency_key=None):
        params = (req.target_agent_did, req.amount, req.reason)
        if idempotency_key in rail.keys:
            if rail.keys[idempotency_key] != params:
                raise RuntimeError("409 IDEM_CONFLICTING_REQUEST")
            return {"cached": True}
        rail.keys[idempotency_key] = params
        rail.paid.append((req.target_agent_did, req.amount))
        return {}

    async def _endpoint(self, db, did):
        return "https://agent.example"

    async def _passes(self, suite, task, did, endpoint, db=None, **kw):
        return 1.0, True, 12, "ok", None

    async def _legs(db, amount, did):
        return [(did, amount)]

    async def _notify(*a, **k):
        return None
    monkeypatch.setattr(ti, "_fund_agent_from_treasury_internal", _fund)
    monkeypatch.setattr(er.EvalRunner, "_agent_endpoint", _endpoint)
    monkeypatch.setattr(er.EvalRunner, "_run_one", _passes)
    monkeypatch.setattr(forge_royalty, "compute_legs", _legs)
    monkeypatch.setattr(push_notify, "notify_agent_owners", _notify)
    return rail


def _suite_run(*dids, pay_slot=None):
    return _run(er.EvalRunner().run_suite(_Db(), SUITE, only_dids=list(dids), pay_slot=pay_slot))


def test_one_run_pays_every_passing_agent(teg):
    _suite_run(A, B)
    assert teg.paid == [(A, "2"), (B, "2")]


def test_each_scheduled_run_pays_its_agent_again(teg):
    _suite_run(A, pay_slot="s1792000000")
    _suite_run(A, pay_slot="s1792003600")
    assert teg.paid == [(A, "2"), (A, "2")]


def test_two_workers_running_one_scheduled_run_pay_it_once(teg):
    _suite_run(A, pay_slot="s1792000000")
    _suite_run(A, pay_slot="s1792000000")
    assert teg.paid == [(A, "2")]


def test_runs_an_agent_starts_itself_pay_it_once_a_day(teg):
    # POST /forge/evals/run (run_suite_once_for) passes no slot: the day's run
    _suite_run(A)
    _suite_run(A)
    assert teg.paid == [(A, "2")]


def test_the_scheduler_hands_both_workers_the_slot_of_the_due_time(monkeypatch):
    due = datetime.datetime(2026, 10, 16, 12, 0, tzinfo=datetime.timezone.utc)
    slots = []

    async def _capture(self, db, suite, only_dids=None, pay_slot=None):
        slots.append(pay_slot)
        return "run"

    class _TickDb:
        def __init__(self, suite):
            self.suite = suite

        async def execute(self, *a, **k):
            return types.SimpleNamespace(scalars=lambda: types.SimpleNamespace(all=lambda: [self.suite]))

        async def commit(self):
            pass

    def _worker():
        # each worker reads the suite as committed: the same due time until the first one commits its next_run_at
        suite = types.SimpleNamespace(id=1, key="uptime", interval_minutes=60, next_run_at=due)

        @contextlib.asynccontextmanager
        async def _ctx():
            yield _TickDb(suite)
        return _ctx
    monkeypatch.setattr(er.EvalRunner, "run_suite", _capture)
    for _ in range(2):
        monkeypatch.setattr(er, "get_db_context", _worker())
        _run(er.EvalRunner()._tick())
    assert slots == [er.scheduled_pay_slot(types.SimpleNamespace(next_run_at=due))] * 2 == [f"s{int(due.timestamp())}"] * 2


def test_control_a_day_later_an_agents_own_run_pays_again():
    day = datetime.datetime(2026, 10, 16, 23, 59, tzinfo=datetime.timezone.utc)
    assert er.on_demand_pay_slot(day) == "d20261016" != er.on_demand_pay_slot(day + datetime.timedelta(minutes=2))


# ── controls: green before and after ─────────────────────────────────────────────────────────────────────────────

def test_control_a_run_pays_a_passing_agent_once(teg):
    _suite_run(A)
    assert teg.paid == [(A, "2")]


def test_control_a_royalty_split_pays_every_leg(teg, monkeypatch):
    async def _split(db, amount, did):
        return [(did, Decimal("1.5")), (ORG, Decimal("0.5"))]
    monkeypatch.setattr(forge_royalty, "compute_legs", _split)

    async def _notify_legs(*a, **k):
        return None
    monkeypatch.setattr(forge_royalty, "notify_royalty_legs", _notify_legs)
    _suite_run(A)
    assert teg.paid == [(A, "1.5"), (ORG, "0.5")]
