"""§MCPTEST30 (V0651, order (p), agentvault2-d3, 2026-10-31): the token bridge is retired (his word, typed in d3's session
~11:43Z: "retire."), so the tester names none of its five tools. Session-release's (p) removes theprotocol_bridgeTransfer,
bridgeIssueWrapped, bridgeRedeem, bridgeUnlock and getBridgeStatus from the catalogs and answers every /api/v1/bridge/*
route 410 whatever TOKEN_BRIDGE_ENABLED says; getBridgeAggregate stays, an admin read of the history.

This replaces test_mcp_bridge_switch.py (D8, 2026-10-08: a bridge switched off read as switched off, not as five broken
contracts): with the tools gone there is nothing left to switch. RED on the code before: each table below still named a
bridge tool (five contracts and an autogen one, the switch row, two by-design reasons, the refusal probe, the NaN probe,
four admin probes, the held-back row).
"""
from __future__ import annotations

import ast
import pathlib

from agentvault_registry.api_tests.contracts import earned_agent_public as P
from agentvault_registry.api_tests.contracts import mcp_switches as M
from agentvault_registry.api_tests.contracts import refusal_reasons as R
from agentvault_registry.api_tests.contracts.mcp_contracts import MCP_CONTRACTS
from agentvault_registry.api_tests.contracts.mcp_contracts_autogen import MCP_AUTOGEN_CONTRACTS

RETIRED = {f"theprotocol_{n}" for n in ("bridgeTransfer", "bridgeIssueWrapped", "bridgeRedeem", "bridgeUnlock",
                                       "getBridgeStatus")}
CONTRACTS = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry" / "api_tests" / "contracts"


def test_no_contract_names_a_retired_tool():
    assert not RETIRED & set(MCP_CONTRACTS) and not RETIRED & set(MCP_AUTOGEN_CONTRACTS)


def test_no_switch_reason_or_held_back_row_names_one():
    assert not RETIRED & set(M.SWITCHED_TOOLS)
    assert not hasattr(M, "BRIDGE_OFF"), "the switch row that read the bridge's 404 went with the bridge"
    assert not RETIRED & set(R.BY_DESIGN_REFUSAL)
    assert P.HELD_BACK == ()


def test_no_lifecycle_calls_one():
    files = sorted(CONTRACTS.glob("*.py"))
    assert len(files) > 20, f"the reader sees {len(files)} contract modules: it is not looking at the tester"
    called = set()
    for f in files:
        for n in ast.walk(ast.parse(f.read_text())):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value in RETIRED:
                called.add((f.name, n.value))
    assert not called, called


def test_the_history_read_stays():
    # getBridgeAggregate reads the bridge's history (an admin read); it stays on the admin surface
    assert "theprotocol_getBridgeAggregate" in (CONTRACTS / "mcp_admin_lifecycles.py").read_text()


# ── the row that measures the retirement where it runs (earned_ad_retired) ──────────────────────────────────────────────
import asyncio  # noqa: E402
import json  # noqa: E402
from typing import Any, Dict, Optional  # noqa: E402

import pytest  # noqa: E402

from agentvault_registry.api_tests.contracts import earned_ad_retired as RT  # noqa: E402
from agentvault_registry.api_tests.contracts import earned_admin_dev  # noqa: E402
from agentvault_registry.api_tests.contracts.mcp_contracts import McpFixtureBag  # noqa: E402


def _body(obj: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(obj)}]}}


def _parse(b: Dict[str, Any]) -> Any:
    try:
        return json.loads(b["result"]["content"][0]["text"])
    except Exception:                                                  # noqa: BLE001
        return {}


class _Admin:
    """adminRequest as the admin bridge answers it: the route's status and its problem+json body."""

    def __init__(self, answer: Optional[Dict[str, tuple]] = None):
        self.answer, self.calls = answer or {}, []

    async def __call__(self, tool: str, args: dict, jwt: str = "", timeout: int = 20):
        assert tool == "theprotocol_adminRequest" and jwt == "dev-jwt"
        self.calls.append((args["method"], args["endpoint"], args.get("body")))
        st, detail, title = self.answer.get(args["endpoint"], (410, RT.SENTENCE, "Gone"))
        return True, _body({"status_code": st, "ok": False, "response": {"type": "about:blank", "title": title,
                                                                         "status": st, "detail": detail}}), "200"


def _run(admin: Optional[_Admin]) -> Dict[str, dict]:
    bag = McpFixtureBag(sentinel_did="did:theprotocol:offline", sentinel_jwt="s", developer_jwt="dev-jwt", developer_id="1")
    if admin is not None:
        bag.rpc_admin = admin              # type: ignore[attr-defined]
    out: Dict[str, dict] = {}

    async def no_rpc(*_a, **_k):
        raise AssertionError("the row reads REST through the admin bridge only")
    asyncio.run(RT.lifecycle_bridge_retired(no_rpc, _parse, bag, out))
    return out


def test_a_registry_that_retired_the_bridge_reads_green():
    admin = _Admin()
    row = _run(admin)[RT.ROW]
    assert row["healthy"] and not row.get("fail_reason") and row["result_excerpt"]["answered_410_with_the_sentence"] == 6
    assert [c[:2] for c in admin.calls] == list(RT.ROUTES), "each of the six, once"
    assert all(c[2] == {} for c in admin.calls if c[0] == "POST"), "a POST carries an empty body: nothing to read"


@pytest.mark.parametrize("path,answer,needle", [
    ("/api/v1/bridge/redeem", (404, "Not Found", "Not Found"), "HTTP 404"),         # an image before V0651
    ("/api/v1/bridge/transfer", (410, "gone", "Gone"), "detail 'gone'"),            # another sentence
    ("/api/v1/bridge/confirm-lock", (200, None, None), "HTTP 200"),                  # a route still acting
])
def test_a_route_not_retired_as_p_says_is_red_and_named(path, answer, needle):
    row = _run(_Admin({path: answer}))[RT.ROW]
    assert not row["healthy"] and path in row["fail_reason"] and needle in row["fail_reason"], row


def test_no_admin_bridge_is_not_measured_and_says_so():
    row = _run(None)[RT.ROW]
    assert not row.get("healthy") and "bag.rpc_admin" in str(row.get("skip_reason")), row


def test_the_row_runs_with_the_earned_admin_lifecycles():
    assert "earn_bridge_retired" in [lc["name"] for lc in earned_admin_dev.LIFECYCLES]
    assert len(RT.ROUTES) == 6 and len({p for _m, p in RT.ROUTES}) == 6
