"""§DOCSFIX D6-687 (2026-10-16): an agreeing Forge verifier is paid once per settled verdict.

The verifier payment's idempotency key was `forge-verify-{task_id}-{verifier_did}`: no candidate, no run. The TEG keeps a
reward-fund key 24 hours with its parameters, and a verifier's pay is the same amount each time, so inside that window a
verifier that graded the same task for another candidate, or for the same candidate in a later run, was answered from
its first payment: paid once for several verdicts. The key names the run, the task and the (candidate, verifier) pair
now (the pair as a digest, which keeps the key inside the TEG's 255 characters), so each settled verdict pays.

Driven through EvalRunner.run_suite and the real quorum; the verifiers' answers and the funding rail are fakes, the
rail keeping keys as the TEG does (same key and parameters: the first result again, nothing paid).

§DOCSFIX review: the run in the key is the run's pay slot (a scheduled run's due time, or the UTC day of a run started
on demand), never a random run id: a candidate starts runs of itself (POST /forge/evals/run), and with a fresh id each
run paid every agreeing verifier again from the treasury; two workers running one scheduled run paid it twice.

RED on the pre-change tree: the two tests that expect a second payment ("two candidates", "a later scheduled run"). RED
before the review: "a candidate's own runs" and "two workers". The controls are green before and after.
"""
from __future__ import annotations

import asyncio
import types
from decimal import Decimal

import pytest

from agentvault_registry.background_tasks import eval_runner as er
from agentvault_registry.background_tasks import push_notify
from agentvault_registry.routers import teg_integration as ti
from agentvault_registry.services import forge_verify as fv

C1 = "did:theprotocol:eu.theprotocol.cloud:candidate-0001"
C2 = "did:theprotocol:eu.theprotocol.cloud:candidate-0002"
V1 = "did:theprotocol:eu.theprotocol.cloud:verifier-0001"
V2 = "did:theprotocol:eu.theprotocol.cloud:verifier-0002"
SUITE = types.SimpleNamespace(id=3, key="patch-bench", pay_per_task=Decimal("0"), emit_reputation_signal=False,
                              task_type="code_patch")
TASK = types.SimpleNamespace(id=21, scorer="code_patch", expected=None, weight=1.0, input={}, grader_config={},
                             holdout=True)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Db:
    async def execute(self, *a, **k):
        return types.SimpleNamespace(scalars=lambda: types.SimpleNamespace(all=lambda: [TASK]), first=lambda: None)

    def add(self, obj):
        pass

    async def commit(self):
        pass


@pytest.fixture
def forge(monkeypatch):
    rail = types.SimpleNamespace(keys={}, paid=[], fractions={V1: 1.0, V2: 1.0})

    async def _fund(db, req, actor_label, idempotency_key=None):
        assert len(idempotency_key) <= 255
        params = (req.target_agent_did, req.amount, req.reason)
        if idempotency_key in rail.keys:
            if rail.keys[idempotency_key] != params:
                raise RuntimeError("409 IDEM_CONFLICTING_REQUEST")
            return {"cached": True}
        rail.keys[idempotency_key] = params
        rail.paid.append(req.target_agent_did)
        return {}

    async def _verifiers(db, exclude_did, limit):
        return [V1, V2]

    async def _answer(client, endpoint, job):
        return {"frac": rail.fractions[job["verifier_did"]], "sig": None}

    async def _endpoint(self, db, did):
        return "https://verifier.example"

    async def _notify(*a, **k):
        return None
    monkeypatch.setenv("FORGE_ENABLED", "true")
    monkeypatch.setenv("FORGE_VERIFIER_QUORUM", "2")
    monkeypatch.delenv("FORGE_VERIFIER_ENDPOINT_OVERRIDE", raising=False)
    monkeypatch.setattr(ti, "_fund_agent_from_treasury_internal", _fund)
    monkeypatch.setattr(fv, "select_verifiers", _verifiers)
    monkeypatch.setattr(fv, "_dispatch_one", _answer)
    monkeypatch.setattr(er.EvalRunner, "_agent_endpoint", _endpoint)
    monkeypatch.setattr(push_notify, "notify_agent_owners", _notify)
    return rail


def _suite_run(*candidates, pay_slot=None):
    return _run(er.EvalRunner().run_suite(_Db(), SUITE, only_dids=list(candidates), pay_slot=pay_slot))


def test_a_verifier_grading_the_task_for_two_candidates_is_paid_for_both_verdicts(forge):
    _suite_run(C1, C2)
    assert sorted(forge.paid) == [V1, V1, V2, V2]


def test_a_verifier_grading_the_same_candidate_in_a_later_scheduled_run_is_paid_again(forge):
    _suite_run(C1, pay_slot="s1792000000")
    _suite_run(C1, pay_slot="s1792003600")
    assert sorted(forge.paid) == [V1, V1, V2, V2]


def test_runs_a_candidate_starts_itself_pay_the_verifiers_once_a_day(forge):
    _suite_run(C1)
    _suite_run(C1)
    assert sorted(forge.paid) == [V1, V2]


def test_two_workers_running_one_scheduled_run_pay_the_verifiers_once(forge):
    _suite_run(C1, pay_slot="s1792000000")
    _suite_run(C1, pay_slot="s1792000000")
    assert sorted(forge.paid) == [V1, V2]


# ── controls: green before and after ─────────────────────────────────────────────────────────────────────────────

def test_control_one_verdict_pays_each_agreeing_verifier_once(forge):
    _suite_run(C1)
    assert sorted(forge.paid) == [V1, V2]


def test_control_an_inconclusive_quorum_pays_nobody(forge):
    forge.fractions[V2] = 0.0   # 1.0 against 0.0: fewer than two agree within the margin
    _suite_run(C1)
    assert forge.paid == []
