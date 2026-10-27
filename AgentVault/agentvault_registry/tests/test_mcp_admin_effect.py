"""§MCPTEST30 (V0553): a public lifecycle's admin steps go through the admin bridge, as the `admin_effect` family.

Five public lifecycles held admin steps (a webhook disabled, enabled and tested; a bundle hidden and shown; a support
ticket answered, reopened and closed; two funding requests approved and rejected; the EigenTrust epoch) and sent them
through the PUBLIC bridge, whose dispatcher refuses an admin tool before it runs. None was ever done: sbx-alpha held 310
pending funding requests and 155 open support tickets of the tester's (measured 2026-10-02). Pinned here: the steps reach
the admin bridge and never the public one, their success on the run's own object is the family's row (the tools' own
rows stay their contracts' refusal pins), a read afterwards that contradicts the step is a BUG-FIND on that row, a flow
without the bridge files nothing it could not clear away, and the admin sweep's probe of an id that names nothing never
replaces a row measured on a real object.
"""
from __future__ import annotations

import asyncio
import types

import pytest

from agentvault_registry.api_tests.contracts import mcp_admin_lifecycles as A
from agentvault_registry.api_tests.contracts import mcp_lifecycles as L


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def _rpc(answers, seen, bridge):
    async def rpc(tool, args, jwt="", timeout=15):
        seen.append((bridge, tool, dict(args)))
        ans = answers.get(tool, (404, f"Error: HTTP 404: no answer scripted for {tool}"))
        if callable(ans):
            ans = ans(args)
        code, payload = ans
        if 200 <= int(code) < 300:
            return True, {"result": payload}, str(code)
        return False, {"result": {"_text": payload} if isinstance(payload, str) else payload}, str(code)
    return rpc


def _parse(body):
    return (body or {}).get("result") or {}


def _run(lifecycle, answers, *, bridge=True, rows=None):
    seen, outcomes = [], {}
    bag = types.SimpleNamespace(developer_jwt="dev", sentinel_jwt="sentinel", sentinel_did="did:x", flow_values={},
                                event_verifier=None)
    if bridge:
        bag.rpc_admin = _rpc(answers, seen, "admin")
        bag.admin_lifecycle_rows = {} if rows is None else rows
    asyncio.run(lifecycle(_rpc(answers, seen, "public"), _parse, bag, outcomes))
    return seen, outcomes, bag


def _webhook_answers(state):
    def admin_set(active):
        def f(args):
            state["is_active"] = active
            return 200, {"id": args["webhook_id"], "is_active": active, "changed": True}
        return f
    return {
        "theprotocol_createWebhook": (201, {"id": "wh-1"}),
        "theprotocol_getWebhook": lambda a: (200, {"id": "wh-1", "is_active": state["is_active"],
                                                    "events": ["agent.created", "agent.updated", "agent.deleted"]}),
        "theprotocol_updateWebhook": (200, {"id": "wh-1"}),
        "theprotocol_testWebhook": (200, {"success": False, "delivery_id": 5}),
        "theprotocol_testDeveloperWebhookAlt": (200, {"success": False}),
        "theprotocol_getWebhookDeliveries": (200, {"deliveries": []}),
        "theprotocol_disableWebhookAdmin": admin_set(False),
        "theprotocol_enableWebhookAdmin": admin_set(True),
        "theprotocol_testWebhookAdmin": (200, {"success": False, "status_code": None, "delivery_id": 6,
                                               "developer_id": 1}),
        "theprotocol_deleteWebhook": (200, {"deleted": True}),
        "theprotocol_getMyWebhooks": (200, {"webhooks": []}),
    }


ADMIN_STEPS = {"theprotocol_disableWebhookAdmin", "theprotocol_enableWebhookAdmin", "theprotocol_testWebhookAdmin",
               "theprotocol_hideBundle", "theprotocol_unhideBundle", "theprotocol_supportReplyTicket",
               "theprotocol_updateSupportTicketStatus", "theprotocol_supportCloseTicket", "theprotocol_approveFunding",
               "theprotocol_rejectFunding", "theprotocol_triggerEigentrustComputation"}


def test_the_webhook_admin_steps_reach_the_admin_bridge_and_are_the_familys_rows():
    seen, outcomes, bag = _run(L.lifecycle_webhook_full_crud, _webhook_answers({"is_active": True}))
    admin = [t for b, t, _ in seen if b == "admin"]
    assert admin == ["theprotocol_disableWebhookAdmin", "theprotocol_enableWebhookAdmin", "theprotocol_testWebhookAdmin"]
    assert not [t for b, t, _ in seen if b == "public" and t in ADMIN_STEPS], "an admin tool went to the public bridge"
    for t in admin:
        row = outcomes[L.admin_effect_row(t)]
        assert row["healthy"] and row["contract_tier"] == "admin_effect" and not row["skip_reason"], (t, row)
        assert t not in outcomes and t not in bag.admin_lifecycle_rows, "the tool's own row stays its contract's"


