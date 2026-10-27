"""§MCPTEST30 (2026-10-01) — the pagination partition check: two pages of n against one page of 2n, read only.

A feed ordered on a non-unique key can return a row on both pages and another on neither while two identical calls
agree (§DIRFEED-2). The judge must call that a BUG-FIND, call an ignored `limit` or `offset` one too, and refuse to judge
(NOT MEASURED) a list that moved between two identical reads or holds no second page; rows keep counts, never ids.
"""
from __future__ import annotations

import asyncio
import json
import random

import pytest

from agentvault_registry.api_tests.contracts import pagination_partition as PP
from agentvault_registry.api_tests.contracts.mcp_lifecycles import _answered, _make_outcome
from agentvault_registry.api_tests.categories.flow_mcp_lifecycle.test_flow_mcp_lifecycle import _parse_rpc_result


def _ok(obj):
    return True, {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps(obj)}],
                                                         "structuredContent": obj if isinstance(obj, dict) else None}}, "200"


ROWS = [{"id": f"r{i}", "created_at": "2026-10-01T00:00:00Z" if i < 4 else f"2026-10-0{i}T00:00:00Z", "name": f"n{i}"}
        for i in range(8)]


class Feed:
    """A paged list. `ties` reorders the four rows that share one sort key on every call (no unique tiebreak)."""

    def __init__(self, rows=ROWS, ties=False, ignore_offset=False, ignore_limit=False, grow=False, key="items",
                 grow_at=4, churn=False):
        self.rows, self.ties, self.ignore_offset, self.ignore_limit, self.grow, self.key = (
            list(rows), ties, ignore_offset, ignore_limit, grow, key)
        self.calls, self.seed, self.grow_at, self.limits, self.churn = 0, 7, grow_at, [], churn

    async def rpc(self, tool, args, jwt="", timeout=30):
        self.calls += 1
        self.limits.append(int(args.get("limit", 0)))
        rows = list(self.rows)
        if self.grow and self.calls >= self.grow_at:            # a row arrives before the read at grow_at
            rows.insert(0, {"id": "new", "created_at": "2026-10-09T00:00:00Z"})
        if self.churn and self.calls >= self.grow_at:           # V0556: a NEW row before every read from grow_at on
            rows.insert(0, {"id": f"new{self.calls}", "created_at": "2026-10-09T00:00:00Z"})
        off = 0 if self.ignore_offset else int(args.get("offset", 0))
        lim = 1000 if self.ignore_limit else int(args.get("limit", 1000))
        if self.ties:   # the planner's order of tied rows: the same for the same plan, another for another LIMIT/OFFSET
            head = rows[:4]
            random.Random(self.seed * 1000 + lim * 10 + off).shuffle(head)
            rows = head + rows[4:]
        page = rows[off:off + lim]
        return _ok({self.key: page, "total": len(rows)} if self.key else page)


class Bag:
    developer_jwt, sentinel_jwt, sentinel_did, developer_id = "dev", "agent", "did:theprotocol:s", 7

    def get(self, k, d=None):
        return getattr(self, k, d)


def _run(feed, paged=(("theprotocol_listAgentCards", "1", {}),)):
    out = {}
    asyncio.run(PP.run_paged(feed.rpc, _parse_rpc_result, Bag(), out, paged, _make_outcome, _answered))
    return out["pagination: " + paged[0][0].replace("theprotocol_", "")]


def test_a_feed_with_a_unique_order_is_a_partition():
    row = _run(Feed())
    assert row["healthy"] is True and not row["skip_reason"]
    assert row["result_excerpt"]["on_both"] == 0 and row["result_excerpt"]["on_neither"] == 0


def test_ties_without_a_tiebreak_are_a_bug_find():
    hits = 0
    for seed in range(20):
        f = Feed(ties=True)
        f.seed = seed
        row = _run(f)
        assert not row["skip_reason"], "the same plan returns the same order: the two big reads agree"
        if not row["healthy"]:
            hits += 1
            assert row["fail_reason"].startswith("BUG-FIND: pagination: two pages of 3 are not a partition")
    assert hits, "some seed must produce a duplicate or a missing row across the pages"


@pytest.mark.parametrize("kw,needle", [(dict(ignore_offset=True), "`offset` ignored"),
                                       (dict(ignore_limit=True), "`limit` not honored")])
def test_an_ignored_parameter_is_a_bug_find(kw, needle):
    row = _run(Feed(**kw))
    assert row["healthy"] is False and needle in row["fail_reason"]


@pytest.fixture(autouse=True)
def _no_pause(monkeypatch):
    monkeypatch.setattr(PP, "MOVED_PAUSE_S", 0, raising=False)   # raising=False: the control against the old probe


