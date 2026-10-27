"""§MEMBERSHIP (V0551): the commons season lifecycle opens a season of its own, walks it, and always cancels it.

Driven against a fake target through the real _exec_step: where the commons is on and no season is live, every
commons tool gets a row from the walk (open, read, submit, the member's view, the ballot and the two payment steps held
to their refusals, strike, close, cancel) and the admin rows land where the admin sweep reads them. Where the commons
is off only the first read runs (held to commons_disabled); where someone else's season is live nothing is opened and
the steps that need a season are NOT MEASURED, named; and a season this run opened is cancelled even when a step in
between fails, because the one live-season slot is shared.
"""
from __future__ import annotations

import asyncio
import types
from datetime import datetime, timedelta, timezone

from agentvault_registry.api_tests.contracts import mcp_lifecycles as L
from agentvault_registry.api_tests.contracts import mcp_switches as M

OFF_TEXT = ("Error: HTTP 403: commons_disabled: The commons is not enabled on this registry (COMMONS_ENABLED=false). "
            "Seasons, submissions and ballots open where it is.")


def _fake_rpc(answers, seen):
    async def rpc(tool, args, jwt="", timeout=15):
        seen.append((tool, dict(args)))
        ans = answers[tool]
        if callable(ans):
            ans = ans(args)
        code, payload = ans
        if 200 <= int(code) < 300:
            return True, {"result": payload}, str(code)
        return False, {"result": {"_text": payload}}, str(code)
    return rpc


def _parse(body):
    return (body or {}).get("result") or {}


def _answers(**over):
    a = {
        "theprotocol_getCommonsSeasons": (200, {"seasons": [{"id": 3, "status": "cancelled"}], "currency": "SBXA"}),
        "theprotocol_adminCommonsOpenSeason": (201, {"id": 4, "status": "open", "budget": "1.000000"}),
        "theprotocol_getCommonsSeason": lambda args: (200, {"id": 4, "status": _STATE["status"], "budget": "1.000000"}),
        "theprotocol_submitCommonsWork": (201, {"id": 9, "season_id": 4, "status": "submitted"}),
        "theprotocol_getMyCommonsSeason": (200, {"season_id": 4, "my_submissions": [{"id": 9}], "is_member": True}),
        "theprotocol_castCommonsBallot": (422, "Error: HTTP 422: own_submission: a member never gives points to their "
                                               "own developer's work: 9."),
        "theprotocol_adminCommonsPaySeason": (409, "Error: HTTP 409: season_not_closed: season 4 is open; close it "
                                                   "first so the tally is fixed."),
        "theprotocol_adminCommonsWriteOffAward": (409, "Error: HTTP 409: season_not_closed: season 4 is open."),
        "theprotocol_adminCommonsStrikeSubmission": (200, {"id": 9, "status": "struck"}),
        "theprotocol_adminCommonsCloseSeason": lambda args: _set("closed", 200, {"id": 4, "status": "closed"}),
        "theprotocol_adminCommonsCancelSeason": lambda args: (
            _set("cancelled", 200, {"id": 4, "status": "cancelled"}) if args["season_id"] == 4
            else (200, {"id": args["season_id"], "status": "cancelled"})),
    }
    a.update(over)
    return a


_STATE = {"status": "open"}


def _set(status, code, body):
    _STATE["status"] = status
    return code, body


def _run(answers, config=None):
    _STATE["status"] = "open"
    seen, outcomes = [], {}
    bag = types.SimpleNamespace(developer_jwt="dev", sentinel_jwt="sentinel", rpc_admin=_fake_rpc(answers, seen),
                                admin_lifecycle_rows={}, event_verifier=None, flow_values={})

    async def go():
        M.use_target(config if config is not None else {"commons_enabled": True})
        await L.lifecycle_commons_season(_fake_rpc(answers, seen), _parse, bag, outcomes)
    asyncio.run(go())
    return seen, outcomes, bag.admin_lifecycle_rows


