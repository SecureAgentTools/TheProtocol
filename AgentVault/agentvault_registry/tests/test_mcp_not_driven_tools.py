"""§MCPTEST30 (V0641): tools whose success no tester run should drive or can reach are NOT MEASURED on their own rows,
their refusal a refusal row held to what a frame and an operator each answer.

finalizeFrameInvitation (federates two frames), approve/reject/getFederationDisputeSettlement (a settlement exists only
for a ruled dispute against another registry's agent; approving slashes it), getRelayStatus and relayAction (need an
agent that runs a relay), federationVetoProposal and federationProposeRaise (federation-wide acts) passed on a refusal
alone: on the frames on probes with made-up input (the veto's 999999 measured the EventStore parsing the probe, 422
uuid_parsing), on the operators on their contracts (lifecycle_misc_safe is no operator lifecycle). Measured: agentvault2-
aa's frame pair nt261025x1a on V0639 and V0639's operator read (2026-10-25). Pinned: the rows, the refusals' inputs
(ids that are well formed and name nothing), both node classes' words, a refusal for another reason red, no pin on the
contracts, the rows through the merge, and misc_safe no longer probing them.
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import json
import textwrap
from types import SimpleNamespace

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F
from agentvault_registry.api_tests.contracts import earned_agent_public as EAP
from agentvault_registry.api_tests.contracts import earned_fixtures as EF
from agentvault_registry.api_tests.contracts import mcp_lifecycles as L
from agentvault_registry.api_tests.contracts.mcp_contracts import get_contract

_NO_ID = "00000000-0000-4000-8000-000000000000"
_FRAME = {  # what aa's frame pair answered (nt261025x1a, V0639), well-formed inputs
    "theprotocol_finalizeFrameInvitation": ("404", "HTTP 404: Invitation not found."),
    "theprotocol_approveDisputeSettlement": ("404", "HTTP 404: Settlement not found"),
    "theprotocol_rejectDisputeSettlement": ("404", "HTTP 404: Settlement not found"),
    "theprotocol_getFederationDisputeSettlement": ("404", f"HTTP 404: Settlement {_NO_ID} not found"),
    "theprotocol_getRelayStatus": ("422", "HTTP 422: Agent endpoint must be https (card declares http)"),
    "theprotocol_relayAction": ("400", "HTTP 400: Invalid relay tool: relay_phase6"),
    "theprotocol_getOperatorMyLifecycle": ("404", "HTTP 404: No operator application found for this developer account."),
}
_OPERATOR_RELAY = ("502", "HTTP 502: The agent's address answered, but not as a relay")


def _answer(payload):
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(payload)}]}}


def _error(text):
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "Error: " + text}],
                                                    "isError": True}}


def _by_design(answers):
    calls = []

    async def rpc(tool, args, jwt="", timeout=20):
        calls.append((tool, dict(args)))
        if tool == "theprotocol_getPublicRegistryConfig":
            return True, _answer({"federation_ballot_mode": True}), "200"
        if tool in answers:
            code, text = answers[tool]
            return False, _error(text), code
        return False, _error("HTTP 401: Federation authentication required"), "401"

    outcomes = {}
    bag = SimpleNamespace(developer_jwt="d", sentinel_jwt="s", sentinel_did="did:theprotocol:sentinel", flow_values={})
    asyncio.run(EAP.lifecycle_earned_by_design(rpc, F._parse_rpc_result, bag, outcomes))
    return outcomes, calls


def _ref(tool, what):
    return f"refusal: {tool[len('theprotocol_'):]} {what}"


def test_each_not_driven_tool_is_said_on_its_row_and_its_refusal_passes_on_a_frames_words():
    outcomes, calls = _by_design(_FRAME)
    whats = {t: w for t, _a, w, _c, _x in EAP.not_driven_refusals(SimpleNamespace(sentinel_did="did:x"))}
    assert set(whats) == {t for t, _, _ in EAP.NOT_DRIVEN} == set(_FRAME)
    for tool in _FRAME:
        row = outcomes[tool]
        assert row["healthy"] is False and str(row["skip_reason"]).startswith("NOT MEASURED"), (tool, row)
        ref = outcomes[_ref(tool, whats[tool])]
        assert ref["healthy"] is True, (tool, ref)
    sent = {t: a for t, a in calls if t in _FRAME}
    for tool in ("theprotocol_finalizeFrameInvitation", "theprotocol_approveDisputeSettlement",
                 "theprotocol_rejectDisputeSettlement", "theprotocol_getFederationDisputeSettlement"):
        assert _NO_ID in json.dumps(sent[tool]), "an id that is well formed and names nothing"
    assert sent["theprotocol_relayAction"]["action_payload"]["tool"] == "relay_phase6"


def test_the_operators_relay_answer_passes_too_and_another_reason_is_red():
    outcomes, _ = _by_design({**_FRAME, "theprotocol_getRelayStatus": _OPERATOR_RELAY})
    assert outcomes[_ref("theprotocol_getRelayStatus", "an agent with no relay")]["healthy"] is True
    other, _ = _by_design({**_FRAME, "theprotocol_approveDisputeSettlement": ("404", "HTTP 404: Agent not found")})
    row = other[_ref("theprotocol_approveDisputeSettlement", "a settlement that does not exist")]
    assert row["healthy"] is False and "settlement not found" in row["fail_reason"]


def _safe_paths(veto, raise_=("404", "HTTP 404: Local proposal not found")):
    calls = []

    async def rpc(tool, args, jwt="", timeout=20):
        calls.append((tool, dict(args)))
        if tool == "theprotocol_federationVetoProposal":
            return False, _error(veto[1]), veto[0]
        if tool == "theprotocol_federationProposeRaise":
            return False, _error(raise_[1]), raise_[0]
        return False, _error("HTTP 401: refused"), "401"

    outcomes = {}
    bag = SimpleNamespace(developer_jwt="d", sentinel_jwt="s", sentinel_did="did:theprotocol:sentinel", flow_values={})
    asyncio.run(L.lifecycle_federation_safe_paths(rpc, F._parse_rpc_result, bag, outcomes))
    return outcomes, calls


_VETO = "refusal: federationVetoProposal a federation proposal that does not exist"
_RAISE = "refusal: federationProposeRaise a local proposal that does not exist"


def test_the_veto_and_the_raise_are_held_back_their_refusals_on_well_formed_ids_on_both_classes():
    frame, calls = _safe_paths(("400", 'HTTP 400: EventStore: {"detail":"Federation proposal not found"}'))
    operator, _ = _safe_paths(("403", "HTTP 403: Only mainframe admin can veto federation proposals"))
    for out in (frame, operator):
        for tool in ("theprotocol_federationVetoProposal", "theprotocol_federationProposeRaise"):
            assert out[tool]["healthy"] is False and str(out[tool]["skip_reason"]).startswith("NOT MEASURED")
        assert out[_VETO]["healthy"] is True and out[_RAISE]["healthy"] is True
    veto_args = next(a for t, a in calls if t == "theprotocol_federationVetoProposal")
    assert veto_args["proposal_id"] == _NO_ID, "a UUID, so the route is reached, never the EventStore's parse"
    parsed, _ = _safe_paths(("422", 'HTTP 422: EventStore: {"detail":[{"type":"uuid_parsing"}]}'))
    assert parsed[_VETO]["healthy"] is False, "the probe's own argument refused is not the rule"


def test_the_contracts_pin_nothing_and_name_why_and_the_rows_survive_the_merge():
    outcomes, _ = _by_design(_FRAME)
    safe, _ = _safe_paths(("400", "HTTP 400: Federation proposal not found"))
    outcomes.update(safe)
    tools = [t for t, _, _ in EAP.NOT_DRIVEN] + ["theprotocol_federationVetoProposal", "theprotocol_federationProposeRaise"]
    for tool in tools:
        c = get_contract(tool)
        assert not c.override_coverage_fan and c.success_path_unmeasured, tool
        d = F._fan_row_verdict(outcomes[tool], tool)
        assert d["healthy"] is False and str(d["skip_reason"]).startswith("NOT MEASURED"), (tool, d)
    kept = dict(F.kept_lifecycle_rows(outcomes, set(tools), set(), lambda n: bool(get_contract(n).override_coverage_fan)))
    assert _VETO in kept and _RAISE in kept
    assert not [k for k in kept if k.startswith("earned: ")]


def test_misc_safe_no_longer_probes_them():
    tree = ast.parse(textwrap.dedent(inspect.getsource(L.lifecycle_misc_safe)))
    named = {n.args[2].value for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_exec_step"
             and len(n.args) > 2 and isinstance(n.args[2], ast.Constant)}
    gone = {t for t, _, _ in EAP.NOT_DRIVEN}
    assert not named & gone, named & gone
    assert "theprotocol_getFederationDisputeSettlements" in named, "the list read stays"


def test_a_refusal_step_takes_alternative_words():
    async def rpc(tool, args, jwt="", timeout=20):
        return False, _error("HTTP 403: Only mainframe admin can veto federation proposals"), "403"
    out = {}
    ok = asyncio.run(EF.refusal_step(rpc, F._parse_rpc_result, "theprotocol_federationVetoProposal", "3", {}, "d", out,
                                     "x", codes=(400, 403), text=("federation proposal not found",
                                                                  "only mainframe admin can veto")))
    assert ok and out["refusal: federationVetoProposal x"]["healthy"]
    out2 = {}
    ok2 = asyncio.run(EF.refusal_step(rpc, F._parse_rpc_result, "theprotocol_federationVetoProposal", "3", {}, "d", out2,
                                      "x", codes=(403,), text=("federation proposal not found", "settlement")))
    assert not ok2 and "any of 'federation proposal not found', 'settlement'" in out2["refusal: federationVetoProposal x"][
        "fail_reason"]


def test_a_named_5xx_is_a_refusal_only_with_its_words_and_never_bare():
    def _rpc(code, text):
        async def rpc(tool, args, jwt="", timeout=20):
            return False, _error(text), code
        return rpc
    name = "refusal: getRelayStatus x"
    words = ("not as a relay",)
    for code, text, codes, passes in (
            ("502", "HTTP 502: The agent's address answered, but not as a relay", (404, 422, 502), True),
            ("502", "HTTP 502: Bad Gateway", (404, 422, 502), False),                   # named, but not its words
            ("502", "HTTP 502: The agent's address answered, but not as a relay", (404, 422), False),  # not named
            ("500", "HTTP 500: not as a relay", (404, 422, 502), False)):                # another 5xx
        out = {}
        ok = asyncio.run(EF.refusal_step(_rpc(code, text), F._parse_rpc_result, "theprotocol_getRelayStatus", "3", {},
                                         "d", out, "x", codes=codes, text=words))
        assert ok is passes and out[name]["healthy"] is passes, (code, text, codes)
    out = {}
    assert not asyncio.run(EF.refusal_step(_rpc("502", "HTTP 502: not as a relay"), F._parse_rpc_result,
                                           "theprotocol_getRelayStatus", "3", {}, "d", out, "x", codes=(502,))), \
        "a 5xx with no words asked for stays red"
