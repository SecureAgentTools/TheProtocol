"""V0658 (v), item 6 (order gwo_5e9184020b0aa3eae72f7675; the maintainer's review, sessions' room seq 2181): a firm's
counts read only the work commissioned or delivered AS the firm, so TheProtocol Sessions read 0 jobs while its agents
held 52 and more verified jobs. The firm's own count stays; the settled Guild work its member agents did on their own
is a separate, labelled answer, never summed into the firm's.

What each test pins:
- services/track_record.member_agents_work: ONE statement for a page of organizations, compiled with the PostgreSQL
  dialect: settled local orders whose worker is an ACTIVE agent of the organization and whose payee is no organization
  (work the agent did as itself; work done as a firm is that firm's), plus those agents' VERIFIED travel credentials;
  per organization the jobs and how many of its agents did them;
- the three reads behind a firm's counts carry it as `member_work`: the Firms strip (discover_firms), this registry's
  listed organizations (#/firms) and the organization's track record; the firm's own numbers (verified_jobs,
  commissioned, settled_work, the record's verified_jobs) are the same numbers as before, never the sum;
- a member-work read that fails leaves `member_work` out (unknown is not zero) and the firm's own answer stands.

The review of 4914af776 added two rules, pinned here and on the real Postgres:
- the line counts only an affiliation this registry already states in public (services/org_mark.py, V0657 (b)): the
  organization is active and listed (`public_listing`) and the agent shows it (`agents.show_org`), on every call, so an
  unlisted organization and an agent that hides its organization add nothing, and the reads carry no `member_work` for
  an unlisted organization at all (no line rather than a false zero); the helper takes no free-form predicate;
- a verified travel credential whose signed claim names a payee firm (`payee_org_id`, or a `payee_did` that is not the
  worker) is firm work, the firm's and never the agent's own: the local rule (`payee_org_id IS NULL`) read from the claim.
And the answer is the jobs alone: the number of agents behind them is read by no surface, so it is not published.

The real-Postgres half (the same statement over seeded rows) is tests/test_firm_member_work_v0658_db.py.
RED on 553347408 (origin/v0657/cut): member_agents_work does not exist and no read carries member_work.
RED on 4914af776 (the review's two rules): the statement has neither rule, the reads attach the line to an unlisted
organization, the helper takes `org_filter` and the answer carries `agents`.
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.dialects import postgresql

ORG = "4f3c1b2a-0000-4000-8000-000000000001"
ORG2 = "4f3c1b2a-0000-4000-8000-000000000002"
SHA = "a" * 64


class _Result:
    def __init__(self, rows=(), scalar=None):
        self._rows = list(rows)
        self._scalar = scalar

    def first(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def all(self):
        return list(self._rows)

    def scalar(self):
        if self._scalar is not None:
            return self._scalar
        r = self.first()
        return (r[0] if isinstance(r, (tuple, list)) else r) if r is not None else None

    def mappings(self):
        return self


class _Db:
    """Answers by the first handler whose needle is in the statement; records every statement (as compiled for
    PostgreSQL) with its parameters."""

    def __init__(self, *handlers):
        self.handlers = list(handlers)
        self.calls = []

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt.compile(dialect=postgresql.dialect())).split()) if hasattr(stmt, "compile") \
            else " ".join(str(stmt).split())
        self.calls.append((sql, dict(params or {})))
        for needle, res in self.handlers:
            if needle in sql:
                if isinstance(res, Exception):
                    raise res
                return res(sql, dict(params or {})) if callable(res) else res
        return _Result([])


def _run(coro):
    return asyncio.run(coro)


MEMBER_NEEDLE = "FROM guild_travel_credentials"


def _member_rows(*rows):
    return _Result([{"org_id": o, "jobs": j} for o, j in rows])


# ── the statement ──────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_statement_counts_only_the_member_agents_own_settled_work():
    from agentvault_registry.services import track_record as tr
    db = _Db((MEMBER_NEEDLE, _member_rows((ORG, 68))))
    out = _run(tr.member_agents_work(db, [ORG, ORG2, ORG, None, ""]))
    assert out == {ORG: {"jobs": 68}}, "one entry per organization that has any; none is invented; the jobs alone"
    assert len(db.calls) == 1, "one statement for the whole page"
    sql, params = db.calls[0]
    assert sorted(params["ids"]) == sorted([ORG, ORG2]), "each organization asked once, empty ids dropped"
    low = sql.lower()
    # the members: the organization's ACTIVE agents
    assert "from agents" in low and "organization_id in" in low and "status = 'active'" in low
    # their own settled work here: settled, and paid to no organization (work done as a firm is that firm's)
    assert "from guild_work_orders" in low and "status = 'settled'" in low
    assert "payee_org_id is null" in low
    # and the work they did on other registries, as their verified travel credentials
    assert "from guild_travel_credentials" in low and "verified" in low
    # counted per organization
    assert "group by" in low and "count(" in low


def _members_cte(sql: str) -> str:
    low = sql.lower()
    return low[low.index("with members as"):low.index("own_work as")]


def _travel_branch(sql: str) -> str:
    low = sql.lower()
    return low[low.index("from guild_travel_credentials"):]


def test_only_an_affiliation_the_registry_states_in_public_is_counted():
    """org_mark's rule (V0657 (b), privacy first) on EVERY call: the organization active and listed, the agent showing
    it. An agent that hides its organization, or the agents of an unlisted one, add nothing: their own job counts are
    public on their cards, so a line that counted them would tie them to an organization they never named in public."""
    from agentvault_registry.services import track_record as tr
    from agentvault_registry.services.org_policy import sql_listed_public
    db = _Db((MEMBER_NEEDLE, _member_rows()))
    _run(tr.member_agents_work(db, [ORG]))
    members = _members_cte(db.calls[0][0])
    for clause in ("a.show_org = true", "o.is_active = true", sql_listed_public("o").lower()):
        assert clause in members, f"the members are read under {clause!r}"


def test_the_helper_takes_no_free_form_predicate():
    """A caller cannot widen or narrow the rule: there is no string to interpolate (the rule lives in the statement)."""
    import inspect
    from agentvault_registry.services import track_record as tr
    params = inspect.signature(tr.member_agents_work).parameters
    assert list(params) == ["db", "org_ids"], list(params)


def test_a_travel_credential_signed_for_a_firm_is_the_firms_not_the_agents_own():
    """The host signs the payee into the work credential (services/guild_reputation.issue_work_credential): work an agent
    did AS a firm through the firm-remote bid names `payee_org_id` and the firm's treasury as `payee_did`. That is the
    firm's work; only a claim that names no payee firm (or predates the payee fields) is the agent's own."""
    from agentvault_registry.services import track_record as tr
    db = _Db((MEMBER_NEEDLE, _member_rows()))
    _run(tr.member_agents_work(db, [ORG]))
    travel = _travel_branch(db.calls[0][0])
    assert "c.verified" in travel
    assert "coalesce(c.bundle->>'payee_org_id', '') = ''" in travel, "a claim naming a payee firm is not counted"
    assert "coalesce(c.bundle->>'payee_did', c.worker_did) = c.worker_did" in travel, \
        "nor a claim paying someone other than the worker"


def test_no_organization_asks_nothing():
    from agentvault_registry.services import track_record as tr
    db = _Db()
    assert _run(tr.member_agents_work(db, [])) == {}
    assert _run(tr.member_agents_work(db, [None, ""])) == {}
    assert db.calls == []


# ── the Firms strip in Discovery ───────────────────────────────────────────────────────────────────────────────────
ORG3 = "4f3c1b2a-0000-4000-8000-000000000003"
LISTED = {"public_transparency_opt_in": True, "public_listing": True}
UNLISTED = {"public_transparency_opt_in": True}


def _firm_row(org=ORG, worker_jobs=0, commissioned=0, settings=None):
    return {"id": org, "name": "TheProtocol Sessions", "slug": "theprotocol-sessions", "description": "d",
            "website": None, "settings": dict(LISTED if settings is None else settings), "created_at": None,
            "worker_jobs": worker_jobs, "commissioned": commissioned, "last_settled": None}


def test_the_firms_strip_carries_the_agents_own_work_apart_from_the_firms_count():
    from agentvault_registry.routers import organizations as r
    db = _Db(("WITH worker AS", _Result([_firm_row(), _firm_row(ORG2, worker_jobs=4, commissioned=1)])),
             (MEMBER_NEEDLE, _member_rows((ORG, 68))))
    out = _run(r.discover_firms(limit=12, db=db))
    first, second = out["firms"]
    assert (first["verified_jobs"], first["commissioned"]) == (0, 0), "the firm's own count is the firm's own"
    assert first["member_work"] == {"jobs": 68}
    assert (second["verified_jobs"], second["commissioned"]) == (4, 1)
    assert second["member_work"] == {"jobs": 0}, "an answered read with nothing is an honest zero"
    member_calls = [c for c in db.calls if MEMBER_NEEDLE in c[0]]
    assert len(member_calls) == 1 and sorted(member_calls[0][1]["ids"]) == sorted([ORG, ORG2])


def test_an_unlisted_firm_in_the_strip_carries_no_line_and_is_not_asked_for():
    """The strip also lists firms that are not listed (open books, an intake agent, settled work as the firm). The
    registry does not state their members in public, so the line is absent there: no line, never a false zero."""
    from agentvault_registry.routers import organizations as r
    db = _Db(("WITH worker AS", _Result([_firm_row(), _firm_row(ORG3, worker_jobs=2, settings=UNLISTED)])),
             (MEMBER_NEEDLE, _member_rows((ORG, 68), (ORG3, 3))))
    out = _run(r.discover_firms(limit=12, db=db))
    listed, unlisted = out["firms"]
    assert listed["listed"] is True and listed["member_work"] == {"jobs": 68}
    assert unlisted["listed"] is False and unlisted["verified_jobs"] == 2
    assert "member_work" not in unlisted, "an unlisted firm's members are not stated in public"
    member_calls = [c for c in db.calls if MEMBER_NEEDLE in c[0]]
    assert len(member_calls) == 1 and member_calls[0][1]["ids"] == [ORG], "only the listed firms are asked for"


def test_a_strip_of_unlisted_firms_asks_nothing():
    from agentvault_registry.routers import organizations as r
    db = _Db(("WITH worker AS", _Result([_firm_row(settings=UNLISTED), _firm_row(ORG2, settings={})])),
             (MEMBER_NEEDLE, _member_rows((ORG, 68))))
    out = _run(r.discover_firms(limit=12, db=db))
    assert all("member_work" not in f for f in out["firms"])
    assert not [c for c in db.calls if MEMBER_NEEDLE in c[0]]


def test_a_failed_member_read_leaves_the_line_out_and_the_firm_stands():
    from agentvault_registry.routers import organizations as r
    db = _Db(("WITH worker AS", _Result([_firm_row(worker_jobs=2)])),
             (MEMBER_NEEDLE, RuntimeError("relation guild_travel_credentials does not exist")))
    out = _run(r.discover_firms(limit=12, db=db))
    firm = out["firms"][0]
    assert firm["verified_jobs"] == 2 and firm["listed"] is True
    assert "member_work" not in firm, "unknown is not zero: no line rather than a false 0"


# ── this registry's listed organizations (#/firms) ─────────────────────────────────────────────────────────────────
def test_the_listed_organizations_carry_the_agents_own_work_beside_the_firms(monkeypatch):
    from agentvault_registry.routers import organizations as r
    monkeypatch.setattr("agentvault_registry.core.public_url.public_ui_origin", lambda: "https://eu.example")
    monkeypatch.setattr("agentvault_registry.core.public_url.public_ui_url_static", lambda: "https://eu.example/ui")
    rows = [(ORG, "sessions", "Sessions", "d", None, SHA, None, 1, 6, 0),
            (ORG2, "reach", "Reach Limited", "d", None, None, None, 1, 2, 5)]
    db = _Db(("SELECT count(*) FROM organizations o", _Result(scalar=2)), ("ORDER BY lower(o.name)", _Result(rows)),
             (MEMBER_NEEDLE, _member_rows((ORG, 52))))
    out = _run(r.list_listed_organizations(limit=200, offset=0, db=db))
    sessions, reach = out["organizations"]
    assert sessions["settled_work"] == 0 and sessions["member_work"] == {"jobs": 52}
    assert reach["settled_work"] == 5 and reach["member_work"] == {"jobs": 0}
    member_sql = [c[0] for c in db.calls if MEMBER_NEEDLE in c[0]]
    assert len(member_sql) == 1
    assert "((o.settings->'public_listing')::text = 'true')" in member_sql[0], \
        "the public list counts only for organizations it may name: the listing test rides the statement too"


# ── the organization's track record ────────────────────────────────────────────────────────────────────────────────
# the organization's own row (the member statement reads `FROM agents a JOIN organizations o`, never this)
ORG_ROW_NEEDLE = "FROM organizations"


def _org_row(listed=True, active=True):
    # (id, name, slug, is_active, listed): `listed` is the statement's own answer (active AND public_listing)
    return _Result([(ORG, "Sessions", "sessions", active, bool(listed and active))])


def test_the_track_record_reads_the_listing_with_the_organization(monkeypatch):
    from agentvault_registry.routers import organizations as r
    from agentvault_registry.services import track_record as tr
    from agentvault_registry.services.org_policy import sql_listed_public

    async def firm_record(db, org_id):
        return {"verified_jobs": 0}
    monkeypatch.setattr(tr, "org_track_record", firm_record)
    db = _Db((ORG_ROW_NEEDLE, _org_row()), (MEMBER_NEEDLE, _member_rows()))
    _run(r.get_org_track_record(ORG, db=db))
    org_sql = next(c[0] for c in db.calls if ORG_ROW_NEEDLE in c[0])
    assert sql_listed_public("o") in org_sql and "o.is_active" in org_sql, \
        "the organization's row carries whether the registry states its members in public"


def test_the_track_record_carries_the_agents_own_work_and_keeps_the_firms(monkeypatch):
    from agentvault_registry.routers import organizations as r
    from agentvault_registry.services import track_record as tr

    async def firm_record(db, org_id):
        return {"verified_jobs": 0, "workers": 0, "commissioned": {"orders": 0}}
    monkeypatch.setattr(tr, "org_track_record", firm_record)
    db = _Db((ORG_ROW_NEEDLE, _org_row()), (MEMBER_NEEDLE, _member_rows((ORG, 52))))
    out = _run(r.get_org_track_record(ORG, db=db))
    assert out["verified_jobs"] == 0, "the firm's own record is unchanged"
    assert out["member_work"] == {"jobs": 52}
    assert (out["name"], out["slug"], out["is_active"]) == ("Sessions", "sessions", True)


def test_a_listed_organization_whose_agents_have_none_reads_an_honest_zero(monkeypatch):
    from agentvault_registry.routers import organizations as r
    from agentvault_registry.services import track_record as tr

    async def firm_record(db, org_id):
        return {"verified_jobs": 1}
    monkeypatch.setattr(tr, "org_track_record", firm_record)
    out = _run(r.get_org_track_record(ORG, db=_Db((ORG_ROW_NEEDLE, _org_row()), (MEMBER_NEEDLE, _member_rows()))))
    assert out["member_work"] == {"jobs": 0}


@pytest.mark.parametrize("listed,active", [(False, True), (True, False)])
def test_an_unlisted_or_closed_organization_carries_no_line_and_is_not_asked_for(monkeypatch, listed, active):
    from agentvault_registry.routers import organizations as r
    from agentvault_registry.services import track_record as tr

    async def firm_record(db, org_id):
        return {"verified_jobs": 3}
    monkeypatch.setattr(tr, "org_track_record", firm_record)
    db = _Db((ORG_ROW_NEEDLE, _org_row(listed=listed, active=active)), (MEMBER_NEEDLE, _member_rows((ORG, 9))))
    out = _run(r.get_org_track_record(ORG, db=db))
    assert out["verified_jobs"] == 3, "the firm's own record stands"
    assert "member_work" not in out, "its members are not stated in public: no line, never a false zero"
    assert not [c for c in db.calls if MEMBER_NEEDLE in c[0]]


def test_a_failed_member_read_leaves_the_track_record_whole(monkeypatch):
    from agentvault_registry.routers import organizations as r
    from agentvault_registry.services import track_record as tr

    async def firm_record(db, org_id):
        return {"verified_jobs": 3}
    monkeypatch.setattr(tr, "org_track_record", firm_record)
    db = _Db((ORG_ROW_NEEDLE, _org_row()), (MEMBER_NEEDLE, RuntimeError("boom")))
    out = _run(r.get_org_track_record(ORG, db=db))
    assert out["verified_jobs"] == 3 and "member_work" not in out


def test_an_unknown_organization_is_a_404():
    from fastapi import HTTPException
    from agentvault_registry.routers import organizations as r
    with pytest.raises(HTTPException) as e:
        _run(r.get_org_track_record(ORG, db=_Db((ORG_ROW_NEEDLE, _Result([])))))
    assert e.value.status_code == 404


@pytest.mark.parametrize("name", ["discover_firms", "list_listed_organizations", "get_org_track_record"])
def test_every_read_asks_the_one_helper(name):
    """One answer for every surface that shows a firm's counts: the reads call the shared helper, never a copy of it."""
    import inspect
    from agentvault_registry.routers import organizations as r
    src = inspect.getsource(getattr(r, name))
    assert "member_agents_work(" in src
    assert "guild_travel_credentials" not in src, "the statement lives in services/track_record.py only"
