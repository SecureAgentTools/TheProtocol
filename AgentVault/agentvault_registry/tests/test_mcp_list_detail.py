"""§MCPTEST30 (2026-10-01) — the MCP tester's list/detail probe: every id a list tool advertises must resolve at its
detail tool. Round 5 found one pair by luck of fixture order (the compliance overview listed peer rows the per-operator
detail never searched); this probe asks on purpose. The judge, the row picking and the engine, against fakes."""
from __future__ import annotations

import asyncio
import json

import pytest

from agentvault_registry.api_tests.contracts import list_detail as LD
from agentvault_registry.api_tests.contracts import mcp_lifecycles as L
from agentvault_registry.api_tests.categories.flow_mcp_lifecycle.test_flow_mcp_lifecycle import (
    _SYNTHETIC_ROW_PREFIXES, _parse_rpc_result)


def _ok(payload):
    return True, {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(payload)}]}}, "200"


def _err(text):
    return False, {"jsonrpc": "2.0", "id": 1, "result": {"isError": True, "content": [{"type": "text", "text": text}]}}, "200"


def test_pick_takes_the_first_the_middle_and_the_last_without_repeats():
    rows = [{"id": i} for i in range(1, 8)]
    assert LD.pick(rows, "id") == [1, 4, 7]
    assert LD.pick([{"id": "a"}], "id") == ["a"]
    assert LD.pick([{"id": "a"}, {"id": "b"}], "id") == ["a", "b"]
    assert LD.pick([{"x": 1}, {"id": None}], "id") == []


def _kind(answer, expect, field="id"):
    ok, body, code = answer
    return LD.detail_kind(ok, _parse_rpc_result(body), code, L._answered, expect, field)


def test_a_detail_answer_names_the_same_object_another_or_refuses():
    assert _kind(_ok({"id": "A1"}), "a1") == "same", "ids compare case-insensitively (a DID, a uuid)"
    assert _kind(_ok({"id": "B2"}), "A1") == "other"
    assert _kind(_ok({"organization": {"id": 7}}), 7, "organization.id") == "same"
    assert _kind(_ok({"name": "x"}), 7) == "no_id"
    assert _kind(_err("Error: getX returned HTTP 404: not found"), 7) == "refused 404"
    assert _kind(_err("Error: getX returned HTTP 500"), 7) == "server_error 500"
    assert _kind((False, {}, "502"), 7) == "no_answer"


def test_a_designed_consent_step_is_neither_a_pass_nor_a_finding():
    assert LD.verdict(["refused 409", "same"], designed=("refused 409",)) == (True, None)
    assert LD.verdict(["refused 409"], designed=("refused 409",))[0] is None
    assert LD.verdict(["refused 403"], designed=("refused 409",))[0] is False


def test_the_verdict_names_a_population_difference():
    assert LD.verdict(["same", "same"]) == (True, None)
    healthy, sentence = LD.verdict(["same", "refused 404", "refused 404"])
    assert healthy is False and sentence.startswith("BUG-FIND: list/detail: 2 of 3 id(s)") and "refused 404" in sentence
    assert LD.verdict([])[0] is None and LD.verdict(["no_answer"])[0] is None and LD.verdict(["no_id"])[0] is None


def test_an_empty_list_rows_without_ids_and_designed_answers_are_three_sentences():
    """V0545: one sentence ("the list returned no row carrying an id") stood for all three."""
    assert LD.verdict(["refused 409", "refused 409"], designed=("refused 409",)) == (
        None, "NOT MEASURED: every detail answer was a designed step (refused 409), so none showed the row")
    assert LD.verdict([]) == (None, "NOT MEASURED: no detail was asked")
    pair = LD.Pair("theprotocol_listThings", "3", ("things",), "id", "theprotocol_getThing", "thing_id", "id")
    filtered = LD.Pair("theprotocol_listThings", "3", ("things",), "id", "theprotocol_getThing", "thing_id", "id",
                       row_where=(("ready", True),))
    for rows, p, want in (([], pair, "NOT MEASURED: the list is empty (0 rows), so no detail can be asked"),
                          ([{"name": "a"}, {"name": "b"}], pair, "NOT MEASURED: 2 row(s), none carrying `id`"),
                          ([{"id": 1, "ready": False}], filtered,
                           "NOT MEASURED: 1 row(s), none carrying `id` among those the pair's row filters admit")):
        calls = []

        async def rpc(tool, args, jwt="", timeout=30, _rows=rows):
            calls.append(tool)
            return _ok({"things": _rows})
        out = {}
        asyncio.run(LD.run_pairs(lambda tier: rpc, _parse_rpc_result, _Bag(), out, (p,), L._make_outcome, L._answered))
        row = out["list_detail: listThings -> getThing"]
        assert row["skip_reason"] == want, row["skip_reason"]
        assert calls == ["theprotocol_listThings"], "no detail is asked without an id"
        assert row["result_excerpt"]["asked"] == 0


class _Bag:
    developer_jwt, sentinel_jwt, sentinel_did = "dev", "sentinel-jwt", "did:theprotocol:sentinel"

    def get(self, k, d=None):
        return d


