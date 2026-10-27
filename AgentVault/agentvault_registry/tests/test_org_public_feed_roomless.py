"""The public firms list and each firm's feed serve one population.

GET /organizations/public/transparent lists every active organization that opted into
transparency and LEFT JOINs its room: a room is off until the org wants one (§OURSTATE-6),
so a firm can be on the list before its room exists. Its feed answered 404 "No public feed"
then: a dead link on the list, and "read failed" on /firms for a firm that has simply
published nothing yet (the MCP tester's list/detail lifecycle found it on sbx-alpha,
2026-10-18). The feed now answers 200 with no records for that firm. A firm that did not opt
in, an inactive one and an unknown id still answer 404.
"""
import asyncio
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from agentvault_registry.routers import organizations as orgs


class _Result:
    def __init__(self, first=None, rows=()):
        self._first = first
        self._rows = list(rows)

    def first(self):
        return self._first

    def fetchall(self):
        return self._rows


class _Db:
    """Answers the feed's reads by the table each statement names, and records them."""

    def __init__(self, org_row, room_row=None, messages=()):
        self.org_row = org_row
        self.room_row = room_row
        self.messages = messages
        self.statements = []

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.statements.append(sql)
        if "FROM organizations" in sql:
            return _Result(first=self.org_row)
        if "FROM conversations" in sql:
            return _Result(first=self.room_row)
        if "FROM chat_messages" in sql:
            return _Result(rows=self.messages)
        raise AssertionError(f"unexpected statement: {sql}")


_OPTED_IN = {"public_transparency_opt_in": True}


def _org(active=True, settings=_OPTED_IN):
    return ("org-1", "Roomless Works", "roomless-works", active, settings)


def _feed(db):
    return asyncio.run(orgs.get_org_public_feed(org_id="org-1", before_seq=None, limit=50, db=db))


def test_an_opted_in_firm_without_a_room_answers_no_records_not_404():
    db = _Db(_org(), room_row=None)
    out = _feed(db)
    assert out == {
        "org_id": "org-1", "name": "Roomless Works", "slug": "roomless-works",
        "topic": None, "transparency": "records-only",
        "records": [], "next_before_seq": None,
    }
    # Nothing is read from a room that does not exist.
    assert not any("FROM chat_messages" in s for s in db.statements)


def test_control_a_firm_with_a_room_still_serves_its_records():
    at = datetime(2026, 10, 18, 21, 0, tzinfo=timezone.utc)
    db = _Db(_org(), room_row=("conv-1", "Weekly ledger", 7),
             messages=[(7, "system", "room.topic", None, at)])
    out = _feed(db)
    assert out["topic"] == "Weekly ledger"
    assert out["records"] == [{"seq": 7, "kind": "system", "at": at.isoformat(), "body": "room.topic"}]
    assert out["next_before_seq"] is None


@pytest.mark.parametrize("org_row", [
    None,                                                   # no such organization
    _org(active=False),                                     # deactivated
    _org(settings={}),                                      # never opted in
    _org(settings={"public_transparency_opt_in": False}),   # opted out
    _org(settings={"public_transparency_opt_in": "true"}),  # not the boolean the settings rail writes
])
def test_everyone_the_list_cannot_show_still_answers_404(org_row):
    db = _Db(org_row, room_row=None)
    with pytest.raises(HTTPException) as e:
        _feed(db)
    assert e.value.status_code == 404
    assert e.value.detail == "No public feed"


def test_the_list_asks_the_feeds_opt_in_question():
    # The list is SQL, the feed asks org_policy.transparency_public (`is True`). `->>` would
    # also admit the string "true", a firm the list shows and the feed refuses; the cast keeps
    # the JSON form, so only the boolean matches (read on sbx-alpha's json column, 2026-10-18).
    db = _Db(org_row=None)

    async def execute(stmt, params=None):
        db.statements.append(str(stmt))
        return _Result(rows=[("org-1", "Roomless Works", "roomless-works", None, None, None)])

    db.execute = execute
    out = asyncio.run(orgs.list_transparent_organizations(limit=25, db=db))
    assert [o["org_id"] for o in out["organizations"]] == ["org-1"]
    (sql,) = db.statements
    assert "(o.settings->'public_transparency_opt_in')::text = 'true'" in sql
    assert "->>'public_transparency_opt_in'" not in sql
    assert "LEFT JOIN conversations" in sql   # a firm without a room stays on the list
