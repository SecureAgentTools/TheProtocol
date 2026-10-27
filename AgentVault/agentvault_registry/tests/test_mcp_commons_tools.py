"""§MEMBERSHIP (V0551): the membership and commons MCP tools reach their routes and say why they were refused.

Phases A and B shipped eleven commons routes and two membership routes with no MCP tool, so an MCP client could not see
a season, submit work, cast a ballot or ask whether it is a member, and the tester could measure none of it (the plan's
hand-over to agentvault2-09). mcp/tools_commons.py: 7 public-server tools (3 public, 2 developer, 2 agent) and 6 admin
tools, wired in the four places (dispatch, tier sets in server.py and audit.py, categories) and listed once each. These
routes refuse with {"error", "message"}, not RFC 7807, so the refusal goes INTO the error (the dispatcher renders only
that key); a ballot waiting for its member's confirmation answers step_up_required without an error key.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from agentvault_registry.mcp import tools_commons as T
from agentvault_registry.mcp.auth_bridge import MCPAuthContext, MCPAuthError

PUBLIC = {"theprotocol_getMembershipStats", "theprotocol_getCommonsSeasons", "theprotocol_getCommonsSeason"}
DEVELOPER = {"theprotocol_getMyMembership", "theprotocol_getMyCommonsSeason"}
AGENT = {"theprotocol_submitCommonsWork", "theprotocol_castCommonsBallot"}
ADMIN = {"theprotocol_adminCommonsOpenSeason", "theprotocol_adminCommonsCloseSeason",
         "theprotocol_adminCommonsStrikeSubmission", "theprotocol_adminCommonsPaySeason",
         "theprotocol_adminCommonsWriteOffAward", "theprotocol_adminCommonsCancelSeason"}

DEV = MCPAuthContext(auth_type="developer", developer_id=7, raw_token="dev-jwt")
AGT = MCPAuthContext(auth_type="agent", agent_did="did:theprotocol:a", agent_id=3, raw_token="agent-jwt")
ADM = MCPAuthContext(auth_type="developer", developer_id=1, is_admin=True, raw_token="admin-jwt")
OFF = {"error": "commons_disabled", "message": "commons_disabled: The commons is not enabled on this registry "
       "(COMMONS_ENABLED=false). Seasons, submissions and ballots open where it is."}


def _resp(status: int, body) -> httpx.Response:
    return httpx.Response(status, json=body, request=httpx.Request("GET", "http://x"))


def _record(monkeypatch, status: int = 200, body=None):
    calls: list = []

    async def _call(method, path, *, token="", params=None, body_=None, **kw):
        calls.append((method, path, token, params, kw.get("body")))
        return _resp(status, {"ok": True} if body is None else body), None
    monkeypatch.setattr(T, "_call", _call)
    return calls


def test_each_tool_is_wired_in_every_place_and_listed_once():
    from agentvault_registry.mcp import audit, server, server_admin, tool_categories as tc
    names = [t["name"] for t in server.ALL_TOOL_SCHEMAS]
    admin_names = [t["name"] for t in server_admin.ADMIN_TOOL_SCHEMAS]
    for n in PUBLIC | DEVELOPER | AGENT:
        assert names.count(n) == 1 and n in server.TOOL_DISPATCH, n
        assert n not in server_admin.ADMIN_TOOL_DISPATCH
        assert tc.get_category(n) == "governance"
    for n in ADMIN:
        assert admin_names.count(n) == 1 and n in server_admin.ADMIN_TOOL_DISPATCH, n
        assert n not in server.TOOL_DISPATCH and n not in names, "an admin tool never reaches the public server"
        assert tc.get_category(n, is_admin=True) == "treasury-economy"
    assert AGENT <= server.TIER2_TOOLS and AGENT <= audit._TIER_2_TOOLS
    assert DEVELOPER <= server.TIER3_TOOLS and DEVELOPER <= audit._TIER_3_TOOLS
    assert not (PUBLIC & (server.TIER2_TOOLS | server.TIER3_TOOLS)) and PUBLIC <= audit._TIER_1_TOOLS
    assert (AGENT | DEVELOPER) <= server.AUTH_REQUIRED_TOOLS and not (PUBLIC & server.AUTH_REQUIRED_TOOLS)
    # the one that moves money, and the ones that cannot be undone, ask a client to confirm
    by = {t["name"]: t for t in server_admin.ADMIN_TOOL_SCHEMAS}
    for n in ADMIN - {"theprotocol_adminCommonsOpenSeason"}:
        assert by[n]["annotations"]["destructiveHint"] is True, n
    assert {t["name"]: t for t in server.ALL_TOOL_SCHEMAS}["theprotocol_getCommonsSeasons"]["annotations"]["readOnlyHint"]


def test_each_tool_sends_its_route_with_its_token(monkeypatch):
    calls = _record(monkeypatch)
    run = asyncio.run
    run(T.get_membership_stats())
    run(T.get_my_membership(DEV))
    run(T.get_commons_seasons(limit=5))
    run(T.get_commons_season(4))
    run(T.get_my_commons_season(DEV, "4"))
    run(T.submit_commons_work(AGT, 4, "change", "A fix", [{"type": "commit", "ref": "abc123"}], "what"))
    run(T.cast_commons_ballot(AGT, 4, {9: 60, "10": 40}, challenge_id="ch-1"))
    run(T.admin_commons_open_season(ADM, title="S", duration_days=7, seed=10))
    run(T.admin_commons_close_season(ADM, 4))
    run(T.admin_commons_strike_submission(ADM, 4, 9, reason="no such commit"))
    run(T.admin_commons_pay_season(ADM, 4))
    run(T.admin_commons_write_off_award(ADM, 4, 2, reason="paid by hand"))
    run(T.admin_commons_cancel_season(ADM, 4, reason="opened by mistake"))
    assert [(m, p, tok) for m, p, tok, _q, _b in calls] == [
        ("GET", "/api/v1/membership/stats", ""),
        ("GET", "/api/v1/membership/me", "dev-jwt"),
        ("GET", "/api/v1/commons/seasons", ""),
        ("GET", "/api/v1/commons/seasons/4", ""),
        ("GET", "/api/v1/commons/seasons/4/mine", "dev-jwt"),
        ("POST", "/api/v1/commons/seasons/4/submissions", "agent-jwt"),
        ("POST", "/api/v1/commons/seasons/4/ballot", "agent-jwt"),
        ("POST", "/api/v1/admin/commons/seasons", "admin-jwt"),
        ("POST", "/api/v1/admin/commons/seasons/4/close", "admin-jwt"),
        ("POST", "/api/v1/admin/commons/seasons/4/strike", "admin-jwt"),
        ("POST", "/api/v1/admin/commons/seasons/4/pay", "admin-jwt"),
        ("POST", "/api/v1/admin/commons/seasons/4/awards/2/write-off", "admin-jwt"),
        ("POST", "/api/v1/admin/commons/seasons/4/cancel", "admin-jwt"),
    ]
    assert calls[2][3] == {"limit": 5}
    assert calls[5][4] == {"kind": "change", "title": "A fix", "description": "what",
                           "evidence": [{"type": "commit", "ref": "abc123"}]}
    assert calls[6][4] == {"allocations": {"9": 60, "10": 40}, "challenge_id": "ch-1"}
    assert calls[7][4] == {"title": "S", "duration_days": 7, "seed": "10"}
    assert calls[9][4] == {"submission_id": 9, "reason": "no such commit"}


def test_a_refusal_carries_its_code_word_and_sentence_into_the_error(monkeypatch):
    _record(monkeypatch, 403, OFF)
    out = asyncio.run(T.get_commons_seasons())
    assert out == {"error": "HTTP 403: " + OFF["message"]}, "the sentence already starts with its code word: once"
    _record(monkeypatch, 409, {"error": "season_live", "message": "a season is already open or awaiting payment"})
    out = asyncio.run(T.admin_commons_open_season(ADM, seed=1))
    assert out["error"] == "HTTP 409: season_live: a season is already open or awaiting payment"
    # control: an RFC 7807 refusal (validation, the auth layer) is read the way every other refusal is
    _record(monkeypatch, 401, {"detail": "Could not validate credentials"})
    assert asyncio.run(T.get_my_membership(DEV)) == {"error": "HTTP 401: Could not validate credentials"}
    # and a 2xx answer is the route's own body
    _record(monkeypatch, 200, {"seasons": [], "currency": "SBXA"})
    assert asyncio.run(T.get_commons_seasons()) == {"seasons": [], "currency": "SBXA"}


def test_a_ballot_waiting_for_its_member_returns_the_challenge_not_an_error(monkeypatch):
    pending = {"error": "step_up_required", "message": "Confirm this ballot on your phone.",
               "step_up": {"challenge_id": "ch-9", "method": "device"}}
    _record(monkeypatch, 428, pending)
    out = asyncio.run(T.cast_commons_ballot(AGT, 4, {"9": 100}))
    assert "error" not in out and out["status"] == "step_up_required"
    assert out["step_up"] == {"challenge_id": "ch-9", "method": "device"} and "challenge_id" in out["next"]
    # control: any other refusal of the ballot is an error with its reason
    _record(monkeypatch, 403, {"error": "not_a_member", "message": "not_a_member: Only members of this registry can "
                                                                   "do this."})
    assert asyncio.run(T.cast_commons_ballot(AGT, 4, {"9": 100})) == {
        "error": "HTTP 403: not_a_member: Only members of this registry can do this."}


def test_a_bad_argument_never_reaches_the_registry(monkeypatch):
    calls = _record(monkeypatch)
    run = asyncio.run
    for bad in ("abc", True, 0, -3, "1.5"):
        assert "season_id" in run(T.get_commons_season(bad))["error"], bad
    assert "limit" in run(T.get_commons_seasons(limit=0))["error"]
    assert "limit" in run(T.get_commons_seasons(limit=101))["error"]
    assert "evidence" in run(T.submit_commons_work(AGT, 4, "change", "A fix", []))["error"]
    assert "allocations" in run(T.cast_commons_ballot(AGT, 4, {}))["error"]
    assert "duration_days" in run(T.admin_commons_open_season(ADM, duration_days=121))["error"]
    assert "award_id" in run(T.admin_commons_write_off_award(ADM, 4, "x", reason="because"))["error"]
    assert calls == []


def test_each_tool_asks_for_its_own_tier():
    run = asyncio.run
    with pytest.raises(MCPAuthError):
        run(T.get_my_membership(AGT))
    with pytest.raises(MCPAuthError):
        run(T.submit_commons_work(DEV, 4, "change", "A fix", [{"type": "commit", "ref": "x"}]))
    with pytest.raises(MCPAuthError):
        run(T.cast_commons_ballot(DEV, 4, {"9": 1}))
    with pytest.raises(MCPAuthError):
        run(T.admin_commons_pay_season(DEV, 4))   # a developer who is not an admin
    with pytest.raises(MCPAuthError):
        run(T.admin_commons_open_season(AGT))