def test_an_open_commons_walks_its_own_season_and_cancels_it():
    seen, rows, admin = _run(_answers())
    assert [t for t, _ in seen] == [
        "theprotocol_getCommonsSeasons", "theprotocol_adminCommonsOpenSeason", "theprotocol_getCommonsSeason",
        "theprotocol_submitCommonsWork", "theprotocol_getMyCommonsSeason", "theprotocol_castCommonsBallot",
        "theprotocol_adminCommonsPaySeason", "theprotocol_adminCommonsWriteOffAward",
        "theprotocol_adminCommonsStrikeSubmission", "theprotocol_adminCommonsCloseSeason",
        "theprotocol_adminCommonsCancelSeason", "theprotocol_getCommonsSeason"]
    tools = {k: v for k, v in rows.items() if k.startswith("theprotocol_")}
    assert set(tools) == {"theprotocol_getCommonsSeasons", "theprotocol_getCommonsSeason",
                          "theprotocol_submitCommonsWork", "theprotocol_getMyCommonsSeason",
                          "theprotocol_castCommonsBallot"}
    # §MCPTEST30 (V0636): the ballot's own row is the member's ballot for another developer's work, which this bag
    # cannot make (it mints no second developer): NOT MEASURED, named. The own-submission refusal is a refusal row.
    ballot = tools.pop("theprotocol_castCommonsBallot")
    assert not ballot["healthy"] and "no mint_throwaway" in ballot["skip_reason"], ballot
    own = rows["refusal: castCommonsBallot a ballot for its own developer's submission"]
    assert own["healthy"] and own["status_code"] == 422, own
    assert all(r["healthy"] for r in tools.values()) and all(r["healthy"] for r in admin.values()), (rows, admin)
    # V0552: the member-ballot probe needs a second developer; this bag mints none, so its two rows say so
    probes = {k: v for k, v in rows.items() if k.startswith("commons: ")}
    assert set(probes) == {"commons: " + L.COMMONS_VOTE_CHECK, "commons: " + L.COMMONS_TALLY_CHECK}
    assert all(not r["healthy"] and "no mint_throwaway" in r["skip_reason"] for r in probes.values())
    assert set(admin) == {"theprotocol_adminCommonsOpenSeason", "theprotocol_adminCommonsPaySeason",
                          "theprotocol_adminCommonsWriteOffAward", "theprotocol_adminCommonsStrikeSubmission",
                          "theprotocol_adminCommonsCloseSeason", "theprotocol_adminCommonsCancelSeason"}
    open_args = dict(seen)["theprotocol_adminCommonsOpenSeason"]
    assert open_args["title"].startswith(L.COMMONS_TESTER_TITLE) and open_args["seed"] == "1"
    # the ballot names its own submission, and the pay step only ever sees the open season
    assert dict(seen)["theprotocol_castCommonsBallot"]["allocations"] == {"9": 10}
    assert dict(seen)["theprotocol_adminCommonsPaySeason"] == {"season_id": 4}


def test_a_refusal_for_another_reason_is_a_failure_and_a_wrong_read_back_a_finding():
    seen, rows, admin = _run(_answers(**{
        "theprotocol_castCommonsBallot": (422, "Error: HTTP 422: too_many_points: a ballot spreads at most 100"),
        "theprotocol_adminCommonsCloseSeason": lambda args: _set("open", 200, {"id": 4, "status": "open"})}))
    own = rows["refusal: castCommonsBallot a ballot for its own developer's submission"]
    assert not own["healthy"]
    assert "own_submission or not_a_member" in own["fail_reason"]
    assert admin["theprotocol_adminCommonsCloseSeason"]["fail_reason"].startswith("BUG-FIND")
    # the cancel still ran and the season reads cancelled
    assert "theprotocol_adminCommonsCancelSeason" in admin and admin["theprotocol_adminCommonsCancelSeason"]["healthy"]


def test_a_season_this_run_opened_is_cancelled_even_when_a_step_fails():
    seen, rows, admin = _run(_answers(**{"theprotocol_submitCommonsWork": (403, "Error: HTTP 403: "
                                                                                "developer_not_eligible: only ...")}))
    tools = [t for t, _ in seen]
    assert tools[-2:] == ["theprotocol_adminCommonsCancelSeason", "theprotocol_getCommonsSeason"]
    assert "theprotocol_adminCommonsCloseSeason" not in tools and not rows["theprotocol_submitCommonsWork"]["healthy"]


def test_someone_elses_live_season_is_never_touched():
    live = {"seasons": [{"id": 7, "status": "open", "title": "Season of 2026-10"}], "currency": "SBXA"}
    seen, rows, admin = _run(_answers(**{"theprotocol_getCommonsSeasons": (200, live)}))
    assert [t for t, _ in seen] == ["theprotocol_getCommonsSeasons"]
    assert set(admin) == {"theprotocol_adminCommonsOpenSeason", "theprotocol_adminCommonsCloseSeason",
                          "theprotocol_adminCommonsStrikeSubmission", "theprotocol_adminCommonsCancelSeason"}
    assert all(not r["healthy"] and "#7" in r["skip_reason"] for r in admin.values())


def test_where_the_commons_is_off_only_the_first_read_runs_held_to_its_switch():
    seen, rows, admin = _run(_answers(**{"theprotocol_getCommonsSeasons": (403, OFF_TEXT)}),
                             config={"commons_enabled": False})
    assert [t for t, _ in seen] == ["theprotocol_getCommonsSeasons"] and admin == {}
    row = rows["theprotocol_getCommonsSeasons"]
    assert row["healthy"] and row["switched_off"] == "commons_enabled=false"
    # control: the same refusal on a target that reports the commons on is a failure, and still nothing is opened
    seen, rows, admin = _run(_answers(**{"theprotocol_getCommonsSeasons": (403, OFF_TEXT)}))
    assert not rows["theprotocol_getCommonsSeasons"]["healthy"] and len(seen) == 1 and admin == {}


