"""§MCPTEST30 (V0644): a renamed tool keeps the response keys harvested under its old name, and the OpenAPI resource
gets the time its first build takes.

The V0643 pair proof (nt261026x2, 2026-10-26) failed on 18 rows. 17 were W3-renamed tools (getApyRates ->
getLockPayoutTiers and the rest): their contracts were renamed, the harvest file (mcp_response_expect_keys.json) was
not, so `get_contract(<new name>)` found no keys and the strict sweep read each tool as a contract gap, where V0642 had
checked the same keys under the old names and passed. The 18th was `resources/read theprotocol://registry/openapi`:
-32603 after the 8 s fetch budget, the worker's first build of the document outlasting it under the proof's load.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentvault_registry.api_tests.contracts import mcp_contracts as C  # noqa: E402
from agentvault_registry.mcp import resources as R  # noqa: E402
from agentvault_registry.mcp.tool_aliases import TOOL_ALIASES  # noqa: E402

_HARVEST = json.loads((Path(C.__file__).parent / "mcp_response_expect_keys.json").read_text())
_OLD_NAME = {new: old for old, new in TOOL_ALIASES.items()}

# The 17 contract-gap rows of nt261026x2's MCP lifecycle run (608a32e31eae402f).
NT261026X2_GAPS = (
    "getAgentLockHistory", "getAgentLockedBalance", "getAgentPayoutHistory", "getAgentPendingPayouts",
    "getLockPayoutStats", "getLockPayoutTiers", "getLockPayoutTiersTeg", "getLockStats", "getMyIncome",
    "getMyLockHistory", "getMyLockStats", "getMyLockStatus", "getMyPayoutHistory", "getPayoutRelockForAgent",
    "getRegistryTreasury", "getUnitPayouts", "getUnitTransactions",
)


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def _own_contract(tool):
    if tool in C.MCP_CONTRACTS:
        return C.MCP_CONTRACTS[tool]
    return C._autogen_dict().get(tool)


@pytest.mark.parametrize("bare", NT261026X2_GAPS)
def test_each_tool_nt261026x2_read_as_a_contract_gap_now_resolves_its_old_names_keys(bare):
    tool = f"theprotocol_{bare}"
    keys = _HARVEST[_OLD_NAME[tool]]
    assert keys and C.get_contract(tool).expect_keys == keys


def test_every_renamed_tool_whose_contract_names_no_keys_takes_its_old_names():
    carried = []
    for old, new in TOOL_ALIASES.items():
        if old not in _HARVEST or new in _HARVEST:
            continue
        own = _own_contract(new)
        if own is not None and (own.expect_keys or own.skip_reason):
            continue  # its own keys, or its skip, win as for any tool
        assert C.get_contract(new).expect_keys == _HARVEST[old], new
        carried.append(new)
    assert set(f"theprotocol_{b}" for b in NT261026X2_GAPS) <= set(carried)


def test_an_entry_under_the_new_name_wins_and_other_tools_are_untouched():
    out = C._carry_renamed_tools({
        "theprotocol_getApyRates": ["old"], "theprotocol_getLockPayoutTiers": ["new"],
        "theprotocol_getMyEarnings": ["income"], "theprotocol_someTool": ["k"],
    })
    assert out["theprotocol_getLockPayoutTiers"] == ["new"]
    assert out["theprotocol_getMyIncome"] == ["income"]
    assert out["theprotocol_someTool"] == ["k"]


def test_a_harvest_that_is_not_a_map_carries_nothing():
    assert C._carry_renamed_tools([]) == {}


class _Answer:
    status_code = 200
    text = "{}"


def _recording_client(seen, raises=None):
    class _Client:
        def __init__(self, timeout=None, **_kw):
            seen.append(timeout)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def get(self, _url):
            if raises is not None:
                raise raises
            return _Answer()

    return _Client


def test_the_openapi_read_waits_thirty_seconds_and_the_other_documents_eight(monkeypatch):
    seen = []
    monkeypatch.setattr(R.httpx, "AsyncClient", _recording_client(seen))
    for uri in ("theprotocol://registry/openapi", "theprotocol://registry/card"):
        out, err = asyncio.run(R.read_resource(uri))
        assert err is None and out["contents"][0]["uri"] == uri
    assert (seen[0].read, seen[1].read) == (30.0, 8.0)
    assert seen[0].connect == seen[1].connect == 3.0


def test_a_read_that_times_out_names_the_timeout(monkeypatch):
    monkeypatch.setattr(R.httpx, "AsyncClient", _recording_client([], raises=R.httpx.ReadTimeout("")))
    out, err = asyncio.run(R.read_resource("theprotocol://registry/openapi"))
    assert out is None and R.error_code(err) == -32603
    assert "ReadTimeout" in str(err)
