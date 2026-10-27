"""§SENDEARLY (2026-09-26): a federation row can act at the start of the run and be judged at its end.

His words: "fix the test so the transfer goes out at the beginning of the test run and success is measured later in the
test run", then "1. yes 2. yes 3. yes" (send as soon as the converting frame knows the receiver, a five-minute
re-delivery on the sandbox pair, both directions). Pinned here:
  - the runner: a `start_first` row acts before every other row (even at a concurrency of 1) and, when it returns a
    DeferredCheck, is judged after all of them; one row, in its place; a DeferredCheck from any other row is an error;
  - the verdict's three states (an unmet precondition is a skip, never a red);
  - `classify_send` against the rail's own sentences, and those sentences still exist in the rail;
  - both cross-frame operator rows are start_first and send early.
RED control: the tree before §SENDEARLY fails every test here (no DeferredCheck, no execute_all, no classify_send).
"""
from __future__ import annotations

import asyncio
import inspect
import os
import pathlib

from agentvault_registry.api_tests.federation_suite import decorator as dec
from agentvault_registry.api_tests.federation_suite.rig import AssertionResult, DeferredCheck, PreconditionUnmet
from agentvault_registry.api_tests.federation_suite.runner import execute_all
from agentvault_registry.api_tests.federation_suite.tests import test_cross_frame_economic_flows as xf
from agentvault_registry.api_tests.federation_suite.tests.test_operator_money_rails import classify_send

_HERE = pathlib.Path(__file__).resolve()
_PKG = pathlib.Path(os.environ["OPDIST_SRC"]) if os.environ.get("OPDIST_SRC") else (
    _HERE.parents[1] / "src" / "agentvault_registry")
_RID = "7aa8c9a0-2fc8-4a34-a1b7-c1638e1dc434"


def _ok(desc="ok", passed=True):
    return AssertionResult(passed=passed, description=desc, budget_sec=1.0, elapsed_sec=0.0, polling_attempts=1)


def _spec(name, fn, start_first=False):
    return dec.FederationTestSpec(name=name, category="c", budget_sec=1.0, severity="low", requires=[],
                                  tags=["no-probe"], runner=fn, start_first=start_first)


def _normal(name, log, pause=0.05):
    async def run(rig):
        log.append(("start", name))
        await asyncio.sleep(pause)
        log.append(("end", name))
        return _ok()
    return run


async def test_a_start_first_row_acts_first_and_is_judged_after_every_other_row():
    log = []

    async def early(rig):
        log.append(("act", "early"))

        async def check():
            log.append(("verdict", "early"))
            return _ok("judged")
        return DeferredCheck(check=check)

    specs = [_spec("n1", _normal("n1", log)), _spec("early", early, start_first=True), _spec("n2", _normal("n2", log))]
    # a bound of ONE is the hard case: the early row must not queue behind the bounded ones
    outcomes = await execute_all(specs, rig=object(), concurrency=1)
    assert log[0] == ("act", "early"), log
    assert log[-1] == ("verdict", "early"), log
    assert [o.spec.name for o in outcomes] == ["n1", "early", "n2"], "rows stay in candidate order"
    early_row = outcomes[1]
    assert early_row.state == "passed" and early_row.pending is None
    assert early_row.total_ms >= max(o.total_ms for o in (outcomes[0], outcomes[2])), \
        "the row's time spans the act, the wait and the verdict"
    assert "pending" not in early_row.to_dict(), "the pending check is never reported"


async def test_a_start_first_row_that_answers_at_once_is_judged_at_once():
    async def early(rig):
        return _ok("refunded before converting", passed=False)
    outcomes = await execute_all([_spec("early", early, start_first=True)], rig=object(), concurrency=4)
    assert outcomes[0].state == "failed"


async def test_a_deferred_check_from_an_ordinary_row_is_an_error():
    async def wrong(rig):
        return DeferredCheck(check=lambda: None)
    outcomes = await execute_all([_spec("wrong", wrong)], rig=object(), concurrency=4)
    assert outcomes[0].state == "errored" and "DeferredCheck" in (outcomes[0].error_repr or "")


