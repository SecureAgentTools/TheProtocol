"""MCP tools: membership and the commons (§MEMBERSHIP phases A and B, 2026-10-02; agentvault2-09).

Membership (routers/membership.py): getMembershipStats (public), getMyMembership (developer key or JWT).

The commons (routers/commons.py; services/commons.py holds the rules; where COMMONS_ENABLED is off every route answers
403 commons_disabled, and /api/v1/public/registry-config says commons_enabled false):
    getCommonsSeasons, getCommonsSeason            public
    getMyCommonsSeason                             developer key or JWT: the caller's submissions and ballot
    submitCommonsWork, castCommonsBallot           agent JWT (a ballot is a member's, one per developer, and is
                                                   confirmed on a device where GOVERNANCE_PRESENCE_MODE asks)
    adminCommons{Open,Close,Pay,Cancel}Season,     admin server, admin_treasury
    adminCommonsStrikeSubmission, adminCommonsWriteOffAward

These routes refuse with {"error": <code word>, "message": <sentence>}, not RFC 7807. The dispatcher renders a result
carrying `error` as `Error: <error>` and drops every other key (§BATCH3), so the code word and the sentence go INTO the
error: `HTTP <status>: <code word>: <sentence>`. A ballot that waits for its member's confirmation answers
`status: step_up_required` WITHOUT an `error` key, so the challenge reaches the caller (castVote's rule).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .auth_bridge import (
    MCPAuthContext, format_tool_exception, mcp_forwarded_headers, require_agent_auth, require_developer_auth,
)
from .auth_bridge import mcp_http_client  # D6-514: every client to this registry carries the MCP relay proof
from .refusal import refusal_reason
from .tools_admin import _get_effective_jwt, require_admin_auth
from .tools_agent import REGISTRY_SELF_URL
from ..core.path_segment import seg

logger = logging.getLogger(__name__)
_TIMEOUT = 30.0

KINDS = ("guild_order", "change", "translation", "operations", "help", "other")
EVIDENCE_TYPES = ("guild_order", "url", "commit", "ticket", "document", "other")


def _reason(r: httpx.Response) -> str:
    """The refusal's code word and sentence. These routes answer {"error", "message"}; any other body (a 422 from
    validation, a proxy's page) is read the way every other refusal is (refusal_reason)."""
    try:
        body = r.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and isinstance(body.get("error"), str) and isinstance(body.get("message"), str):
        code, msg = body["error"].strip(), body["message"].strip()
        return (msg if msg.startswith(code) else f"{code}: {msg}")[:500]
    return refusal_reason(r)


async def _call(method: str, path: str, *, token: str = "", params: Optional[dict] = None,
                body: Optional[dict] = None) -> Tuple[Optional[httpx.Response], Optional[Dict[str, Any]]]:
    headers = {"Content-Type": "application/json", **mcp_forwarded_headers()}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with mcp_http_client(timeout=_TIMEOUT) as client:
            r = await client.request(method, f"{REGISTRY_SELF_URL}{path}", params=params, json=body, headers=headers)
        return r, None
    except httpx.TimeoutException:
        return None, {"error": f"{method} {path} timed out"}
    except Exception as e:  # noqa: BLE001 — every failure reaches the caller as a sentence
        logger.error("commons %s %s error: %s", method, path, e, exc_info=True)
        return None, {"error": format_tool_exception(e)}


def _answer(r: httpx.Response) -> Dict[str, Any]:
    if r.status_code in (200, 201):
        try:
            data = r.json()
        except ValueError:
            return {"error": f"HTTP {r.status_code}: the registry's answer was not JSON"}
        return data if isinstance(data, dict) else {"items": data}
    return {"error": f"HTTP {r.status_code}: {_reason(r)}"}


async def _request(method: str, path: str, **kw) -> Dict[str, Any]:
    r, err = await _call(method, path, **kw)
    return err or _answer(r)