# ── V0552 (agentvault2-33's ask): at most once per UTC day, and the tester's own orphan never holds the live slot ──────
def _tester_season(sid, status, when):
    return {"id": sid, "status": status, "title": f"MCP tester season {when:%Y%m%dT%H%M%S}Z", "opens_at": when.isoformat()}


def _listing(*seasons):
    return (200, {"seasons": list(seasons), "currency": "SBXA"})


def test_a_tester_season_opened_today_caps_the_lifecycle_and_names_it():
    now = datetime.now(timezone.utc)
    seen, rows, admin = _run(_answers(**{"theprotocol_getCommonsSeasons": _listing(_tester_season(9, "cancelled", now))}))
    assert [t for t, _ in seen] == ["theprotocol_getCommonsSeasons"]
    assert dict(seen)["theprotocol_getCommonsSeasons"] == {"limit": 20}
    assert set(admin) == {"theprotocol_adminCommonsOpenSeason", "theprotocol_adminCommonsCloseSeason",
                          "theprotocol_adminCommonsStrikeSubmission", "theprotocol_adminCommonsCancelSeason"}
    assert all(not r["healthy"] and "ran today at" in r["skip_reason"] and "#9" in r["skip_reason"] for r in admin.values())
    # every other commons tool keeps its contract (a refusal probe): no lifecycle row is written for it; the member-ballot
    # probe's two rows name the cap
    assert {k for k in rows if k.startswith("theprotocol_")} == {"theprotocol_getCommonsSeasons"}
    assert all("ran today at" in rows["commons: " + c]["skip_reason"] for c in (L.COMMONS_VOTE_CHECK, L.COMMONS_TALLY_CHECK))


def test_a_tester_season_from_yesterday_does_not_cap():
    yesterday = datetime.now(timezone.utc) - timedelta(days=1, minutes=5)
    seen, rows, admin = _run(_answers(**{"theprotocol_getCommonsSeasons": _listing(
        _tester_season(8, "cancelled", yesterday))}))
    assert "theprotocol_adminCommonsOpenSeason" in [t for t, _ in seen]
    assert admin["theprotocol_adminCommonsCancelSeason"]["healthy"]


def test_a_tester_season_left_open_by_an_earlier_run_is_cancelled_first():
    yesterday = datetime.now(timezone.utc) - timedelta(days=1, minutes=5)
    seen, rows, admin = _run(_answers(**{"theprotocol_getCommonsSeasons": _listing(
        _tester_season(7, "open", yesterday))}))
    tools = [(t, a.get("season_id")) for t, a in seen]
    assert tools[:3] == [("theprotocol_getCommonsSeasons", None), ("theprotocol_adminCommonsCancelSeason", 7),
                         ("theprotocol_adminCommonsOpenSeason", None)]
    assert tools[-2:] == [("theprotocol_adminCommonsCancelSeason", 4), ("theprotocol_getCommonsSeason", 4)]
    # one opened today and left open: cancelled, and the day's slot is taken (the cancel row is the measurement)
    now = datetime.now(timezone.utc)
    seen, rows, admin = _run(_answers(**{"theprotocol_getCommonsSeasons": _listing(_tester_season(6, "open", now))}))
    assert [(t, a.get("season_id")) for t, a in seen] == [("theprotocol_getCommonsSeasons", None),
                                                          ("theprotocol_adminCommonsCancelSeason", 6)]
    assert admin["theprotocol_adminCommonsCancelSeason"]["healthy"]
    assert "ran today at" in admin["theprotocol_adminCommonsOpenSeason"]["skip_reason"]


def test_a_season_a_person_opened_is_never_touched_even_beside_a_tester_orphan():
    yesterday = datetime.now(timezone.utc) - timedelta(days=1, minutes=5)
    person = {"id": 12, "status": "open", "title": "Season of 2026-10", "opens_at": yesterday.isoformat()}
    seen, rows, admin = _run(_answers(**{"theprotocol_getCommonsSeasons": _listing(
        person, _tester_season(7, "open", yesterday))}))
    cancelled = [a["season_id"] for t, a in seen if t == "theprotocol_adminCommonsCancelSeason"]
    assert cancelled == [7], "only the tester's own orphan is cancelled"
    assert "#12" in admin["theprotocol_adminCommonsOpenSeason"]["skip_reason"]
    # control: a title that merely starts like the tester's is a person's season
    lookalike = dict(person, title="MCP tester season, by hand")
    seen, rows, admin = _run(_answers(**{"theprotocol_getCommonsSeasons": _listing(lookalike)}))
    assert [t for t, _ in seen] == ["theprotocol_getCommonsSeasons"]

