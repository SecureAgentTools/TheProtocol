"""§TWOAGENT (V0439, 2026-09-24) — a PASSED federation-suite outcome keeps which legs ran.

Found reading V0438's own proof: three flows reported `passed`, and a reader counting their legs met an empty map,
because `TestOutcome.to_dict()` dropped `last_state` for every state but `failed`; `all()` over that empty map reads
True, which is the trap the doctrine names. The pass was real (each flow derives `passed` from its planned legs), but it
could not be audited from its result. A passed outcome now keeps the leg map as booleans and `not_run`, never the evidence
(which would bloat the nightly history; the summary reads `last_state` only from red rows). RED on 04642a97 (V0438): the
first test; the others pass on both trees.
"""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://ci:ci@localhost:5432/ci")
os.environ.setdefault("API_KEY_SECRET", "ci-dummy-secret-0123456789abcdef")

from agentvault_registry.api_tests.federation_suite import decorator as dec


def _spec(name):
    return dec.FederationTestSpec(name=name, category="c", budget_sec=1.0, severity="low", requires=[], tags=[],
                                  runner=None)


def _outcome(state, last_state):
    return dec.TestOutcome(spec=_spec("t"), state=state, arrange_ms=0, act_ms=1, propagation_ms=0, total_ms=1,
                           last_state=last_state)


STATE = {"legs": {"the_offer_lands": True, "the_owner_hears_it": True}, "not_run": [],
         "evidence": {"the_offer_lands": {"a": "x" * 5000}}}


def test_a_pass_keeps_its_leg_map_and_no_evidence():
    d = _outcome("passed", STATE).to_dict()
    assert d["last_state"] == {"legs": {"the_offer_lands": True, "the_owner_hears_it": True}, "not_run": []}


def test_control_a_failure_keeps_everything():
    assert _outcome("failed", STATE).to_dict()["last_state"] == STATE


def test_control_a_pass_without_a_leg_map_carries_nothing():
    assert _outcome("passed", {"peer": 4}).to_dict()["last_state"] is None
    assert _outcome("passed", None).to_dict()["last_state"] is None


def test_control_skips_and_errors_carry_nothing():
    for st in ("skipped", "errored", "vacuous"):
        assert _outcome(st, STATE).to_dict()["last_state"] is None, st