def _whole(name: str, value: Any, lo: int = 1, hi: Optional[int] = None) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    """A whole number from the caller, in range; a bool or a fraction is the caller's error, said as such."""
    if isinstance(value, bool):
        return None, {"error": f"{name} must be a whole number (got {value!r})"}
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return None, {"error": f"{name} must be a whole number (got {str(value)[:40]!r})"}
    if n < lo or (hi is not None and n > hi):
        return None, {"error": f"{name} must be between {lo} and {hi}" if hi is not None else f"{name} must be at least {lo}"}
    return n, None


def _token(auth: MCPAuthContext) -> Optional[Dict[str, Any]]:
    return None if auth.raw_token else {"error": "No authentication token available"}


# ── membership ───────────────────────────────────────────────────────────────

async def get_membership_stats() -> Dict[str, Any]:
    """Members of this registry: the count, the 30-day flow and the rules (public)."""
    return await _request("GET", "/api/v1/membership/stats")


async def get_my_membership(auth: MCPAuthContext) -> Dict[str, Any]:
    """Am I (my developer) a member of this registry, and if not, what is missing (developer key or JWT)."""
    require_developer_auth(auth)
    return _token(auth) or await _request("GET", "/api/v1/membership/me", token=auth.raw_token)


# ── the commons: public ──────────────────────────────────────────────────────

async def get_commons_seasons(limit: int = 20) -> Dict[str, Any]:
    """The commons seasons of this registry, newest first, with the frame's currency (public)."""
    n, refused = _whole("limit", limit, 1, 100)
    return refused or await _request("GET", "/api/v1/commons/seasons", params={"limit": n})


async def get_commons_season(season_id: int) -> Dict[str, Any]:
    """One season: its budget, rules, submissions and, once it closes, the ballots and the results (public)."""
    sid, refused = _whole("season_id", season_id)
    return refused or await _request("GET", f"/api/v1/commons/seasons/{seg(sid)}")


# ── the commons: a member's side ─────────────────────────────────────────────

async def get_my_commons_season(auth: MCPAuthContext, season_id: int) -> Dict[str, Any]:
    """The caller's own side of a season: their developer's submissions, their current ballot, and whether they are a
    member (developer key or JWT)."""
    require_developer_auth(auth)
    sid, refused = _whole("season_id", season_id)
    return refused or _token(auth) or await _request("GET", f"/api/v1/commons/seasons/{seg(sid)}/mine",
                                                       token=auth.raw_token)


async def submit_commons_work(auth: MCPAuthContext, season_id: int, kind: str, title: str,
                              evidence: Optional[List[Dict[str, Any]]] = None, description: str = "") -> Dict[str, Any]:
    """Submit work ALREADY DONE to an open season, with its evidence (agent JWT; a verified developer's agent)."""
    require_agent_auth(auth)
    sid, refused = _whole("season_id", season_id)
    if refused:
        return refused
    if not isinstance(evidence, list) or not evidence:
        return {"error": "evidence is required: a list of {type, ref, url?} (1 to 10 items)"}
    body = {"kind": kind, "title": title, "description": description or "", "evidence": evidence}
    return _token(auth) or await _request("POST", f"/api/v1/commons/seasons/{seg(sid)}/submissions",
                                          token=auth.raw_token, body=body)


async def cast_commons_ballot(auth: MCPAuthContext, season_id: int, allocations: Optional[Dict[str, Any]] = None,
                              totp_code: str = "", challenge_id: str = "") -> Dict[str, Any]:
    """Spread up to 100 points over an open season's submissions (members; one ballot per developer, replaceable until
    the close; never your own developer's submissions). Where the registry asks for a confirmation the first call
    answers status step_up_required with the challenge to approve on your phone; call again with challenge_id."""
    require_agent_auth(auth)
    sid, refused = _whole("season_id", season_id)
    if refused:
        return refused
    if not isinstance(allocations, dict) or not allocations:
        return {"error": "allocations is required: {submission_id: points}, at most 100 points in all"}
    body: Dict[str, Any] = {"allocations": {str(k): v for k, v in allocations.items()}}
    if totp_code:
        body["totp_code"] = str(totp_code)[:16]
    if challenge_id:
        body["challenge_id"] = str(challenge_id)[:44]
    if (miss := _token(auth)):
        return miss
    r, err = await _call("POST", f"/api/v1/commons/seasons/{seg(sid)}/ballot", token=auth.raw_token, body=body)
    if err:
        return err
    if r.status_code == 428:
        try:
            pending = r.json()
        except ValueError:
            pending = None
        if isinstance(pending, dict) and pending.get("error") == "step_up_required":
            return {
                "status": "step_up_required",
                "message": pending.get("message") or "Confirm this ballot on your phone.",
                "step_up": pending.get("step_up"),
                "next": ("Approve the challenge in Pocket, Approvals (or use your authenticator app), then call "
                         "castCommonsBallot again with the same season_id and allocations plus challenge_id "
                         "(or totp_code)."),
            }
    return _answer(r)


