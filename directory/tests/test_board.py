"""§MEMBERSHIP phase C (2026-10-02): the registry board's two reads, each with its own state, and what the index keeps.

A board that printed "0 members" for a registry that does not serve the figure, or "commons off" because a gateway said
403, would print a sentence it never observed. These tests pin the states, that a failed read keeps the last figures
(silence is not a deletion), that the registry's own "absent" / "switched off" clears them, and the GraphQL shape.
"""
import asyncio
import json
import os
import tempfile

from directory import board as b
from directory.schema import schema
from directory.store import Store


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class _Client:
    """Answers by URL; an Exception value is raised as a transport failure."""
    def __init__(self, answers):
        self.answers, self.asked = answers, []

    async def get(self, url):
        self.asked.append(url)
        a = self.answers[url]
        if isinstance(a, Exception):
            raise a
        return _Resp(*a)


BASE = "https://r.example"
M = BASE + b.MEMBERSHIP_STATS
C = BASE + b.COMMONS_SEASONS
STATS = {"mode": "member", "members": 7, "joined_30d": 2, "left_30d": 1, "network_points": 911, "min_bond_age_days": 30,
         "tenure_full_days": 365, "max_weight": 2.0, "presence_mode": "conditional", "as_of": "2026-10-02T14:00:00+00:00"}
SEASON = {"id": 4, "title": "October", "status": "open", "currency": "SBXA", "budget": "100.000000", "paid_total": "0",
          "submissions": 3, "ballots": 2, "opens_at": "2026-10-02T10:00:00+00:00", "ends_at": "2026-11-01T10:00:00+00:00",
          "rules": {"ballot_points": 100}}


def run(coro):
    return asyncio.run(coro)


def test_membership_states():
    ok = run(b.read_membership(_Client({M: (200, STATS)}), BASE))
    assert ok["state"] == "ok" and ok["figures"]["members"] == 7 and ok["figures"]["mode"] == "member"
    assert "network_points" not in ok["figures"], "the board keeps counts and rules, nothing it does not show"
    assert run(b.read_membership(_Client({M: (404, {"detail": "Not Found"})}), BASE))["state"] == "absent"
    for answer, error in (((502, None), "http 502"), (ConnectionError("refused"), "ConnectionError: refused"),
                          ((200, ValueError("html")), "http 200 without a stats document"),
                          ((200, {"members": "many"}), "http 200 without a stats document")):
        got = run(b.read_membership(_Client({M: answer}), BASE))
        assert got == {"state": "unreadable", "figures": None, "error": error}, (answer, got)


def test_commons_states_and_only_the_registrys_own_refusal_reads_switched_off():
    seasons = [SEASON, {**SEASON, "id": 3, "status": "paid"}, {"title": "no id"}, {**SEASON, "id": 2}, {**SEASON, "id": 1}]
    ok = run(b.read_commons(_Client({C: (200, {"seasons": seasons, "currency": "SBXA"})}), BASE))
    # the newest three rows are read; a row without an id is dropped, never back-filled from further down
    assert ok["state"] == "ok" and [s["id"] for s in ok["figures"]["seasons"]] == [4, 3], ok
    assert "rules" not in ok["figures"]["seasons"][0] and ok["figures"]["seasons"][0]["submissions"] == 3
    off = run(b.read_commons(_Client({C: (403, {"error": "commons_disabled", "message": "..."})}), BASE))
    assert off["state"] == "switched_off"
    gateway = run(b.read_commons(_Client({C: (403, {"detail": "Forbidden"})}), BASE))
    assert gateway == {"state": "unreadable", "figures": None, "error": "http 403"}, "a gateway's 403 is not the registry's word"
    assert run(b.read_commons(_Client({C: (404, None)}), BASE))["state"] == "absent"
    assert run(b.read_commons(_Client({C: (200, {"items": []})}), BASE))["error"] == "http 200 without a seasons document"



