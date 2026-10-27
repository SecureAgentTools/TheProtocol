"""§MCPTEST30 (V0641): an operator run sends the cross-registry dust to its parent frame's canary receiver, and never
the made-up receiver that starts an FX route there.

tegCrossRegistryTransferDirect passed on a refusal alone on both sandbox operators: the contract's call sent 1 unit to
a made-up DID, which an operator routes through its FX gateway (409 "FX route did not settle ... it returned this
payment", every run: V0639's read and V0641's preview, 2026-10-25), and cross_registry_canary_recipient, the frame's
dust lifecycle, did not run on an operator. agentvault2-d6's word (2026-10-25): 0.01 dust from each operator to its
parent frame's canary receiver, mirroring what a frame's run sends its operators, and the made-up-receiver probe dropped
on the operators (the product side is D6-830). Pinned: the receiver is the parent's canary in the operator's own
currency (none otherwise, nothing sent), a frame's lookup is unchanged, and an operator run never sends the made-up DID.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F
from agentvault_registry.api_tests.contracts import mcp_lifecycles as L

_TOOL = "theprotocol_tegCrossRegistryTransferDirect"
_MADE_UP = "did:theprotocol:888eeb39-a53e-4554-74e2"
_OPERATOR_CFG = {"self": {"key": "sbxalphaop", "role": "operator", "parent": "sandbox-alpha", "currency": "SBXA"},
                 "peers": [{"key": "sandbox-alpha", "role": "frame", "parent": None, "currency": "SBXA"},
                           {"key": "sandbox-beta", "role": "frame", "parent": None, "currency": "SBXB"},
                           {"key": "sbxbetaop", "role": "operator", "parent": "sandbox-beta", "currency": "SBXB"}]}
_FRAME_CFG = {"self": {"key": "sandbox-alpha", "role": "frame", "currency": "SBXA"},
              "peers": [{"key": "sbxalphaop", "role": "operator", "parent": "sandbox-alpha", "currency": "SBXA"}]}
_PARENT_CANARY = "did:theprotocol:sandbox-a.theprotocol.cloud:27fedb94-7974-46ef-9d5d-e5c261affd10"


def _answer(payload):
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(payload)}]}}


def _error(text):
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "Error: " + text}],
                                                    "isError": True}}


def _run(cfg, canary=_PARENT_CANARY):
    calls, queries = [], []

    async def rpc(tool, args, jwt="", timeout=20):
        calls.append((tool, dict(args)))
        if tool == "theprotocol_getPublicRegistryConfig":
            return True, _answer(cfg), "200"
        if tool == _TOOL:
            if args.get("receiver_did") == _MADE_UP:
                return False, _error("HTTP 400: Cannot resolve registry for receiver"), "400"
            return True, _answer({"transaction_id": "tx-1", "status": "initiated"}), "200"
        raise AssertionError(tool)

    async def target_db(sql, params, write=False):
        queries.append(dict(params))
        return (canary, None) if canary else (None, None)

    bag = SimpleNamespace(developer_jwt="d", sentinel_jwt="s", sentinel_did="did:theprotocol:sentinel",
                          flow_values={}, target_db=target_db, event_verifier=None)
    outcomes = {}
    asyncio.run(L.lifecycle_cross_registry_canary_recipient(rpc, F._parse_rpc_result, bag, outcomes))
    return outcomes, calls, queries


def test_an_operator_sends_its_dust_to_the_parent_frames_canary_and_never_the_made_up_receiver():
    outcomes, calls, queries = _run(_OPERATOR_CFG)
    sent = [a for t, a in calls if t == _TOOL]
    assert [a["receiver_did"] for a in sent] == [_PARENT_CANARY], "one transfer, to the parent's canary"
    assert sent[0]["amount"] == "0.01"
    assert queries == [{"n": "canary-%-receiver%", "s": "%/registry/sandbox-alpha"}]
    assert outcomes[_TOOL]["healthy"] is True and outcomes[_TOOL]["status_code"] == 200
    assert not [k for k in outcomes if k.startswith("refusal: ")], "the frame's made-up-receiver refusal is not sent"


def test_without_the_parent_canary_the_row_says_so_and_nothing_is_sent():
    outcomes, calls, _q = _run(_OPERATOR_CFG, canary=None)
    assert not [c for c in calls if c[0] == _TOOL]
    assert outcomes[_TOOL]["skip_reason"].startswith("NOT MEASURED: no canary receiver of this operator's parent frame")


def test_a_parent_in_another_currency_is_no_receiver():
    cfg = json.loads(json.dumps(_OPERATOR_CFG))
    cfg["peers"][0]["currency"] = "SBXB"
    outcomes, calls, queries = _run(cfg)
    assert queries == [] and not [c for c in calls if c[0] == _TOOL]
    assert outcomes[_TOOL]["skip_reason"].startswith("NOT MEASURED")


def test_a_frame_still_reads_its_operators_canaries_and_keeps_its_refusal_row():
    outcomes, calls, queries = _run(_FRAME_CFG)
    assert queries == [{"n": "canary-sbxalphaop-receiver%", "s": "%/registry/sbxalphaop"}]
    receivers = [a["receiver_did"] for t, a in calls if t == _TOOL]
    assert receivers == [_MADE_UP, _PARENT_CANARY]
    assert outcomes["refusal: tegCrossRegistryTransferDirect a receiver no peer registry holds"]["healthy"] is True