# ── the commons: admin (admin_treasury) ──────────────────────────────────────

async def admin_commons_open_season(auth: MCPAuthContext, title: str = "", ends_at: str = "",
                                    duration_days: Optional[int] = None, seed: Any = None,
                                    fee_share_percent: Any = None) -> Dict[str, Any]:
    """Open a commons season. Its budget is published at opening (a share of the fee collector's balance plus the
    seed, capped by COMMONS_MAX_BUDGET) and nothing moves until it is paid. One live season at a time."""
    require_admin_auth(auth)
    body: Dict[str, Any] = {"title": title or ""}
    if ends_at:
        body["ends_at"] = str(ends_at)
    if duration_days not in (None, ""):
        d, refused = _whole("duration_days", duration_days, 1, 120)
        if refused:
            return refused
        body["duration_days"] = d
    if seed not in (None, ""):
        body["seed"] = str(seed)
    if fee_share_percent not in (None, ""):
        body["fee_share_percent"] = str(fee_share_percent)
    return await _request("POST", "/api/v1/admin/commons/seasons", token=_get_effective_jwt(auth), body=body)


async def admin_commons_close_season(auth: MCPAuthContext, season_id: int) -> Dict[str, Any]:
    """Close a season and fix its tally (the awards it will pay); answers the season with its results."""
    require_admin_auth(auth)
    sid, refused = _whole("season_id", season_id)
    return refused or await _request("POST", f"/api/v1/admin/commons/seasons/{seg(sid)}/close",
                                     token=_get_effective_jwt(auth))


async def admin_commons_strike_submission(auth: MCPAuthContext, season_id: int, submission_id: int,
                                          reason: str = "") -> Dict[str, Any]:
    """Strike a submission whose evidence does not hold (before payment starts); the reason is kept and published."""
    require_admin_auth(auth)
    sid, refused = _whole("season_id", season_id)
    if refused:
        return refused
    xid, refused = _whole("submission_id", submission_id)
    return refused or await _request("POST", f"/api/v1/admin/commons/seasons/{seg(sid)}/strike",
                                     token=_get_effective_jwt(auth), body={"submission_id": xid, "reason": reason})


async def admin_commons_pay_season(auth: MCPAuthContext, season_id: int) -> Dict[str, Any]:
    """Pay a closed season's awards through the reward funding waterfall (fee collector first, then treasury). A
    failed payment is re-sent by the next run while its first attempt is under 23 hours old; older ones are listed in
    needs_decision for a write-off."""
    require_admin_auth(auth)
    sid, refused = _whole("season_id", season_id)
    return refused or await _request("POST", f"/api/v1/admin/commons/seasons/{seg(sid)}/pay",
                                     token=_get_effective_jwt(auth))


async def admin_commons_write_off_award(auth: MCPAuthContext, season_id: int, award_id: int,
                                        reason: str = "") -> Dict[str, Any]:
    """Settle a failed award without a commons payment (a run will not re-send it); the failure stays on the award."""
    require_admin_auth(auth)
    sid, refused = _whole("season_id", season_id)
    if refused:
        return refused
    aid, refused = _whole("award_id", award_id)
    return refused or await _request("POST", f"/api/v1/admin/commons/seasons/{seg(sid)}/awards/{seg(aid)}/write-off",
                                     token=_get_effective_jwt(auth), body={"reason": reason})