def test_cancelled_seasons_are_counted_not_shown():
    """A cancelled season never paid anything (a cancel is refused once any award was sent). A test runner that opens and
    cancels one per run must not push a registry's real seasons off the board: the newest three NOT cancelled are kept from
    a window of twenty, and the cancelled ones in that window are counted."""
    assert b.COMMONS_SEASONS.endswith("limit=20")
    rows = [{**SEASON, "id": 9, "status": "cancelled"}, {**SEASON, "id": 8, "status": "cancelled"}, {**SEASON, "id": 7},
            {**SEASON, "id": 6, "status": "cancelled"}, {**SEASON, "id": 5, "status": "paid"},
            {**SEASON, "id": 4, "status": "closed"}, {**SEASON, "id": 3, "status": "paid"}]
    got = run(b.read_commons(_Client({C: (200, {"seasons": rows, "currency": "SBXA"})}), BASE))
    assert [s["id"] for s in got["figures"]["seasons"]] == [7, 5, 4] and got["figures"]["cancelled_recent"] == 3, got
    none = run(b.read_commons(_Client({C: (200, {"seasons": [{**SEASON, "status": "cancelled"}], "currency": "SBXA"})}), BASE))
    assert none["state"] == "ok" and none["figures"]["seasons"] == [] and none["figures"]["cancelled_recent"] == 1
    store = _store()
    b._record(store, "sbx-alpha", "commons", got, 1.0)
    q = "{ registries { commons { seasons { id } cancelledRecent } } }"
    r = schema.execute_sync(q, context_value={"store": store})
    assert r.errors is None, r.errors
    assert r.data["registries"][0]["commons"] == {"seasons": [{"id": 7}, {"id": 5}, {"id": 4}], "cancelledRecent": 3}


def _store():
    d = tempfile.mkdtemp()
    s = Store(os.path.join(d, "dir.sqlite"))
    s.upsert_registry(name="sbx-alpha", trust_domain="sbx-alpha", tier="frame", public_url=BASE, verified=1, reachable=1,
                      agents_indexed=0)
    return s


def _query(store):
    q = "{ registries { name membership { state members mode readAt error } " \
        "commons { state currency seasons { id status budget submissions } readAt error } } }"
    r = schema.execute_sync(q, context_value={"store": store})
    assert r.errors is None, r.errors
    return r.data["registries"][0]


def test_a_failed_read_keeps_the_last_figures_and_says_so():
    store = _store()
    reg = {"name": "sbx-alpha", "base": BASE}
    assert _query(store)["membership"] is None, "never checked: null, not zero"

    out = run(b.pull_board(_Client({M: (200, STATS), C: (200, {"seasons": [SEASON], "currency": "SBXA"})}), store, reg))
    assert out == {"membership": "ok", "commons": "ok", "errors": []}
    first = _query(store)
    assert first["membership"]["members"] == 7 and first["membership"]["state"] == "ok" and first["membership"]["error"] is None
    assert first["commons"]["seasons"][0]["budget"] == "100.000000"

    run(b.pull_board(_Client({M: (502, None), C: ConnectionError("down")}), store, reg))
    stale = _query(store)
    assert stale["membership"]["state"] == "unreadable" and stale["membership"]["members"] == 7, "silence is not a deletion"
    assert stale["membership"]["readAt"] == first["membership"]["readAt"], "and it says how old the figures are"
    assert stale["membership"]["error"] == "http 502" and stale["commons"]["error"].startswith("ConnectionError")

    run(b.pull_board(_Client({M: (404, None), C: (403, {"error": "commons_disabled"})}), store, reg))
    said = _query(store)
    assert said["membership"] == {"state": "absent", "members": None, "mode": None, "readAt": first["membership"]["readAt"],
                                  "error": None}
    assert said["commons"]["state"] == "switched_off" and said["commons"]["seasons"] == []


def test_the_board_columns_migrate_onto_an_older_index():
    d = tempfile.mkdtemp()
    path = os.path.join(d, "old.sqlite")
    import sqlite3
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE registries (name TEXT PRIMARY KEY, trust_domain TEXT, tier TEXT, public_url TEXT, "
              "did_namespace TEXT, verified INTEGER NOT NULL DEFAULT 0, reason TEXT, reachable INTEGER NOT NULL DEFAULT 0, "
              "card_epoch TEXT, location TEXT, latitude REAL, longitude REAL, parent_name TEXT, federation_status TEXT, "
              "hop INTEGER, last_sync_at REAL, last_error TEXT, agents_indexed INTEGER NOT NULL DEFAULT 0, card_json TEXT)")
    c.execute("INSERT INTO registries (name) VALUES ('old')")
    c.commit()
    c.close()
    store = Store(path)
    row = store.get_registry("old")
    assert {"membership_state", "commons_json", "commons_checked_at"} <= set(row), sorted(row)
    assert b.row_figures(row, "membership") is None


def test_the_schema_names_no_member():
    sdl = schema.as_str()
    for field in ("membership: MembershipFigures", "commons: CommonsFigures", "joined30d: Int", "seasons: [CommonsSeasonFigures!]!"):
        assert field in sdl, field
    figures = sdl[sdl.index("type MembershipFigures"):]
    figures = figures[:figures.index("}")]
    for word in ("did", "voter", "developer", "name:"):
        assert word not in figures.lower(), f"the board's membership figures carry no {word!r}"
    assert json.dumps(STATS)  # the fixture is plain JSON, as a registry answers