def test_a_read_afterwards_that_contradicts_the_step_is_a_bug_find_on_the_familys_row():
    answers = _webhook_answers({"is_active": True})
    answers["theprotocol_disableWebhookAdmin"] = (200, {"id": "wh-1", "is_active": False, "changed": True})  # says so
    seen, outcomes, _ = _run(L.lifecycle_webhook_full_crud, answers)                                       # but no change
    row = outcomes[L.admin_effect_row("theprotocol_disableWebhookAdmin")]
    assert not row["healthy"] and "BUG-FIND" in row["fail_reason"] and "is_active=true" in row["fail_reason"]
    assert outcomes[L.admin_effect_row("theprotocol_enableWebhookAdmin")]["healthy"]


def test_an_answer_that_does_not_say_what_the_step_did_is_a_bug_find():
    answers = _webhook_answers({"is_active": True})
    answers["theprotocol_testWebhookAdmin"] = (200, {"success": False})
    _, outcomes, _ = _run(L.lifecycle_webhook_full_crud, answers)
    row = outcomes[L.admin_effect_row("theprotocol_testWebhookAdmin")]
    assert not row["healthy"] and "names no delivery" in row["fail_reason"]


def test_a_refused_admin_step_fails_its_row_and_its_read_back_is_not_asked():
    answers = _webhook_answers({"is_active": True})
    answers["theprotocol_disableWebhookAdmin"] = (403, "Error: HTTP 403: admin_platform required")
    seen, outcomes, _ = _run(L.lifecycle_webhook_full_crud, answers)
    row = outcomes[L.admin_effect_row("theprotocol_disableWebhookAdmin")]
    assert not row["healthy"] and row["status_code"] == 403
    i = [t for _, t, _ in seen].index("theprotocol_disableWebhookAdmin")
    assert seen[i + 1][1] == "theprotocol_enableWebhookAdmin", "a read-back followed a refused step"


def test_without_the_admin_bridge_no_admin_step_runs_anywhere():
    seen, outcomes, _ = _run(L.lifecycle_webhook_full_crud, _webhook_answers({"is_active": True}), bridge=False)
    assert not [t for _, t, _ in seen if t in ADMIN_STEPS]
    assert not [k for k in outcomes if k.startswith("admin_effect: ")]


def _bundle_answers():
    return {
        "theprotocol_createBundle": (201, {"id": "b-1", "name": "phase4-bundle"}),
        "theprotocol_hideBundle": (200, {"ok": True, "hidden": True, "name": "phase4-bundle"}),
        "theprotocol_unhideBundle": (200, {"ok": True, "unhidden": True, "name": "phase4-bundle"}),
    }


def test_hide_bundle_sends_the_reason_its_tool_requires():
    answers = _bundle_answers()
    seen = []
    bag = types.SimpleNamespace(rpc_admin=_rpc(answers, seen, "admin"))
    out = {}
    ok, _ = asyncio.run(L._admin_effect(bag.rpc_admin, _parse, "theprotocol_hideBundle",
                                        {"bundle_id": "b-1", "reason": "r"}, "dev", out, check=L._says("hidden")))
    assert ok and out[L.admin_effect_row("theprotocol_hideBundle")]["healthy"]
    ok, _ = asyncio.run(L._admin_effect(bag.rpc_admin, _parse, "theprotocol_unhideBundle", {"bundle_id": "b-1"},
                                        "dev", out, check=L._says("hidden")))
    assert not ok and "says none of ['hidden']" in out[L.admin_effect_row("theprotocol_unhideBundle")]["fail_reason"]
    # the lifecycle's own call carries the reason (the gate test_mcp_lifecycle_probe_args holds every step to its schema)
    import inspect
    src = inspect.getsource(L.lifecycle_bundle_full_crud)
    assert '"theprotocol_hideBundle",' in src and '"reason": "MCP tester: its own bundle' in src


def _funding_answers(state):
    def submit(args):
        state["n"] += 1
        return 201, {"id": 100 + state["n"], "status": "pending"}

    def approve(args):
        state[args["request_id"]] = "funded"
        return 200, {"id": args["request_id"], "status": "funded"}

    def reject(args):
        state[args["request_id"]] = "rejected"
        return 200, {"id": args["request_id"], "status": "rejected"}
    return {
        "theprotocol_submitFundingRequest": submit,
        "theprotocol_approveFunding": approve,
        "theprotocol_rejectFunding": reject,
        "theprotocol_getMyFundingRequests": lambda a: (200, {"requests": [
            {"id": k, "status": v} for k, v in state.items() if isinstance(k, int)]}),
    }


def test_both_funding_requests_are_resolved_through_the_admin_bridge():
    state = {"n": 0}
    seen, outcomes, _ = _run(L.lifecycle_funding_approve_reject, _funding_answers(state))
    assert [(t, a.get("request_id")) for b, t, a in seen if b == "admin"] == [
        ("theprotocol_approveFunding", 101), ("theprotocol_rejectFunding", 102)]
    assert state[101] == "funded" and state[102] == "rejected", "a request was left pending"
    assert outcomes[L.admin_effect_row("theprotocol_approveFunding")]["healthy"]
    assert outcomes[L.admin_effect_row("theprotocol_rejectFunding")]["healthy"]
    # the reject path's submit is a prerequisite: the tool's row is the approve path's, held to success
    assert outcomes["theprotocol_submitFundingRequest"]["probe_expect_status"] == "success"


