"""§MCPTEST30 (V0546) — a read-after-write check that judged nothing says so at run time.

The mTLS toggle's checks read `enabled` / `mtls_enabled` and the route answers `enrolled`: each check returned "no
finding" on every run since it was written, and V0545 found it by reading the code. `_exec_step` now hands every check a
dict that logs the top-level keys it asks for; a 2xx read that carries none of them notes the PARENT mutation
(`unjudged_read_back`), and the sweep's summary lists those mutations. A refused read is excluded (after a delete, a 404
is the judgment), and so is a check that tests absence with `in`.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from agentvault_registry.api_tests.contracts import mcp_lifecycles as L


def _ok(obj, code="200"):
    return True, {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(obj)}],
                                                         "structuredContent": obj}}, code


def _parse(body):
    try:
        return json.loads(body["result"]["content"][0]["text"])
    except Exception:
        return {"_text": str(body)}


def _run(read_answer, check, read_code="200"):
    async def rpc(tool, args, jwt="", timeout=15):
        if tool == "theprotocol_mutate":
            return _ok({"done": True})
        if read_code.startswith("2"):
            return _ok(read_answer, read_code)
        return False, {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text",
                                                                           "text": f"Error: HTTP {read_code}: gone"}],
                                                              "isError": True}}, read_code
    out = {}

    async def go():
        await L._exec_step(rpc, _parse, "theprotocol_mutate", "3", {}, "jwt", out, expect_status="any")
        await L._exec_step(rpc, _parse, "theprotocol_read", "3", {}, "jwt", out, expect_status="any",
                           record_as_separate=False, verify_against="theprotocol_mutate", verify_against_check=check)
    asyncio.run(go())
    return out


def _old_mtls_check(inner):
    """The check the toggle carried before V0545, verbatim in substance: it never read the route's field."""
    actual = inner.get("enabled")
    if actual is None:
        actual = inner.get("mtls_enabled")
    if actual is None:
        return None
    return None if actual else "enableMtls returned 2xx but getMyMtlsStatus.enabled is False"


def test_the_key_log_records_what_a_check_asked_and_found():
    k = L._KeyLog({"enrolled": True, "spiffe_id": "x"})
    assert k.get("enabled") is None and k["enrolled"] is True and k.get("spiffe_id") == "x"
    assert k.asked == {"enabled", "enrolled", "spiffe_id"} and k.found == {"enrolled", "spiffe_id"}
    assert "absent" not in k and k.asked == {"enabled", "enrolled", "spiffe_id"}, "`in` is not logged"
    assert dict(k) == {"enrolled": True, "spiffe_id": "x"} and isinstance(k, dict)


def test_the_pre_v0545_mtls_check_is_named_as_judging_nothing():
    out = _run({"enrolled": False, "spiffe_id": None, "enrolled_at": None}, _old_mtls_check)
    row = out["theprotocol_mutate"]
    assert row["healthy"] is True, "judging nothing is not a failure of the mutation"
    assert row["unjudged_read_back"] == (
        "theprotocol_read answered 200 without any of ['enabled', 'mtls_enabled'], the keys the check reads: the "
        "read-after-write judged nothing")


def test_the_v0545_check_judges_and_flags_a_flip_that_did_not_land():
    out = _run({"enrolled": False}, L.verify_mtls_flip(True, "enableMtls"))
    row = out["theprotocol_mutate"]
    assert row["healthy"] is False and row["fail_reason"].startswith("BUG-FIND: enableMtls returned 2xx")
    assert "unjudged_read_back" not in row
    ok = _run({"enrolled": True}, L.verify_mtls_flip(True, "enableMtls"))["theprotocol_mutate"]
    assert ok["healthy"] is True and "unjudged_read_back" not in ok


def test_a_refused_read_is_not_called_unjudged():
    """After a delete a 404 IS the judgment: the TEG policy delete check passes on it by design."""
    out = _run({}, lambda inner: None if inner.get("error") or not inner.get("id") else "still there", read_code="404")
    assert "unjudged_read_back" not in out["theprotocol_mutate"]


def test_a_check_that_tests_absence_with_in_is_not_called_unjudged():
    out = _run({"status": "gone"}, lambda inner: "still active" if "id" in inner else None)
    assert "unjudged_read_back" not in out["theprotocol_mutate"]


def test_a_check_that_found_one_of_several_keys_judged():
    out = _run({"enrolled": True}, lambda inner: None if (inner.get("enabled") or inner.get("enrolled")) else "off")
    assert "unjudged_read_back" not in out["theprotocol_mutate"]


def test_every_lifecycle_check_still_runs_on_a_plain_dict_view():
    """Every check in the file is handed the key log: a check that type-tests `dict` or copies it must still work."""
    k = L._KeyLog({"a": 1})
    assert isinstance(k, dict) and dict(k) == {"a": 1} and json.dumps(k) == '{"a": 1}' and k.copy() == {"a": 1}


def test_the_summary_lists_the_mutations_whose_read_back_judged_nothing():
    import inspect
    from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F
    src = inspect.getsource(F.McpLifecycleFlow.test_mcp_lifecycle_flow) if hasattr(F, "McpLifecycleFlow") else \
        open(F.__file__).read()
    assert '"unjudged_read_backs": sorted(t for t, o in lifecycle_outcomes.items()' in src


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