async def admin_commons_cancel_season(auth: MCPAuthContext, season_id: int, reason: str = "") -> Dict[str, Any]:
    """Cancel a season nothing was paid from (frees the live-season slot); the reason is kept and published."""
    require_admin_auth(auth)
    sid, refused = _whole("season_id", season_id)
    return refused or await _request("POST", f"/api/v1/admin/commons/seasons/{seg(sid)}/cancel",
                                     token=_get_effective_jwt(auth), body={"reason": reason})


# ── schemas ──────────────────────────────────────────────────────────────────

_SEASON_ID = {"type": "integer", "description": "The season's id (getCommonsSeasons)"}
_AGENT_JWT = {"type": "string", "description": "Optional: agent JWT from getAgentToken."}
_OFF = " Where COMMONS_ENABLED is off it answers 403 commons_disabled."

COMMONS_PUBLIC_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "name": "theprotocol_getMembershipStats",
        "description": ("Members of this registry: how many, the 30-day flow, and the rules a developer meets to be one "
                        "(a reputation bond of their own, held long enough). Public."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "theprotocol_getCommonsSeasons",
        "description": ("The commons seasons of this registry, newest first: a member-steered budget that pays only for "
                        "work already done. Public." + _OFF),
        "inputSchema": {"type": "object", "properties": {
            "limit": {"type": "integer", "description": "How many seasons (1 to 100, default 20)", "default": 20},
        }},
    },
    {
        "name": "theprotocol_getCommonsSeason",
        "description": ("One commons season: its budget, rules and submissions; once it closes, the ballots and the "
                        "results. Public." + _OFF),
        "inputSchema": {"type": "object", "properties": {"season_id": _SEASON_ID}, "required": ["season_id"]},
    },
]

COMMONS_DEVELOPER_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "name": "theprotocol_getMyMembership",
        "description": ("Is your developer a member of this registry, and if not, what is missing (the next step in "
                        "words). Developer key or JWT."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "theprotocol_getMyCommonsSeason",
        "description": ("Your side of a commons season: your developer's submissions, your current ballot (the one a "
                        "new ballot replaces) and whether you are a member. Developer key or JWT." + _OFF),
        "inputSchema": {"type": "object", "properties": {"season_id": _SEASON_ID}, "required": ["season_id"]},
    },
]

COMMONS_AGENT_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "name": "theprotocol_submitCommonsWork",
        "description": ("Submit work ALREADY DONE to an open commons season, with evidence a member can check (a guild "
                        "order, a commit, a ticket, a document). Members spread their points over the submissions and "
                        "the season's budget is shared by the median points. Agent JWT." + _OFF),
        "inputSchema": {"type": "object", "properties": {
            "season_id": _SEASON_ID,
            "kind": {"type": "string", "enum": list(KINDS), "description": "What kind of work"},
            "title": {"type": "string", "description": "A short title (3 to 200 characters)"},
            "description": {"type": "string", "description": "What was done (up to 4000 characters)", "default": ""},
            "evidence": {"type": "array", "description": "1 to 10 items a member can check", "items": {
                "type": "object", "properties": {
                    "type": {"type": "string", "enum": list(EVIDENCE_TYPES)},
                    "ref": {"type": "string", "description": "The order id, commit, ticket or a short label"},
                    "url": {"type": "string", "description": "Optional link"},
                }, "required": ["type", "ref"]}},
            "agent_jwt": _AGENT_JWT,
        }, "required": ["season_id", "kind", "title", "evidence"]},
    },
    {
        "name": "theprotocol_castCommonsBallot",
        "description": ("Spread up to 100 points over an open season's submissions. Members only; one ballot per "
                        "developer, replaceable until the close; never your own developer's submissions. Where the "
                        "registry asks for a confirmation the first call answers status step_up_required with a "
                        "challenge to approve on your phone; call again with challenge_id (or totp_code). "
                        "Agent JWT." + _OFF),
        "inputSchema": {"type": "object", "properties": {
            "season_id": _SEASON_ID,
            "allocations": {"type": "object", "description": "submission id -> points, at most 100 in all",
                            "additionalProperties": {"type": "integer"}},
            "totp_code": {"type": "string", "description": "Optional: a current authenticator code", "default": ""},
            "challenge_id": {"type": "string", "description": "Optional: the challenge you approved for THIS ballot",
                             "default": ""},
            "agent_jwt": _AGENT_JWT,
        }, "required": ["season_id", "allocations"]},
    },
]

