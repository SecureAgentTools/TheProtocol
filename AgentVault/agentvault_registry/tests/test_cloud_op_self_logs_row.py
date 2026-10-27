"""§MCPTEST30 (V0549): the cloud-op self-logs row reads the operator's real path and cannot pass on a refusal.

Until V0549 the row called getCloudOperatorSelfLogs on each operator's admin bridge (no MCP caller can succeed with it:
503 "mainframe only" on an operator, 401 on a frame) and accepted the error as a pass. It now calls
operatorPortalSelfLogs on each operator, which forwards to the parent frame with the operator's licence, and passes only
on log lines read under that licence. It keeps counts, never a line.
"""
from __future__ import annotations

import asyncio

from agentvault_registry.api_tests.federation_suite import rig as rig_mod
from agentvault_registry.api_tests.federation_suite.tests import test_cloud_op_self_logs as row

LOGS = {"operator_name": "sbxalphaop", "auth_mode": "federation_license", "service": "registry", "tail": 10,
        "output": "cloud-op-sbxalphaop-registry | line one\ncloud-op-sbxalphaop-registry | line two\n"}
REFUSED = {"_text": "Error: HTTP 503: Operator self-logs is for cloud-ops only."}


class _Client:
    def __init__(self, answer, seen):
        self.answer, self.seen = answer, seen

    async def call(self, tool, args=None):
        self.seen.append((tool, dict(args or {})))
        # V0550: a label may answer per tool (a parent frame answers its card and its operator tools differently)
        return self.answer.get(tool, self.answer) if isinstance(self.answer, dict) and tool in self.answer else self.answer


class _Rig(rig_mod.FederationTestRig):
    """The real rig with its bridges replaced, and a poll that asks once (the budget is the real rig's concern)."""

    def __init__(self, answers):
        super().__init__()
        self.answers, self.seen = answers, []

    def mcp(self, label):
        return _Client(self.answers[label], self.seen)

    async def assert_within(self, *, budget_sec, predicate, description, poll_interval_sec=1.0, capture_state=None):
        ok = await predicate()
        return rig_mod.AssertionResult(passed=bool(ok), description=description, budget_sec=budget_sec,
                                       elapsed_sec=0.0, polling_attempts=1,
                                       last_state=capture_state() if capture_state else None)


def _run(answers):
    rig = _Rig(answers)
    return asyncio.run(row.test_cloud_op_self_logs.__wrapped__(rig)
                       if hasattr(row.test_cloud_op_self_logs, "__wrapped__")
                       else row.test_cloud_op_self_logs(rig)), rig


def test_lines_read_under_the_licence_on_both_operators_pass():
    res, rig = _run({"sandboxalpha": LOGS, "sandboxdelta": dict(LOGS, operator_name="sbxbetaop")})
    assert res.passed, res.last_state
    assert {t for t, _ in rig.seen} == {"theprotocol_operatorPortalSelfLogs"} or \
        {t for t, _ in rig.seen} == {"operatorPortalSelfLogs"}
    assert all(a == {"lines": 10} for _, a in rig.seen)
    assert res.last_state["sandboxalpha"] == {"operator_name": "sbxalphaop", "auth_mode": "federation_license",
                                              "lines": 2}
    assert "line one" not in repr(res.last_state), "the row keeps counts, never a log line"


def test_a_refusal_on_one_operator_fails_the_row():
    res, _ = _run({"sandboxalpha": LOGS, "sandboxdelta": REFUSED})
    assert not res.passed
    assert res.last_state["sandboxdelta"] == {"refused": REFUSED["_text"]}


def test_an_answer_not_read_under_the_licence_or_without_lines_fails():
    res, _ = _run({"sandboxalpha": dict(LOGS, auth_mode="admin_jwt"), "sandboxdelta": LOGS})
    assert not res.passed
    res, _ = _run({"sandboxalpha": dict(LOGS, output=""), "sandboxdelta": LOGS})
    assert not res.passed


# §MCPTEST30 (V0550): the operator self-view rows ask the PARENT as the operator's applicant
def _card(name):
    return {"identity": {"registry_name": name}}


def _run_row(fn, answers):
    rig = _Rig(answers)
    return asyncio.run(fn(rig)), rig


def test_the_applicant_reads_its_operators_status_on_the_parent():
    ok = {"sandboxalpha": {"getRegistryCard": _card("sbxalphaop")}, "sandboxdelta": {"getRegistryCard": _card("sbxbetaop")},
          "sandbox-A": {"getOperatorMyStatus": {"application": {"name": "sbxalphaop", "status": "approved"}}},
          "sandbox-B": {"getOperatorMyStatus": {"application": {"name": "sbxbetaop", "status": "approved"}}}}
    res, rig = _run_row(row.test_operator_portal_self_status, ok)
    assert res.passed, res.last_state
    assert ("getOperatorMyStatus", {}) in rig.seen
    # the operator asked itself (what the row used to do) answers 503: a parent that answers so fails the row
    bad = dict(ok, **{"sandbox-B": {"getOperatorMyStatus": {"_text": "Error: HTTP 503: This feature runs on sovereign mainframes only."}}})
    res, _ = _run_row(row.test_operator_portal_self_status, bad)
    assert not res.passed and res.last_state["sandbox-B"]["refused"].startswith("Error: HTTP 503")
    # another operator's application is not this operator's
    wrong = dict(ok, **{"sandbox-A": {"getOperatorMyStatus": {"application": {"name": "RBAC Operator Candidate", "status": "approved"}}}})
    assert not _run_row(row.test_operator_portal_self_status, wrong)[0].passed


def test_the_applicant_reads_its_operators_lifecycle_on_the_parent():
    life = lambda n: {"application": {"name": n, "status": "approved"}, "federation_license": {"status": "active"},
                      "peer_registry": {"status": "ACTIVE"}, "cloud": {}, "drift_flags": []}
    ok = {"sandboxalpha": {"getRegistryCard": _card("sbxalphaop")}, "sandboxdelta": {"getRegistryCard": _card("sbxbetaop")},
          "sandbox-A": {"getOperatorMyLifecycle": life("sbxalphaop")}, "sandbox-B": {"getOperatorMyLifecycle": life("sbxbetaop")}}
    res, _ = _run_row(row.test_operator_my_lifecycle, ok)
    assert res.passed, res.last_state
    no_licence = dict(ok, **{"sandbox-A": {"getOperatorMyLifecycle": dict(life("sbxalphaop"), federation_license=None)}})
    assert not _run_row(row.test_operator_my_lifecycle, no_licence)[0].passed