def test_a_list_that_moves_is_not_measured_and_a_single_row_too():
    churn = Feed(churn=True)
    row = _run(churn)
    assert row["skip_reason"].startswith("NOT MEASURED: the list moved") and "(asked 3 times" in row["skip_reason"]
    assert churn.calls == 4 * (1 + PP.MOVED_RETRIES) and row["result_excerpt"]["moved_retries"] == PP.MOVED_RETRIES
    one = Feed(rows=ROWS[:1])
    assert "no second page of 3" in _run(one)["skip_reason"]
    assert one.calls == 4, "a single row holds no second page at any size: it is not asked again"
    assert "no second page" in _run(Feed(rows=[]))["skip_reason"]


@pytest.mark.parametrize("n_rows", [2, 3])
def test_a_short_list_is_asked_again_at_a_page_that_fits_it(n_rows):
    """V0545: 2..PAGE rows were NOT MEASURED (no second page of 3); they are now judged at pages of len//2."""
    rows = [{"id": f"s{i}", "created_at": f"2026-10-0{i + 1}T00:00:00Z"} for i in range(n_rows)]
    f = Feed(rows=rows)
    row = _run(f)
    assert row["healthy"] is True and not row["skip_reason"], row
    ev = row["result_excerpt"]
    assert ev["page"] == 1 and ev["first_asked_at_page"] == 3 and ev["rows_in_one_page_of_2n"] == 2
    assert f.calls == 8 and f.limits == [6, 3, 3, 6, 2, 1, 1, 2], "no far read when nothing repeats"


def test_a_short_list_with_ties_is_a_bug_find_at_the_smaller_page():
    rows = [{"id": f"t{i}", "created_at": "2026-10-01T00:00:00Z"} for i in range(3)]   # one shared sort key
    hits = 0
    for seed in range(30):
        f = Feed(rows=rows, ties=True)
        f.seed = seed
        row = _run(f)
        assert not row["skip_reason"], row
        if not row["healthy"]:
            hits += 1
            fr = row["fail_reason"]
            assert (fr.startswith("BUG-FIND: pagination: two pages of 1 are not a partition of one page of 2")
                    or fr == ("BUG-FIND: pagination: the second page repeats the first: rows that share the sort key "
                              "with no unique tiebreak (§DIRFEED-2): `offset` is honored, a read far past the list "
                              "came back empty")), fr
            assert "`offset` ignored" not in fr, "an honored offset must not be called ignored"
    assert hits, "some seed must put one tied row on both pages of 1"


def test_a_repeated_page_is_told_apart_by_one_read_far_past_the_list():
    """V0545: the second page repeating the first is an ignored offset OR a tie; the far read says which, and the row
    names both when it cannot tell."""
    f = Feed(ignore_offset=True)
    row = _run(f)
    assert row["fail_reason"] == ("BUG-FIND: pagination: the second page repeats the first: `offset` ignored: a read "
                                  "far past the list returned the first page again")
    assert row["result_excerpt"]["rows_far_past_the_list"] == 3 and f.calls == 5
    short = Feed(rows=ROWS[:3], ignore_offset=True)
    row = _run(short)
    assert "`offset` ignored: a read far past the list" in row["fail_reason"] and row["result_excerpt"]["page"] == 1
    assert short.calls == 9, "four reads at 3, four at 1, one far read"
    # the far read refused: both causes named, neither claimed
    v = PP.verdict(["a", "b"], ["a", "b"], ["a"], ["a"], n=1, far=None)
    assert v[0] is False and "cannot tell which" in v[1] and "`offset` ignored, or rows" in v[1]
    # other rows far past the list (a list longer than the far offset): both named
    assert "cannot tell which" in PP.verdict(["a", "b"], ["a", "b"], ["a"], ["a"], n=1, far=["z"])[1]
    # a direct caller that never makes the far read: both named
    assert "the reads cannot tell which" in PP.verdict(["a", "b"], ["a", "b"], ["a"], ["a"], n=1)[1]


def test_a_short_list_that_moves_on_the_second_ask_or_refuses_it_is_not_measured():
    rows = [{"id": f"m{i}", "created_at": f"2026-10-0{i + 1}T00:00:00Z"} for i in range(3)]
    assert _run(Feed(rows=rows, churn=True, grow_at=8))["skip_reason"].startswith("NOT MEASURED: the list moved")
    f = Feed(rows=rows)
    inner = f.rpc

    async def refuse_late(tool, args, jwt="", timeout=30):
        if f.calls >= 5:
            f.calls += 1
            return False, {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "Error: HTTP 503"}],
                                                                 "isError": True}}, "503"
        return await inner(tool, args, jwt, timeout)
    f.rpc = refuse_late
    row = _run(f)
    assert row["skip_reason"].startswith("NOT MEASURED: 3 row(s); asked again at pages of 1, a read answered HTTP 503")