COMMONS_ADMIN_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "name": "theprotocol_adminCommonsOpenSeason",
        "description": ("Open a commons season. Its budget is published at opening (a share of the fee collector's "
                        "balance plus the seed, capped by COMMONS_MAX_BUDGET); nothing moves until it is paid. One live "
                        "season at a time (409 season_live). Admin (admin_treasury)." + _OFF),
        "inputSchema": {"type": "object", "properties": {
            "title": {"type": "string", "description": "Defaults to 'Season of <month>'", "default": ""},
            "ends_at": {"type": "string", "description": "When it closes (ISO 8601, UTC); or duration_days"},
            "duration_days": {"type": "integer", "description": "Instead of ends_at (1 to 120; default 30)"},
            "seed": {"type": ["number", "string"], "description": "Added from the treasury, in the frame's unit"},
            "fee_share_percent": {"type": ["number", "string"],
                                  "description": "The fee collector's share (default COMMONS_FEE_SHARE_PERCENT)"},
        }},
    },
    {
        "name": "theprotocol_adminCommonsCloseSeason",
        "description": ("Close a commons season and fix its tally: the awards it will pay. Answers the season with its "
                        "results. Admin (admin_treasury)." + _OFF),
        "inputSchema": {"type": "object", "properties": {"season_id": _SEASON_ID}, "required": ["season_id"]},
    },
    {
        "name": "theprotocol_adminCommonsStrikeSubmission",
        "description": ("Strike a submission whose evidence does not hold, before payment starts (409 payment_started "
                        "after). The reason is kept and published. Admin (admin_treasury)." + _OFF),
        "inputSchema": {"type": "object", "properties": {
            "season_id": _SEASON_ID,
            "submission_id": {"type": "integer", "description": "The submission to strike"},
            "reason": {"type": "string", "description": "Why its evidence does not hold"},
        }, "required": ["season_id", "submission_id", "reason"]},
    },
    {
        "name": "theprotocol_adminCommonsPaySeason",
        "description": ("Pay a closed season's awards through the payout funding waterfall (fee collector first, then "
                        "treasury). A failed payment is re-sent by the next run while its first attempt is under 23 "
                        "hours old; older ones are listed in needs_decision. MOVES MONEY. Admin (admin_treasury)."
                        + _OFF),
        "inputSchema": {"type": "object", "properties": {"season_id": _SEASON_ID}, "required": ["season_id"]},
    },
    {
        "name": "theprotocol_adminCommonsWriteOffAward",
        "description": ("Settle a failed award without a commons payment, when a run will not re-send it (pay it by "
                        "hand through the treasury rail if it is owed). Admin (admin_treasury)." + _OFF),
        "inputSchema": {"type": "object", "properties": {
            "season_id": _SEASON_ID,
            "award_id": {"type": "integer", "description": "The award (getCommonsSeason lists each award's id)"},
            "reason": {"type": "string", "description": "Why it is settled without a payment (kept on the award)"},
        }, "required": ["season_id", "award_id", "reason"]},
    },
    {
        "name": "theprotocol_adminCommonsCancelSeason",
        "description": ("Cancel a season nothing was paid from; frees the live-season slot (409 season_partly_paid "
                        "once anything was paid). Admin (admin_treasury)." + _OFF),
        "inputSchema": {"type": "object", "properties": {
            "season_id": _SEASON_ID,
            "reason": {"type": "string", "description": "Why it is cancelled (kept and published)"},
        }, "required": ["season_id", "reason"]},
    },
]
