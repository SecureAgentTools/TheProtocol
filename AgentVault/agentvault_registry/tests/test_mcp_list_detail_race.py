"""V0649 (agentvault2-13, 2026-10-30): the list/detail probe tells a row deleted between its two reads from a population
difference. pair_proof_v0645's first attempt (nt261026x4, 2026-10-27) went red on getMyWebhooks -> getWebhook: the
owner-scoping lifecycle deleted its webhook 62 ms after the probe listed it and 35 ms before the detail asked. On a
detail 404 the probe now reads the list once more: an id no longer listed is NOT MEASURED for that id ("gone from the
list"), an id still listed is asked again and only a second refusal stays a BUG-FIND. Fails on V0647's probe (control).
"""
from __future__ import annotations

import asyncio
import json

from agentvault_registry.api_tests.contracts import list_detail as LD
from agentvault_registry.api_tests.contracts import mcp_lifecycles as L
from agentvault_registry.api_tests.categories.flow_mcp_lifecycle.test_flow_mcp_lifecycle import _parse_rpc_result

PAIR = LD.Pair("theprotocol_getMyWebhooks", "3", ("webhooks",), "id", "theprotocol_getWebhook", "webhook_id", "id")
NAME = "list_detail: getMyWebhooks -> getWebhook"


def _ok(payload):
    return True, {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(payload)}]}}, "200"


def _err(text):
    return False, {"jsonrpc": "2.0", "id": 1, "result": {"isError": True, "content": [{"type": "text", "text": text}]}}, "200"


class _Bag:
    developer_jwt, sentinel_jwt, sentinel_did = "dev", "sentinel-jwt", "did:theprotocol:sentinel"

    def get(self, k, d=None):
        return d


def _run(lists, detail):
    """`lists`: the list answers in order (the first read, then the re-read); `detail(id, nth)` answers a detail."""
    calls, asked = [], {}

    async def rpc(tool, args, jwt="", timeout=30):
        calls.append(tool)
        if tool == PAIR.list_tool:
            return lists.pop(0)
        i = args["webhook_id"]
        asked[i] = asked.get(i, 0) + 1
        return detail(i, asked[i])
    out = {}
    asyncio.run(LD.run_pairs(lambda tier: rpc, _parse_rpc_result, _Bag(), out, (PAIR,), L._make_outcome, L._answered))
    return out[NAME], calls


def _not_found():
    return _err("Error: getWebhook returned HTTP 404: Webhook not found")


def test_an_id_deleted_between_the_reads_is_not_a_finding():
    first = _ok({"webhooks": [{"id": "w1"}, {"id": "w2"}]})
    after = _ok({"webhooks": [{"id": "w1"}]})                       # another lifecycle deleted w2 in between
    row, calls = _run([first, after], lambda i, n: _ok({"id": i}) if i == "w1" else _not_found())
    assert row["healthy"] is True and not row.get("fail_reason"), row
    assert row["result_excerpt"]["answers"] == ["same", LD.GONE]
    assert calls == [PAIR.list_tool, PAIR.detail_tool, PAIR.detail_tool, PAIR.list_tool], "a gone id is not asked again"


def test_every_id_gone_is_not_measured_and_says_why():
    first = _ok({"webhooks": [{"id": "w2"}]})
    row, _ = _run([first, _ok({"webhooks": []})], lambda i, n: _not_found())
    assert row["healthy"] is False and row["skip_reason"].startswith("NOT MEASURED: 1 of 1 id(s) the list advertised were "
                                                                     "gone from it on a re-read")


def test_an_id_still_listed_and_still_refused_stays_a_finding():
    lst = _ok({"webhooks": [{"id": "w1"}, {"id": "w2"}]})
    row, calls = _run([lst, lst], lambda i, n: _ok({"id": i}) if i == "w1" else _not_found())
    assert row["healthy"] is False and row["fail_reason"].startswith("BUG-FIND: list/detail: 1 of 2 id(s)")
    assert calls.count(PAIR.detail_tool) == 3, "w2 is asked a second time"


def test_an_id_still_listed_that_resolves_on_the_second_ask_passes():
    lst = _ok({"webhooks": [{"id": "w2"}]})
    row, _ = _run([lst, lst], lambda i, n: _not_found() if n == 1 else _ok({"id": i}))
    assert row["healthy"] is True and row["result_excerpt"]["answers"] == ["same"]


def test_a_failed_re_read_leaves_the_finding_standing():
    lst = _ok({"webhooks": [{"id": "w2"}]})
    row, _ = _run([lst, _err("Error: getMyWebhooks returned HTTP 503")], lambda i, n: _not_found())
    assert row["healthy"] is False and "BUG-FIND" in row["fail_reason"]


def test_the_verdict_counts_gone_ids_as_neither_pass_nor_finding():
    assert LD.verdict(["same", LD.GONE]) == (True, None)
    assert LD.verdict(["refused 404", LD.GONE])[1].startswith("BUG-FIND: list/detail: 1 of 1 id(s)")
    assert LD.verdict([LD.GONE, LD.GONE])[0] is None
