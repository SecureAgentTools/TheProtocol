"""§MCPTEST30 (V0641): purchasePipelineTemplate earns its row on a free template the target lists, bought by a throwaway's
own agent; its refusal reaches the template.

The tool passed on a refusal alone on every node: bundle_download_safe's probe sent a made-up buyer, so what it measured
was the buyer lookup (404 "Agent did:theprotocol:phase6-no-such not found", agentvault2-aa's frame pair nt261025x1a, and
V0639's operator read). purchase_template charges for real since 2026-07-24, a free template (price 0) with no TEG call:
only the purchase row. Pinned: the CI/CD lifecycle buys the free template it already downloads, never a priced one,
for the throwaway's own agent; an answer that moved something, or carries no config, is red; with no free template both
rows say so; the safe-path probe is a refusal row with the sentinel as buyer and a template that does not exist.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F
from agentvault_registry.api_tests.contracts import earned_ad_devtools as D
from agentvault_registry.api_tests.contracts import mcp_lifecycles as L

_BUY = "theprotocol_purchasePipelineTemplate"
_FREE = {"id": "t-free", "name": "Free starter", "price_teg": "0", "author_did": None}          # official
_AUTHORED = {"id": "t-dev", "name": "Free by a developer", "price_teg": "0", "author_did": "did:theprotocol:dev"}
_PAID = {"id": "t-paid", "name": "Paid pro", "price_teg": "5", "author_did": None}
_NAMES = {t["id"]: t["name"] for t in (_FREE, _AUTHORED, _PAID)}


def _answer(payload):
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(payload)}]}}


def _error(text):
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "Error: " + text}],
                                                    "isError": True}}


def _cicd(templates=(_PAID, _AUTHORED, _FREE), bought=None):
    calls, dep = [], {"id": "dep1", "environment": "staging", "logs": "", "status": "success", "error_message": None}
    bought = bought or {"message": "Template purchased successfully", "template_config": {"stages": []},
                        "transaction_id": None}

    async def rpc(tool, args, jwt="", timeout=20):
        calls.append((tool, dict(args), jwt))
        if tool == "theprotocol_createVersion":
            return True, _answer({"version_id": "v" + args["version"][-1]}), "201"
        if tool == "theprotocol_activateVersion":
            return True, _answer({"ok": True}), "200"
        if tool == "theprotocol_deleteVersion":       # versions v0 and v1 (1.0.0, 1.0.1), v1 made current
            if args["version_id"] == "v0":
                return True, _answer({"deleted": True}), "200"
            return False, _error("HTTP 409: Cannot delete the current version"), "409"
        if tool == "theprotocol_getMyCicdVersions":
            return True, _answer({"versions": [{"id": "v1"}]}), "200"
        if tool == "theprotocol_triggerDeployment":
            return True, _answer({"deployment_id": "dep1"}), "201"
        if tool == "theprotocol_getDeployment":
            return True, _answer(dict(dep)), "200"
        if tool == "theprotocol_appendDeploymentLogs":
            dep["logs"] += args["logs"]
            return True, _answer({"ok": True}), "200"
        if tool == "theprotocol_updateDeploymentStatus":
            dep.update(status=args["status"], error_message=args["error_message"])
            return True, _answer({"ok": True}), "200"
        if tool == "theprotocol_getPipelineTemplates":
            return True, _answer({"templates": list(templates)}), "200"
        if tool == _BUY:
            return True, _answer(bought), "200"
        if tool == "theprotocol_downloadPipelineTemplate":
            return True, _answer({"name": _NAMES[args["template_id"]]}), "200"
        raise AssertionError(tool)

    outcomes = {}
    asyncio.run(D._cicd(rpc, F._parse_rpc_result, SimpleNamespace(flow_values={}), outcomes,
                        {"access_token": "throwaway-jwt"}, {"did": "did:theprotocol:cicd-agent"}))
    return outcomes, calls


def test_a_free_official_template_is_bought_by_the_throwaways_own_agent_never_an_authored_or_priced_one():
    outcomes, calls = _cicd()
    buys = [(a, j) for t, a, j in calls if t == _BUY]
    assert buys == [({"template_id": "t-free", "buyer_did": "did:theprotocol:cicd-agent"}, "throwaway-jwt")]
    row = outcomes[_BUY]
    assert row["healthy"] is True and row["status_code"] == 200 and not row.get("skip_reason"), row
    assert outcomes["theprotocol_downloadPipelineTemplate"]["healthy"] is True


def test_a_purchase_that_moved_something_or_carries_no_config_is_red():
    for bought in ({"message": "Template purchased successfully", "template_config": {}, "transaction_id": "tx-1"},
                   {"message": "Template purchased successfully"}):
        outcomes, _ = _cicd(bought=bought)
        assert outcomes[_BUY]["healthy"] is False, bought


def test_with_no_free_template_both_rows_say_so_and_nothing_is_bought():
    outcomes, calls = _cicd(templates=(_PAID,))
    assert not [c for c in calls if c[0] == _BUY]
    for tool in (_BUY, "theprotocol_downloadPipelineTemplate"):
        assert str(outcomes[tool]["skip_reason"]).startswith("NOT MEASURED") and "no free" in outcomes[tool][
            "skip_reason"], tool
    assert _BUY in D.CICD


def test_the_safe_path_probe_is_a_refusal_row_with_the_sentinel_as_buyer():
    calls = []

    async def rpc(tool, args, jwt="", timeout=20):
        calls.append((tool, dict(args)))
        if tool == _BUY:
            return False, _error("HTTP 404: Template not found"), "404"
        return False, _error("HTTP 404: not found"), "404"

    outcomes = {}
    bag = SimpleNamespace(developer_jwt="d", sentinel_did="did:theprotocol:sentinel", sentinel_jwt="s",
                          flow_values={})
    asyncio.run(L.lifecycle_bundle_download_safe(rpc, F._parse_rpc_result, bag, outcomes))
    assert _BUY not in outcomes
    assert outcomes["refusal: purchasePipelineTemplate a template that does not exist"]["healthy"] is True
    sent = next(a for t, a in calls if t == _BUY)
    assert sent == {"template_id": "00000000-0000-4000-8000-000000000000", "buyer_did": "did:theprotocol:sentinel"}


def test_with_only_an_authored_free_template_the_purchase_says_so_and_the_download_still_runs():
    """agentvault2-aa's condition: a purchase counts a download on its template, so only an official one (no author)."""
    outcomes, calls = _cicd(templates=(_PAID, _AUTHORED))
    assert not [c for c in calls if c[0] == _BUY]
    assert "no free official" in outcomes[_BUY]["skip_reason"]
    assert outcomes["theprotocol_downloadPipelineTemplate"]["healthy"] is True
    assert [a for t, a, _ in calls if t == "theprotocol_downloadPipelineTemplate"] == [{"template_id": "t-dev"}]
