"""§MCPTEST30 V0643 (agentvault2-aa, 2026-10-25; agentvault2-66's find on the V0641 operator read): a read-after-write
check judges a write that answered 2xx, and a refused write keeps its own failure.

lifecycle_webhook's delete answered 409 on sbxalphaop (a product race: the parallel lifecycles' agent.* deliveries land
between the route's two deletes), and the row read "BUG-FIND: deleteWebhook returned 2xx but id=... still present in
getMyWebhooks": the read-back check ran on getMyWebhooks whatever the delete answered, and `_exec_step` wrote its sentence
over the delete's own. A write that failed on its own now keeps its reason (the check's sentence is kept as `read_back`);
a 2xx write the read-back contradicts is a BUG-FIND as before, and so is a refusal the step expected (a healthy row) that
the read-back finds changed something.
"""
from __future__ import annotations

import asyncio
import json

from agentvault_registry.api_tests.contracts import mcp_lifecycles as L


def _answer(obj, code):
    if code.startswith("2"):
        return True, {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(obj)}],
                                                             "structuredContent": obj}}, code
    return False, {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text",
                                                                       "text": f"Error: HTTP {code}: {obj}"}],
                                                          "isError": True}}, code


def _parse(body):
    try:
        return json.loads(body["result"]["content"][0]["text"])
    except Exception:
        return {"_text": str(body)}


def _still_present(inner):
    """The webhook lifecycle's check in substance: the deleted id is still listed."""
    if any(isinstance(w, dict) and w.get("id") == "wh-1" for w in inner.get("webhooks") or []):
        return "deleteWebhook returned 2xx but id=wh-1 still present in getMyWebhooks"
    return None


def _run(write_code, write_expect="success"):
    async def rpc(tool, args, jwt="", timeout=15):
        if tool == "theprotocol_deleteWebhook":
            return _answer({"deleted": True} if write_code.startswith("2") else "the webhook still has deliveries",
                           write_code)
        return _answer({"webhooks": [{"id": "wh-1"}]}, "200")
    out = {}

    async def go():
        await L._exec_step(rpc, _parse, "theprotocol_deleteWebhook", "3", {"webhook_id": "wh-1"}, "jwt", out,
                           expect_status=write_expect)
        await L._exec_step(rpc, _parse, "theprotocol_getMyWebhooks", "3", {}, "jwt", out,
                           record_as_separate=False, verify_against="theprotocol_deleteWebhook",
                           verify_against_check=_still_present)
    asyncio.run(go())
    return out["theprotocol_deleteWebhook"]


def test_a_refused_write_keeps_its_own_reason():
    row = _run("409")
    assert row["healthy"] is False and row["status_code"] == 409
    assert not str(row["fail_reason"]).startswith("BUG-FIND"), row["fail_reason"]
    assert "2xx" not in str(row["fail_reason"]), "no 2xx the server never answered"
    assert row["read_back"] == "deleteWebhook returned 2xx but id=wh-1 still present in getMyWebhooks"


def test_a_2xx_write_the_read_back_contradicts_is_a_bug_find():
    row = _run("200")
    assert row["healthy"] is False and row["status_code"] == 200
    assert row["fail_reason"] == "BUG-FIND: deleteWebhook returned 2xx but id=wh-1 still present in getMyWebhooks"
    assert "read_back" not in row


def test_a_healthy_refusal_row_is_still_judged_by_its_read_back():
    # the mechanics only: a row the step accepted (an expected 4xx) is not one that "failed on its own"
    row = _run("409", write_expect="error_4xx")
    assert row["healthy"] is False and row["fail_reason"].startswith("BUG-FIND: "), row
    assert "read_back" not in row