def test_a_request_the_read_shows_still_pending_is_a_bug_find():
    state = {"n": 0}
    answers = _funding_answers(state)
    answers["theprotocol_approveFunding"] = lambda a: (200, {"id": a["request_id"], "status": "funded"})  # no change
    state[101] = "pending"
    _, outcomes, _ = _run(L.lifecycle_funding_approve_reject, answers)
    row = outcomes[L.admin_effect_row("theprotocol_approveFunding")]
    assert not row["healthy"] and "status='pending'" in row["fail_reason"]


def test_without_the_admin_bridge_no_funding_request_is_filed():
    seen, outcomes, _ = _run(L.lifecycle_funding_approve_reject, _funding_answers({"n": 0}), bridge=False)
    assert seen == [] and outcomes == {}


def _ticket_answers(state):
    def reply(args):
        state["messages"].append(args["message"])
        return 200, {"id": 9, "status": state["status"]}

    def set_status(args):
        state["status"] = args["status"]
        return 200, {"id": 9, "status": args["status"]}

    def close(args):
        state["messages"].append(args.get("message") or "")
        state["status"] = args["status"]
        return 200, {"id": 9, "status": args["status"]}
    return {
        "theprotocol_submitSupportTicket": (201, {"id": 9, "status": "open"}),
        "theprotocol_replySupportTicket": reply,
        "theprotocol_supportReplyTicket": reply,
        "theprotocol_updateSupportTicketStatus": set_status,
        "theprotocol_supportCloseTicket": close,
        "theprotocol_getSupportTicketDetail": lambda a: (200, {"id": 9, "status": state["status"], "messages": [
            {"message": m} for m in state["messages"]]}),
    }


def test_the_ticket_is_answered_and_closed_through_the_admin_bridge():
    state = {"status": "open", "messages": []}
    seen, outcomes, _ = _run(L.lifecycle_support_ticket, _ticket_answers(state))
    assert [t for b, t, _ in seen if b == "admin"] == [
        "theprotocol_supportReplyTicket", "theprotocol_updateSupportTicketStatus", "theprotocol_supportCloseTicket"]
    assert state["status"] == "resolved", "the run's ticket was left open"
    for t in ("theprotocol_supportReplyTicket", "theprotocol_updateSupportTicketStatus", "theprotocol_supportCloseTicket"):
        assert outcomes[L.admin_effect_row(t)]["healthy"], t


def test_a_ticket_the_read_shows_still_open_after_the_close_is_a_bug_find():
    state = {"status": "open", "messages": []}
    answers = _ticket_answers(state)
    answers["theprotocol_supportCloseTicket"] = (200, {"id": 9, "status": "resolved"})   # says so, changes nothing
    _, outcomes, _ = _run(L.lifecycle_support_ticket, answers)
    row = outcomes[L.admin_effect_row("theprotocol_supportCloseTicket")]
    assert not row["healthy"] and "status='open'" in row["fail_reason"]


def test_the_epoch_row_joins_the_admin_sweeps_rows_and_the_probe_list_does_not_start_a_second():
    rows = {}
    seen, calls = [], []
    rpc_admin = _rpc({"theprotocol_triggerEigentrustComputation": (200, {"status": "started", "message": "m"})},
                     seen, "admin")
    asyncio.run(L._exec_step(rpc_admin, _parse, "theprotocol_triggerEigentrustComputation", "admin", {}, "dev", rows))
    assert rows["theprotocol_triggerEigentrustComputation"]["healthy"]

    async def probe_rpc(tool, args, jwt="", timeout=15):
        calls.append(tool)
        return False, {"result": {"_text": f"Error: HTTP 404: {tool}"}}, "404"
    bag = types.SimpleNamespace(developer_jwt="dev", sentinel_jwt="sentinel", sentinel_did="did:theprotocol:x")
    asyncio.run(A.lifecycle_admin_destructive_safe(probe_rpc, _parse, bag, rows))
    assert "theprotocol_triggerEigentrustComputation" not in calls, "the probe list started a second epoch"
    assert rows["theprotocol_triggerEigentrustComputation"]["healthy"], "the probe replaced the real row"
    assert "theprotocol_approveFunding" in calls, "the probes of tools without a real row still run"


def test_a_named_skip_does_not_stop_the_probe():
    rows = {"theprotocol_triggerEigentrustComputation": L._not_measured("theprotocol_triggerEigentrustComputation",
                                                                         "admin", "NOT MEASURED: no bridge")}
    assert not A._measured_for_real(rows, "theprotocol_triggerEigentrustComputation")
    assert not A._measured_for_real({}, "theprotocol_x")
    assert A._measured_for_real({"t": {"healthy": False, "skip_reason": None}}, "t"), "a failed real row stands too"
