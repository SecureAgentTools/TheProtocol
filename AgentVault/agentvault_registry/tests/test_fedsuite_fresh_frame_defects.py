"""§NIGHTPROV (2026-09-27): three federation-suite checks that failed on the first nightly pair (nt260927x2a), a frame
two hours old, while the standing sandbox passed them on old rows or on its age. Each is a tester defect:

- operator_application_submit_and_inventory posted no `accept_operator_terms`, which the route has required since
  §LEGALKIT: 422 on any frame without an application row older than that rule (sbx-alpha has one).
- public_showcase_call_endpoint called getPublicShowcaseCall with no arguments; since §MCPSWEEP V0464 the tool takes
  {service, input}, so the dispatcher refused it (-32602) before the route ran.
- reactor_lifetime_dispatches_growing asserted >= 10000 lifetime dispatches, a population only a weeks-old tier holds;
  the young frame held 211, 0 errors.

The rig is faked below the predicate: its poll loop runs the predicate until it passes or the attempts run out, with
no sleeping, so each case exercises the check as the suite runs it. Each fix keeps a control for the defect it closes.
"""
from __future__ import annotations

import ast
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from agentvault_registry import schemas
from agentvault_registry.api_tests.federation_suite.rig import AssertionResult, MCPError, PreconditionUnmet
from agentvault_registry.api_tests.federation_suite.tests import test_public_showcase as showcase
from agentvault_registry.api_tests.federation_suite.tests import test_reactor_inventory_drill as reactors

TESTS = pathlib.Path(showcase.__file__).parent


class _Rig:
    """answers[label][tool] is a value, an exception to raise, or a list consumed one per call (the last repeats)."""

    def __init__(self, answers, attempts=3):
        self.answers, self.attempts, self.calls = answers, attempts, []

    def mcp(self, label):
        rig = self

        class _C:
            async def call(self, tool, arguments=None, **_k):
                rig.calls.append((label, tool, arguments))
                a = rig.answers[label][tool]
                if isinstance(a, list):
                    a = a.pop(0) if len(a) > 1 else a[0]
                if isinstance(a, Exception):
                    raise a
                return a
        return _C()

    async def assert_within(self, *, budget_sec, predicate, description, capture_state=None, **_k):
        ok, n = False, 0
        while not ok and n < self.attempts:
            n += 1
            ok = bool(await predicate())
        return AssertionResult(passed=ok, description=description, budget_sec=budget_sec, elapsed_sec=0.0,
                               polling_attempts=n, last_state=capture_state() if capture_state else None)


def _ago(**kw):
    return (datetime.now(timezone.utc) - timedelta(**kw)).isoformat()


# ── operator application: the terms are accepted wherever the tester submits one ──────────────────────────────────

def _dict_literals_with(path, key):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [n for n in ast.walk(tree) if isinstance(n, ast.Dict)
            and any(isinstance(k, ast.Constant) and k.value == key for k in n.keys)]


@pytest.mark.parametrize("path, marker", [
    (TESTS / "test_operator_provisioning_flow.py", "federation_test_suite operator provisioning probe"),
    (TESTS.parents[1] / "request_bodies.py", "Synthetic application created by automated API tester for coverage."),
])
def test_every_tester_application_body_accepts_the_operator_terms(path, marker):
    bodies = [d for d in _dict_literals_with(path, "use_case")
              if any(isinstance(v, ast.Constant) and v.value == marker for v in d.values)]
    assert len(bodies) == 1, (path.name, len(bodies))
    # a value the literal does not carry (a module constant such as CANDIDATE_NAME) stands in as a plain string
    body = {k.value: (v.value if isinstance(v, ast.Constant) else "stand-in")
            for k, v in zip(bodies[0].keys, bodies[0].values) if isinstance(k, ast.Constant)}
    assert body.get("accept_operator_terms") is True, path.name
    assert schemas.OperatorApplicationCreate(**body).accept_operator_terms is True  # the route's own schema takes it


def test_control_the_old_body_is_the_one_the_route_refuses():
    """The route refuses an application whose terms are not accepted (operator_applications.py: 422)."""
    old = {"name": "n", "email": "e@x", "deployment": "sandbox", "experience": "advanced", "use_case": "u"}
    assert schemas.OperatorApplicationCreate(**old).accept_operator_terms is False
    route = (TESTS.parents[2] / "routers" / "operator_applications.py").read_text(encoding="utf-8")
    assert 'if not getattr(application, "accept_operator_terms", False):' in route


# ── public showcase call: the tool is called with its declared arguments and judged by the route's words ──────────

def _showcase_rig(tool_answer, route_status, route_body):
    return _Rig({
        "sandbox-A": {"getPublicShowcaseCall": tool_answer},
        "sandbox-A-admin": {"adminRequest": {"status_code": route_status, "response": route_body, "ok": False}},
    })