async def test_the_verdict_keeps_the_three_states():
    def row(check):
        async def early(rig):
            return DeferredCheck(check=check)
        return _spec("early", early, start_first=True)

    async def unmet():
        raise PreconditionUnmet("the receiver never reached the converting frame")

    async def boom():
        raise RuntimeError("probe broke")

    async def red():
        return _ok("not re-delivered", passed=False)

    got = [(await execute_all([row(c)], rig=object(), concurrency=4))[0] for c in (unmet, boom, red)]
    assert [o.state for o in got] == ["skipped", "errored", "failed"]
    assert got[0].skip_code and "precondition unmet" in got[0].skip_reason


def test_classify_send_reads_the_rails_own_sentences():
    parked = (f"FX route did not settle (route_id={_RID}) and the gateway did not report a refund; the ingress is "
              f"parked at the gateway: FX route: egress delegation to sandbox-beta failed post-conversion; "
              f"1.983240000000000000 SBXB parked at did:theprotocol:fx-router-sbxb (route_id={_RID})")
    p = classify_send(409, {"detail": parked})
    assert (p["kind"], p["parked_amount"], p["parked_currency"], p["parked_at"], p["route_id"]) == (
        "parked", "1.983240000000000000", "SBXB", "did:theprotocol:fx-router-sbxb", _RID)
    refunded = (f"FX route did not settle (route_id={_RID}); the gateway compensates pre-conversion / "
                f"dead-letters post-conversion.")
    assert classify_send(409, {"detail": refunded})["kind"] == "refunded"
    stranded = (f"FX route did not settle (route_id={_RID}) and the gateway did not report a refund; the ingress is "
                f"parked at the gateway: gateway unreachable")
    assert classify_send(409, {"detail": stranded})["kind"] == "stranded", "the origin's own 'parked at the gateway' is not a parking"
    d = classify_send(200, {"transfer_id": _RID, "credited_amount": "1.98324", "status": "completed"})
    assert (d["kind"], d["credited"], d["route_id"]) == ("delivered", "1.98324", _RID)
    assert classify_send(402, {"detail": "FX route ingress failed (no funds moved): insufficient balance"})["kind"] == "no_funds"
    assert classify_send(409, {"detail": "FX route ingress failed (no funds moved): refused"})["kind"] == "no_funds"
    assert classify_send(409, {"detail": "the FX swap booth, which is disabled (FX_ENABLED=false)"})["kind"] == "no_booth"
    assert classify_send(400, {"detail": "Cannot resolve registry for receiver did:x"})["kind"] == "unresolved"
    assert classify_send(403, {"detail": "forbidden"})["kind"] == "refused"


def test_the_sentences_the_classifier_keys_on_still_exist_in_the_rail():
    src = (_PKG / "routers" / "teg_integration.py").read_text(encoding="utf-8")
    for frag in ("failed post-conversion; ", " parked at {gd_router} (route_id={route_id})",
                 "compensates pre-conversion", 'FX route did not settle (route_id={route_id})',
                 "FX route ingress failed (no funds moved)", "FX swap booth", "Cannot resolve registry for receiver"):
        assert frag in src, f"the rail no longer says {frag!r}: classify_send reads a sentence that is gone"


def test_both_cross_frame_operator_rows_send_early():
    by_name = {s.name: s for s in dec.REGISTRY}
    for name, fn in (("cross_cloud_op_transfer_alpha_to_delta", xf.test_cross_cloud_op_transfer_alpha_to_delta),
                     ("cross_cloud_op_transfer_delta_to_alpha", xf.test_cross_cloud_op_transfer_delta_to_alpha)):
        spec = by_name[name]
        assert spec.start_first and "send-early" in spec.tags, name
        assert "_send_early(" in inspect.getsource(fn), name
