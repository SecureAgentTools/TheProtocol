"""§MCPTEST30 (V0545) — the mTLS toggle lifecycle verifies the flip it was written to verify.

Its read-after-write checks read `enabled`, then `mtls_enabled`; the status route answers `enrolled`. Neither key ever
arrived, so each check returned "no finding" on every run: round 11 recorded enableMtls and disableMyMtls healthy
(both 200) on read-backs that judged nothing, and the status tool's only recorded call was one the transport timed out
(status 0, which an any-status step passes as below 500). The checks now read the route's field, the read-backs ask for
success, and the status contract runs on its own with the route's keys.
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import json

import pytest

from agentvault_registry.api_tests.contracts import mcp_lifecycles as L
from agentvault_registry.api_tests.contracts.mcp_contracts import MCP_CONTRACTS


def test_the_route_answers_enrolled():
    """The route's own keys, read off its return statement: the field the checks read must be one of them."""
    from agentvault_registry.routers import agent_mtls
    fn = next(n for n in ast.walk(ast.parse(inspect.getsource(agent_mtls)))
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "mtls_status")
    keys = {k.value for n in ast.walk(fn) if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict)
            for k in n.value.keys if isinstance(k, ast.Constant)}
    assert "enrolled" in keys and not {"enabled", "mtls_enabled"} & keys, keys
    assert set(MCP_CONTRACTS["theprotocol_getMyMtlsStatus"].expect_keys) <= keys


@pytest.mark.parametrize("inner,want", [
    ({"enrolled": True, "spiffe_id": "spiffe://x"}, True),
    ({"enrolled": False, "spiffe_id": None}, False),
    ({"mtls_enabled": True}, True),                       # the old names stay as fallbacks, after the route's own
    ({"enabled": False}, False),
    ({"spiffe_id": "spiffe://x"}, None),                  # nothing to read: judged nowhere here (the contract's keys)
    ({"_text": "Error: HTTP 401"}, None),
    ("not a dict", None),
    ({"enrolled": "yes"}, None),                          # a non-bool is not an answer
])
def test_the_state_is_read_from_the_field_the_route_answers(inner, want):
    assert L.mtls_enrolment(inner) is want


def test_a_flip_that_did_not_land_is_a_bug_find_on_the_mutation():
    after_enable = L.verify_mtls_flip(True, "enableMtls")
    after_disable = L.verify_mtls_flip(False, "disableMyMtls")
    assert after_enable({"enrolled": True}) is None and after_disable({"enrolled": False}) is None
    assert after_enable({"enrolled": False}) == (
        "enableMtls returned 2xx but getMyMtlsStatus reads enrolled=False (the flip did not land)")
    assert "disableMyMtls returned 2xx" in after_disable({"enrolled": True})
    # CONTROL: the shape the old checks read never arrives, so they could not fail; the new one can
    assert after_enable({"enrolled": False, "docker_label": None, "spiffe_id": None}) is not None


def _drive(status_answers, enable_code="200", disable_code="200"):
    """Run the lifecycle over a fake transport: enable, a status read, disable, a status read."""
    calls = []
    reads = iter(status_answers)

    def body(obj):
        return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(obj)}],
                                                       "structuredContent": obj}}

    async def rpc(tool, args, jwt="", timeout=15):
        calls.append(tool)
        if tool == "theprotocol_enableMtls":
            return enable_code.startswith("2"), body({"status": "enrolled"}), enable_code
        if tool == "theprotocol_disableMyMtls":
            return disable_code.startswith("2"), body({"status": "unenrolled"}), disable_code
        code, obj = next(reads)
        if code == "0":   # the transport's timeout: no body, no status
            return False, {"_raw": ""}, "0"
        return True, body(obj), code

    def parse(b):
        try:
            return json.loads(b["result"]["content"][0]["text"])
        except Exception:
            return {}

    class Bag:
        developer_jwt, sentinel_jwt = "dev", "agent"
    out = {}
    asyncio.run(L.lifecycle_mtls_toggle(rpc, parse, Bag(), out))
    return out, calls


def test_the_lifecycle_flags_a_flip_that_did_not_land():
    out, calls = _drive([("200", {"enrolled": False, "spiffe_id": None}), ("200", {"enrolled": False})])
    assert calls == ["theprotocol_enableMtls", "theprotocol_getMyMtlsStatus",
                     "theprotocol_disableMyMtls", "theprotocol_getMyMtlsStatus"]
    assert out["theprotocol_enableMtls"]["healthy"] is False
    assert out["theprotocol_enableMtls"]["fail_reason"].startswith("BUG-FIND: enableMtls returned 2xx")
    assert out["theprotocol_disableMyMtls"]["healthy"] is True


def test_the_lifecycle_passes_a_flip_that_landed_and_records_the_read():
    out, _ = _drive([("200", {"enrolled": True, "spiffe_id": "spiffe://x"}), ("200", {"enrolled": False})])
    assert out["theprotocol_enableMtls"]["healthy"] is True and out["theprotocol_disableMyMtls"]["healthy"] is True
    assert out["theprotocol_getMyMtlsStatus"]["status_code"] == 200


def test_a_timed_out_read_back_verifies_nothing_and_records_nothing():
    """Status 0 passed an any-status step (0 < 500) and became the tool's only row ("REFUSED (HTTP 0)").

    Since V0545 (13) a read whose answer never arrived is asked once more (mcp_lifecycles.no_http_status), so each
    read-back here meets two timeouts: four answers for two read-backs."""
    out, calls = _drive([("0", None)] * 4)
    assert calls.count("theprotocol_getMyMtlsStatus") == 4, "each read-back asked once more, never a third time"
    assert "theprotocol_getMyMtlsStatus" not in out, "a read that never answered is no row of the tool"
    assert out["theprotocol_enableMtls"]["healthy"] is True, "an unverified flip is not called a failure"


def test_the_status_contract_runs_on_its_own():
    c = MCP_CONTRACTS["theprotocol_getMyMtlsStatus"]
    assert c.override_coverage_fan is True and c.expect_status == "success"
    assert c.arguments == {"agent_jwt": "${sentinel_jwt}"}


def test_no_flare_check_reads_a_field_its_read_cannot_carry():
    """getMyFlareStatus answers FlareStatusResponse, which has no bearer field: a check reading one judged nothing."""
    from agentvault_registry.routers.fiat_onramp import FlareStatusResponse
    assert "bears_encirclement_flare" not in FlareStatusResponse.model_fields
    assert "_verify_unequip" not in inspect.getsource(L.lifecycle_flare)


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