async def test_the_showcase_probe_names_an_unknown_service_and_passes_on_the_routes_refusal():
    rig = _showcase_rig({"_text": "Error: getPublicShowcaseCall returned HTTP 400"}, 400,
                        {"error": "Unknown service: fedsuite-no-such-service", "available": ["weather", "currency"]})
    r = await showcase.test_showcase_call_endpoint(rig)
    assert r.passed is True and r.last_state["answer"] == "the route refused an unknown service"
    tool_calls = [c for c in rig.calls if c[1] == "getPublicShowcaseCall"]
    assert tool_calls == [("sandbox-A", "getPublicShowcaseCall", {"service": "fedsuite-no-such-service", "input": ""})]
    assert len(rig.calls) == 2, "one probe answers it: the caller's hourly budget is not spent on retries"


async def test_a_disabled_showcase_is_reachable_and_passes():
    rig = _showcase_rig({"_text": "Error: getPublicShowcaseCall returned HTTP 503"}, 503,
                        {"error": "The showcase is disabled on this deployment.", "enabled": False})
    r = await showcase.test_showcase_call_endpoint(rig)
    assert r.passed is True and r.last_state["answer"] == "the showcase is disabled on this frame"


async def test_control_a_call_the_dispatcher_refuses_fails():
    """The defect this closes: no arguments, -32602 from the dispatcher, the route never ran."""
    err = MCPError("sandbox-A", "theprotocol_getPublicShowcaseCall", "400",
                   '{"code":-32602,"message":"Invalid params: get_public_showcase_call() missing 2 required '
                   "positional arguments: 'service' and 'input'\"}")
    rig = _showcase_rig(err, 400, {"error": "Unknown service: fedsuite-no-such-service", "available": []})
    r = await showcase.test_showcase_call_endpoint(rig)
    assert r.passed is False and "-32602" in r.last_state["error"]


@pytest.mark.parametrize("status, body", [
    (400, {"error": "Invalid JSON"}),                     # the route's other 400: the body did not arrive as sent
    (500, {"detail": "Internal Server Error"}),
    (404, {"detail": "Not Found"}),                       # the route is gone
])
async def test_control_any_other_answer_fails(status, body):
    rig = _showcase_rig({"_text": f"Error: getPublicShowcaseCall returned HTTP {status}"}, status, body)
    r = await showcase.test_showcase_call_endpoint(rig)
    assert r.passed is False and r.last_state["answer"] is None


async def test_control_the_tool_and_the_route_must_agree():
    rig = _showcase_rig({"_text": "Error: getPublicShowcaseCall returned HTTP 502"}, 400,
                        {"error": "Unknown service: fedsuite-no-such-service", "available": []})
    assert (await showcase.test_showcase_call_endpoint(rig)).passed is False


# ── reactor dispatches: a population floor for an old tier, growth for a young one ─────────────────────────────────

def _reactor_rig(dispatches, oldest_event, errors=0):
    status = [{"summary": {"lifetime_dispatches": d, "lifetime_errors": errors}} for d in dispatches]
    return _Rig({"sandbox-A-admin": {"getReactorStatus": status,
                                     "getEventStoreStats": {"total_events": 38, "oldest_event": oldest_event}}})


async def test_a_long_running_tier_above_the_floor_passes():
    r = await reactors.test_reactor_dispatches(_reactor_rig([12000], _ago(days=30)))
    assert r.passed is True


async def test_a_young_frame_whose_dispatches_grow_passes():
    r = await reactors.test_reactor_dispatches(_reactor_rig([211, 211, 215], _ago(hours=2)))
    assert r.passed is True and r.last_state["grew_by"] == 4 and "verdict" not in r.last_state


async def test_a_young_quiet_frame_is_not_measured():
    """The measured case: nt260927x2a, 211 dispatches, 0 errors, a ledger two hours old."""
    with pytest.raises(PreconditionUnmet) as exc:
        await reactors.test_reactor_dispatches(_reactor_rig([211], _ago(hours=2)))
    assert str(exc.value).startswith("NOT MEASURED") and "211" in str(exc.value)


async def test_control_an_old_quiet_tier_under_the_floor_still_fails():
    r = await reactors.test_reactor_dispatches(_reactor_rig([211], _ago(days=30)))
    assert r.passed is False and "verdict" not in r.last_state


async def test_control_an_unreadable_status_is_never_a_skip():
    rig = _Rig({"sandbox-A-admin": {"getReactorStatus": RuntimeError("status unreadable"),
                                    "getEventStoreStats": {"oldest_event": _ago(hours=2)}}})
    r = await reactors.test_reactor_dispatches(rig)
    assert r.passed is False and "status unreadable" in r.last_state["error"]