def test_a_list_that_moved_once_is_judged_on_the_next_quiet_read():
    """V0556: listAgentCards read NOT MEASURED on the 2026-10-03 nightly (the sandbox's sim registers agents); a row that
    arrived during the four reads leaves the next four quiet, and those are judged."""
    f = Feed(grow=True)
    row = _run(f)
    assert row["healthy"] is True and not row["skip_reason"], row
    assert row["result_excerpt"]["moved_retries"] == 1 and f.calls == 8


def test_a_bare_list_and_a_refusal():
    assert _run(Feed(key=None))["healthy"] is True

    async def refuse(tool, args, jwt="", timeout=30):
        return False, {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "Error: HTTP 403: no"}],
                                                             "isError": True}}, "403"
    out = {}
    asyncio.run(PP.run_paged(refuse, _parse_rpc_result, Bag(), out, (("theprotocol_getMyDisputes", "3", {}),),
                             _make_outcome, _answered))
    assert out["pagination: getMyDisputes"]["skip_reason"].startswith("NOT MEASURED: a read answered HTTP 403")


def test_a_missing_fixture_is_named_and_an_agent_tool_carries_the_agent_token():
    seen = []

    async def rec(tool, args, jwt="", timeout=30):
        seen.append(dict(args))
        return _ok({"items": []})
    out = {}

    class NoDid(Bag):
        sentinel_did = None
    asyncio.run(PP.run_paged(rec, _parse_rpc_result, NoDid(), out,
                             (("theprotocol_getMyAgentLogs", "3", {"agent_did": "${sentinel_did}"}),
                              ("theprotocol_getMyIncome", "2", {})), _make_outcome, _answered))
    assert "fixture missing" in out["pagination: getMyAgentLogs"]["skip_reason"]
    assert seen and all(a.get("agent_jwt") == "agent" for a in seen)


def test_the_audit_log_is_read_where_the_probe_writes_nothing():
    """V0545: every MCP call writes an audit row as its caller (the probe's are the admin's), so an unfiltered
    newest-first audit list moves under the probe's own reads; the system actor's rows are written by no MCP caller."""
    extra = next(e for t, _tier, e in PP.PAGED_ADMIN if t == "theprotocol_getAdminAuditLogs")
    assert extra == {"actor_type": "system", "since_hours": 720}
    seen = []

    async def rec(tool, args, jwt="", timeout=30):
        seen.append(dict(args))
        return _ok({"items": [], "count": 0})
    out = {}
    asyncio.run(PP.run_paged(rec, _parse_rpc_result, Bag(), out, (("theprotocol_getAdminAuditLogs", "admin", extra),),
                             _make_outcome, _answered))
    assert seen and all(a.get("actor_type") == "system" for a in seen), "every read carries the filter"
    assert all(a.get("since_hours") == 720 for a in seen), "every read looks back 720 hours, not the route's 24"


def test_rows_never_carry_an_id():
    row = _run(Feed(ties=True))
    blob = json.dumps(row, default=str)
    assert "r0" not in blob and "n1" not in blob


def test_rows_of_finds_the_list():
    assert PP.rows_of([{"a": 1}]) == [{"a": 1}]
    assert PP.rows_of({"agents": [{"did": "x"}], "total": 1}) == [{"did": "x"}]
    assert PP.rows_of({"whatever": [{"k": 1}], "n": 1}) == [{"k": 1}]
    assert PP.rows_of({"a": [{"k": 1}], "b": [{"k": 2}]}) is None, "two unknown lists: ambiguous"
    assert PP.rows_of({"count": 3}) is None and PP.rows_of("text") is None
    assert PP.identity({"id": 5, "did": "d"}) == "id=5" and PP.identity({"x": 1}).startswith("row=")


def test_the_census_of_paged_tools_matches_the_schemas():
    from agentvault_registry.mcp import server, server_admin
    def paged(schemas):
        return {s["name"] for s in schemas
                if {"limit", "offset"} <= set(((s.get("inputSchema") or {}).get("properties") or {}))}
    assert paged(server.ALL_TOOL_SCHEMAS) == {t for t, _, _ in PP.PAGED_PUBLIC}
    assert paged(server_admin.ADMIN_TOOL_SCHEMAS) == {t for t, _, _ in PP.PAGED_ADMIN}
    for t, tier, _ in PP.PAGED_PUBLIC:
        assert (tier == "2") == (t in server.TIER2_TOOLS), t


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
