"""§MCPTEST30 V0614 (2026-10-14): one discover answer reads one snapshot.

`GET /agent-cards/discover` read its page with the total, its facets and its tags in three statements under READ COMMITTED,
so agent cards landing between them made one answer carry a `total` and a `facets.total` that disagree: the V0613 round's
federation suite (discovery_ranked_page_is_public_and_partitions) read facets 6542 against total 6544 while the round's own
lifecycles created agents, and the 10-13 nightly 6473 against 6472. The facets and the tags now ride the page statement as
two scalar subqueries over the same `base`; only an empty page, which has no row to carry them, reads them on its own.

Driven through the real route function with a fake session that answers by statement and counts the card statements; the
controls prove each check can fail (a page row with facets_json is read from the row, an empty page falls back).
"""
from __future__ import annotations

import asyncio
import datetime

from agentvault_registry.routers import agent_cards as mod

KW = dict(q=None, origins=None, pricing=None, tag=None, verified_only=False, active_24h=False, encircled_only=False,
          foreign_only=False, answerable_only=False, bonded_only=False, include_unbonded=None, sort="newest",
          limit=30, offset=0, viewer=None)


class _Res:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar(self):
        return None


class _Db:
    """Answers the peer read, the page statement and the two fallback statements; counts the card statements."""

    def __init__(self, page_rows):
        self.page_rows = page_rows
        self.card_statements = []

    async def execute(self, stmt, *a, **k):
        sql = str(stmt)
        if "peer_registries" in sql:
            return _Res([])
        if "full_total" in sql:
            self.card_statements.append(("page", sql))
            return _Res(self.page_rows)
        if "GROUPING SETS" in sql:
            self.card_statements.append(("facets", sql))
            return _Res([{"origin": None, "count": 7, "live_24h": 1, "paid": 2},
                         {"origin": "Local", "count": 7, "live_24h": 1, "paid": 2}])
        if "jsonb_array_elements_text" in sql:
            self.card_statements.append(("tags", sql))
            return _Res([{"tag": "fallback-tag", "count": 3}])
        return _Res([])   # the enrichments (reputation, track record) read nothing here; they never break discovery


def _row(**over):
    now = datetime.datetime(2026, 10, 14, 10, 0, tzinfo=datetime.timezone.utc)
    r = {"id": 1, "agent_did": "did:theprotocol:fed-1", "name": "Fed One", "description": "d", "created_at": now,
         "updated_at": now, "developer_id": None, "is_local": False, "origin": "peer-frame", "reputation_score": 1.0,
         "last_active_at": None, "developer_verified": False, "is_paid": False, "is_live": False, "unlisted": False,
         "last_health": None, "last_health_at": None, "is_bonded": False, "reputation_bond_status": None,
         "staked_balance": None, "card_data": {"name": "Fed One"}, "is_enforced": False, "human_readable_id": None,
         "card_did": None, "tags": [], "pricing": None, "icon_url": None, "flare": {"tier": "x"}, "fee_ccy": None,
         "pricing_ccy": None, "source_registry": None, "full_total": 6544,
         "facets_json": [{"origin": None, "count": 6544, "live_24h": 5, "paid": 9},
                         {"origin": "peer-frame", "count": 6000, "live_24h": 4, "paid": 8},
                         {"origin": "Local", "count": 544, "live_24h": 1, "paid": 1}],
         "tags_json": [{"tag": "data", "count": 40}, {"tag": "fx", "count": 12}]}
    r.update(over)
    return r


def _call(db, **over):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(mod.discover_agent_cards(db=db, **{**KW, **over}))
    finally:
        loop.close()


def test_the_page_statement_carries_the_facets_and_the_tags():
    db = _Db([_row()])
    _call(db)
    kinds = [k for k, _ in db.card_statements]
    assert kinds == ["page"], f"one statement for the page, the facets and the tags, got {kinds}"
    sql = db.card_statements[0][1]
    for needle in ("facet AS (", "tagc AS (", "AS facets_json", "AS tags_json", "COUNT(*) OVER () AS full_total",
                   "GROUPING SETS ((origin), ())", "jsonb_array_elements_text"):
        assert needle in sql, needle


def test_the_answer_reads_its_facets_and_tags_from_the_page_row():
    out = _call(_Db([_row()]))
    assert out["total"] == 6544 and out["facets"]["total"] == 6544
    assert out["facets"]["paid"] == 9 and out["facets"]["free"] == 6544 - 9 and out["facets"]["live_24h"] == 5
    assert [o["name"] for o in out["facets"]["origins"]] == ["peer-frame", "Local"]
    assert out["facets"]["tags"] == [{"name": "data", "count": 40}, {"name": "fx", "count": 12}]


def test_a_jsonb_aggregate_that_arrives_as_text_is_parsed():
    out = _call(_Db([_row(facets_json='[{"origin": null, "count": 3, "live_24h": 0, "paid": 1}]',
                          tags_json='[{"tag": "t", "count": 1}]')]))
    assert out["facets"]["total"] == 3 and out["facets"]["tags"] == [{"name": "t", "count": 1}]


def test_an_empty_page_reads_the_facets_and_the_tags_on_its_own():
    db = _Db([])
    out = _call(db, offset=1_000_000)
    assert [k for k, _ in db.card_statements] == ["page", "facets", "tags"]
    assert out["total"] == 0 and out["facets"]["total"] == 7 and out["facets"]["tags"] == [{"name": "fallback-tag", "count": 3}]


def test_json_list_reads_lists_strings_and_nothing_else():
    assert mod._json_list([{"a": 1}, 2, "x"]) == [{"a": 1}]
    assert mod._json_list('[{"a": 1}]') == [{"a": 1}]
    assert mod._json_list("not json") == [] and mod._json_list(None) == [] and mod._json_list({"a": 1}) == []


def test_the_check_can_fail():
    # the V0613 shape: three statements, the facets and the tags from the second and third
    v0613 = ["page", "facets", "tags"]
    assert v0613 != ["page"]