def test_the_engine_reads_a_list_and_asks_the_detail_for_each_picked_id():
    pair = LD.Pair("theprotocol_listThings", "3", ("things",), "id", "theprotocol_getThing", "thing_id", "id")
    calls = []

    async def rpc(tool, args, jwt="", timeout=30):
        calls.append((tool, args))
        if tool == "theprotocol_listThings":
            return _ok({"things": [{"id": i} for i in range(1, 6)]})
        if args["thing_id"] == 5:
            return _err("Error: getThing returned HTTP 404: Thing not found")
        return _ok({"id": args["thing_id"]})
    out = {}
    asyncio.run(LD.run_pairs(lambda tier: rpc, _parse_rpc_result, _Bag(), out, (pair,), L._make_outcome, L._answered))
    row = out["list_detail: listThings -> getThing"]
    assert [c[1].get("thing_id") for c in calls[1:]] == [1, 3, 5]
    assert row["healthy"] is False and "1 of 3 id(s)" in row["fail_reason"]
    assert row["result_excerpt"] == {"rows": 5, "asked": 3, "answers": ["same", "same", "refused 404"]}
    assert row["probe_expect_status"] == "success"
    no_admin = {}
    admin_pair = LD.Pair("theprotocol_listA", "admin", ("items",), "id", "theprotocol_getA", "id", "id")
    asyncio.run(LD.run_pairs(lambda tier: None if tier == "admin" else rpc, _parse_rpc_result, _Bag(), no_admin,
                             (admin_pair,), L._make_outcome, L._answered))
    assert no_admin["list_detail: listA -> getA"]["skip_reason"].startswith("NOT MEASURED: no transport")


def test_every_pair_is_well_formed_and_the_lifecycle_is_registered():
    names = [lc["name"] for lc in L.LIFECYCLES]
    assert names.index("list_detail") == names.index("page_bounds") + 1
    assert "list_detail: " in _SYNTHETIC_ROW_PREFIXES
    assert LD.PAIRS, "a probe with no pairs measures nothing"
    from agentvault_registry.mcp import server, server_admin
    for p in LD.PAIRS:
        for tool, tier in ((p.list_tool, p.tier), (p.detail_tool, p.detail_tier or p.tier)):
            table = server_admin.ADMIN_TOOL_DISPATCH if tier == "admin" else server.TOOL_DISPATCH
            assert tool in table, (tool, tier)
        assert p.tier in ("1", "2", "3", "admin") and p.row_id and p.detail_arg and p.detail_id


def test_a_wrapped_detail_refusal_is_classified_never_lost():
    """Round 7: two circuits' detail failed and the judge, reading the wrapped status as a lost call, passed the pair."""
    wrapped = (False, {"jsonrpc": "2.0", "id": 1, "result": {"isError": True, "content": [
        {"type": "text", "text": "Error: circuits/x/acir returned HTTP 500: ACIR binary not found"}]}}, "500")
    assert _kind(wrapped, "x") == "server_error 500"
    assert LD.verdict(["same", "server_error 500"])[0] is False


def test_a_failure_without_an_error_key_is_still_a_refusal():
    """The admin and public GET helpers answer a non-2xx with {status_code, upstream_error, ...}, which the dispatcher
    does not mark isError: read as an answer, a 404 would hide as "no id"."""
    assert _kind(_ok({"status_code": 404, "upstream_error": "x returned HTTP 404", "path": "/x"}), 7) == "refused 404"
    assert _kind(_ok({"status_code": 500, "upstream_error": "x returned HTTP 500"}), 7) == "server_error 500"
    assert LD.failed_answer({"id": 7, "status": "active"}) is None


def test_the_row_filters_choose_the_population_the_detail_serves():
    rows = [{"id": 1, "status": "ACTIVE"}, {"id": 2, "status": "INACTIVE"}, {"id": 3, "status": "ACTIVE", "n": 900}]
    assert LD.pick(rows, "id", where=(("status", "ACTIVE"),)) == [1, 3]
    assert LD.pick(rows, "id", where=(("status", "ACTIVE"),), most=(("n", 50),)) == [1]


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


class _Scalars:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row

    def scalars(self):
        return self

    def first(self):
        return self._row


class _ByDidDB:
    """Answers get_agent_by_did's SELECTs in order: no Agent row, no card by agent_did, then the card named by did."""
    def __init__(self, named):
        self.answers, self.statements = [None, None, named], []

    async def execute(self, stmt):
        self.statements.append(str(stmt.compile(compile_kwargs={"literal_binds": True})))
        return _Scalars(self.answers.pop(0) if self.answers else None)


def test_a_federated_agent_discover_lists_resolves_at_its_profile(monkeypatch):
    """§MCPTEST30 (V0515): /discover's federated half names cards with no agent_did by card_data['did']; the by-DID
    route matched agent_did only, so each of those agents answered 404 at its profile."""
    from agentvault_registry.routers import agent_discovery as AD
    card = object()

    async def _track(db, did, resp):
        return {"did": did, **resp}
    monkeypatch.setattr(AD, "_attach_track_record", _track)
    monkeypatch.setattr(AD, "_build_federated_agent_response", lambda c: {"federated": c is card})
    db = _ByDidDB(card)
    out = asyncio.run(AD.get_agent_by_did(did="did:theprotocol:peer-1", db=db, current_developer=None))
    assert out == {"did": "did:theprotocol:peer-1", "federated": True}
    named = db.statements[2]
    assert "agent_cards.agent_did IS NULL" in named and "card_data ->> 'did'" in named
    with pytest.raises(Exception) as e:
        asyncio.run(AD.get_agent_by_did(did="did:theprotocol:nobody", db=_ByDidDB(None), current_developer=None))
    assert getattr(e.value, "status_code", None) == 404
