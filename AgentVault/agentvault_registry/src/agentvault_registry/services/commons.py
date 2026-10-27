"""§MEMBERSHIP phase B (2026-10-02): the commons. A registry's fee income funds work its members steer.

His word 2026-10-02 ("approved", "do it fully autonomously") on DESIGN_2026-10-02_STAKING_REPLACEMENT.md § 12 (S3).
The success link of the old staking idea, pointed at the people who create it: a busy registry collects fees, a share
of them becomes a season's budget, and the budget pays for work, never for holding anything.

    a SEASON          a budget (a share of the fee collector's balance when it opens, plus an optional seed from
                      the treasury), a window, and the rules in force, snapshotted when it opens
    a SUBMISSION      work already done, with its evidence, by any agent of a verified developer (not only members)
    a BALLOT          a member spreads up to 100 points over the season's submissions, never their own; one ballot
                      per member developer, replaceable until the season closes
    the TALLY         per submission, the MEDIAN of the non-zero points from at least COMMONS_MIN_VOTERS_PER_SUBMISSION
                      members, so a small ring cannot steer it; shares normalised to the budget; each developer
                      capped at COMMONS_RECIPIENT_CAP_PERCENT of it; what is not awarded stays where it is
    an AWARD          paid through the reward funding waterfall (fee collector first, then treasury; it never mints),
                      one payment per recipient per season, key `commons-{season}-{did}`, so a re-run pays nothing

What never enters any formula here: a balance, a stake position, an AGORA point, a vote weight or a track record.
tests/test_commons.py scans this module for it and has a control that must fail.

Money moves only in `pay_season`, through `services/reward_funding.fund_reward_via_waterfall` (rule 14: no new rail).
The audit events (CommonsSeasonOpened/Closed, CommonsAwardPaid) are emitted by the registry and skipped by the
projection (mig 0183); the balance move is the waterfall's own TokensTransferred.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import logging
import os
import statistics
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import network_profile as _np
from . import membership as _membership

logger = logging.getLogger(__name__)

BALLOT_POINTS = 100
KINDS = ("guild_order", "change", "translation", "operations", "help", "other")
EVIDENCE_TYPES = ("guild_order", "url", "commit", "ticket", "document", "other")
MAX_EVIDENCE = 10
AMOUNT_QUANTUM = Decimal("0.000001")   # agents' balances are Numeric(30, 6): never award a dust the cache cannot hold
WATERFALL_REASON = "commons"
# A payment that failed (or never reported back) is re-sent under its own key only while the ledger still remembers
# that key: the ledger keeps an idempotency record 24 hours, so inside the window a re-send of a payment that DID land
# answers with the original transaction, and past it the same re-send could pay twice. The window is measured from
# the FIRST attempt (the ledger's record dates from then), and an older failure waits for a person (write_off_award).
RETRY_WINDOW = _dt.timedelta(hours=23)

DISABLED_SENTENCE = ("commons_disabled: The commons is not enabled on this registry (COMMONS_ENABLED=false). "
                     "Seasons, submissions and ballots open where it is.")


class CommonsRefusal(Exception):
    """A refusal that knows its HTTP status and code word (the GovernanceRefusal shape)."""

    def __init__(self, status_code: int, error: str, message: str, **extra):
        super().__init__(message)
        self.status_code = status_code
        self.error = error
        self.message = message
        self.extra = extra

    def body(self) -> dict:
        return {"error": self.error, "message": self.message, **self.extra}


# ── knobs ────────────────────────────────────────────────────────────────────

def commons_enabled() -> bool:
    return _np.bool_knob("COMMONS_ENABLED", False)


def require_enabled() -> None:
    if not commons_enabled():
        raise CommonsRefusal(403, "commons_disabled", DISABLED_SENTENCE)


def _percent_knob(name: str, fallback: str, lo: str, hi: str) -> Decimal:
    v = _np.money_knob(name, fallback)
    return min(max(v, Decimal(lo)), Decimal(hi))


def fee_share_percent() -> Decimal:
    return _percent_knob("COMMONS_FEE_SHARE_PERCENT", "50", "0", "100")


def recipient_cap_percent() -> Decimal:
    return _percent_knob("COMMONS_RECIPIENT_CAP_PERCENT", "20", "1", "100")


def min_voters() -> int:
    return max(1, _np.int_knob("COMMONS_MIN_VOTERS_PER_SUBMISSION", 2))


def max_submissions_per_developer() -> int:
    return max(1, _np.int_knob("COMMONS_MAX_SUBMISSIONS_PER_DEVELOPER", 5))


def max_budget() -> Optional[Decimal]:
    raw = (_np.knob("COMMONS_MAX_BUDGET", "") or "").strip()
    if not raw:
        return None
    try:
        v = Decimal(raw)
        return v if v > 0 else None
    except (InvalidOperation, ValueError):
        logger.error("[COMMONS] COMMONS_MAX_BUDGET=%r is not a number; no cap", raw)
        return None


def currency() -> str:
    from ..core.frame_currency import frame_currency
    return frame_currency()


def now_utc() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


# ── the tally (pure; tests/test_commons.py drives it directly) ──────────────

def q(amount: Decimal) -> Decimal:
    return Decimal(amount).quantize(AMOUNT_QUANTUM, rounding=ROUND_DOWN)


def tally(submissions: Iterable[Mapping[str, Any]], ballots: Iterable[Mapping[str, Any]], *,
          budget: Decimal, cap_percent: Decimal, min_voters_needed: int) -> Dict[str, Any]:
    """Who gets what, from the ballots alone.

    `submissions`: id, developer_id, submitter_did, status. `ballots`: voter_developer_id, allocations
    ({submission id as str: points}). A ballot's points for its own developer's submission are ignored even if
    they slipped in. Returns {"rows": [...], "awarded", "unallocated"}; a row per live submission, funded or not,
    so the page can say why a submission got nothing.
    """
    budget = Decimal(budget)
    subs = [dict(s) for s in submissions if (s.get("status") or "submitted") == "submitted"]
    bl = [dict(b) for b in ballots]
    scored: List[Dict[str, Any]] = []
    for s in subs:
        sid = str(s["id"])
        pts = []
        for b in bl:
            if int(b["voter_developer_id"]) == int(s["developer_id"]):
                continue
            try:
                p = int((b.get("allocations") or {}).get(sid, 0) or 0)
            except (TypeError, ValueError):
                p = 0
            if p > 0:
                pts.append(p)
        funded = len(pts) >= min_voters_needed
        median = Decimal(str(statistics.median(pts))) if (pts and funded) else Decimal(0)
        scored.append({"submission_id": int(s["id"]), "developer_id": int(s["developer_id"]),
                       "recipient_did": s["submitter_did"], "voters": len(pts), "median_points": median,
                       "funded": funded, "reason": None if funded else
                       ("no_points" if not pts else "too_few_voters")})
    total = sum((r["median_points"] for r in scored), Decimal(0))
    for r in scored:
        r["share"] = (r["median_points"] / total) if total > 0 else Decimal(0)
        r["amount"] = budget * r["share"]
    cap = budget * Decimal(cap_percent) / Decimal(100)
    by_dev: Dict[int, Decimal] = {}
    for r in scored:
        by_dev[r["developer_id"]] = by_dev.get(r["developer_id"], Decimal(0)) + r["amount"]
    for r in scored:
        dev_total = by_dev[r["developer_id"]]
        if dev_total > cap and dev_total > 0:
            r["amount"] = r["amount"] * cap / dev_total
            r["capped"] = True
        else:
            r["capped"] = False
        r["amount"] = q(r["amount"])
    awarded = sum((r["amount"] for r in scored), Decimal(0))
    return {"rows": scored, "awarded": awarded, "unallocated": budget - awarded}


def payment_action(status: str, attempted_at: Optional[_dt.datetime], now: _dt.datetime) -> Optional[str]:
    """What a pay run does with one award: "pay" (never sent), "retry" (sent, no answer recorded or failed, inside
    RETRY_WINDOW of the first attempt), "decide" (the same, past the window: never re-sent by a run), or None
    (paid, partial or written off: settled). A pending award WITH an attempt clock is a payment whose answer was lost
    (the process stopped mid-call): it is treated exactly like a failure, never as unsent."""
    if status not in ("pending", "failed"):
        return None
    if attempted_at is None:
        return "pay" if status == "pending" else "decide"
    return "retry" if now - attempted_at <= RETRY_WINDOW else "decide"


def ballot_digest(allocations: Mapping[str, int]) -> str:
    """Binds a phone approval to THIS allocation: change one point and the approval no longer fits."""
    canon = json.dumps({str(k): int(v) for k, v in sorted(allocations.items(), key=lambda kv: int(kv[0]))},
                       separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canon.encode()).hexdigest()[:16]


# ── reads ─────────────────────────────────────────────────────────────────────

async def _season(db: AsyncSession, season_id: int):
    from ..models import CommonsSeason
    s = await db.get(CommonsSeason, int(season_id))
    if s is None:
        raise CommonsRefusal(404, "season_not_found", f"season_not_found: there is no season {season_id}.")
    return s


async def live_season(db: AsyncSession):
    from ..models import CommonsSeason
    return (await db.execute(select(CommonsSeason).where(CommonsSeason.status.in_(("open", "closed")))
                             .order_by(CommonsSeason.id.desc()).limit(1))).scalar_one_or_none()


def _iso(t: Optional[_dt.datetime]) -> Optional[str]:
    return t.isoformat() if t else None


def _money(v: Any) -> Optional[str]:
    return None if v is None else format(Decimal(v).normalize(), "f")


def season_summary(s) -> Dict[str, Any]:
    return {
        "id": s.id, "title": s.title, "status": s.status, "currency": s.currency,
        "opens_at": _iso(s.opens_at), "ends_at": _iso(s.ends_at),
        "budget": _money(s.budget), "seed": _money(s.seed),
        "fee_share_percent": _money(s.fee_share_percent),
        "fee_collector_balance_at_open": _money(s.fee_collector_balance_at_open),
        "recipient_cap_percent": _money(s.recipient_cap_percent), "min_voters": s.min_voters,
        "ballot_points": BALLOT_POINTS,
        "closed_at": _iso(s.closed_at), "paid_at": _iso(s.paid_at),
        "cancelled_at": _iso(s.cancelled_at), "cancel_reason": s.cancel_reason,
        "rules": s.rules or {},
    }


async def list_seasons(db: AsyncSession, limit: int = 20) -> List[Dict[str, Any]]:
    from ..models import CommonsSeason
    rows = (await db.execute(select(CommonsSeason).order_by(CommonsSeason.id.desc()).limit(limit))).scalars().all()
    out = []
    for s in rows:
        paid = (await db.execute(text(
            "SELECT COALESCE(SUM(funded_amount), 0) FROM commons_awards WHERE season_id = :s AND status IN ('paid','partial')"),
            {"s": s.id})).scalar()
        subs = (await db.execute(text(
            "SELECT COUNT(*) FROM commons_submissions WHERE season_id = :s AND status = 'submitted'"), {"s": s.id})).scalar()
        ballots = (await db.execute(text("SELECT COUNT(*) FROM commons_ballots WHERE season_id = :s"),
                                    {"s": s.id})).scalar()
        out.append({**season_summary(s), "paid_total": _money(paid), "submissions": int(subs or 0),
                    "ballots": int(ballots or 0)})
    return out


async def season_detail(db: AsyncSession, season_id: int, viewer_developer_id: Optional[int] = None) -> Dict[str, Any]:
    """The public page of one season. Ballots are counted while it is open and published once it closes:
    who allocated what is the transparency that makes a ring of members visible."""
    from ..models import CommonsAward, CommonsBallot, CommonsSubmission
    s = await _season(db, season_id)
    subs = (await db.execute(select(CommonsSubmission).where(CommonsSubmission.season_id == s.id)
                             .order_by(CommonsSubmission.id))).scalars().all()
    ballots = (await db.execute(select(CommonsBallot).where(CommonsBallot.season_id == s.id)
                                .order_by(CommonsBallot.id))).scalars().all()
    awards = {a.submission_id: a for a in (await db.execute(
        select(CommonsAward).where(CommonsAward.season_id == s.id))).scalars().all()}
    names = {}
    if subs:
        names = {r["agent_did"]: r["name"] for r in (await db.execute(text(
            "SELECT agent_did, name FROM agent_cards WHERE agent_did = ANY(:d)"),
            {"d": list({x.submitter_did for x in subs})})).mappings().all()}
    closed = s.status in ("closed", "paid")
    out_subs = []
    for x in subs:
        a = awards.get(x.id)
        out_subs.append({
            "id": x.id, "kind": x.kind, "title": x.title, "description": x.description, "evidence": x.evidence or [],
            "submitter_did": x.submitter_did, "submitter_name": names.get(x.submitter_did) or x.submitter_did,
            "status": x.status, "struck_reason": x.struck_reason, "created_at": _iso(x.created_at),
            "mine": viewer_developer_id is not None and int(x.developer_id) == int(viewer_developer_id),
            "award": None if a is None else {
                "id": a.id,
                "median_points": _money(a.median_points), "voters": a.voters, "share": _money(a.share),
                "amount": _money(a.amount), "status": a.status, "funded_amount": _money(a.funded_amount),
                "shortfall": _money(a.shortfall), "paid_at": _iso(a.paid_at),
                "attempted_at": _iso(a.attempted_at), "written_off_at": _iso(a.written_off_at),
                "written_off_reason": a.written_off_reason,
            },
        })
    my_ballot = None
    if viewer_developer_id is not None:
        mine = next((b for b in ballots if int(b.voter_developer_id) == int(viewer_developer_id)), None)
        if mine is not None:
            my_ballot = {"allocations": mine.allocations, "total_points": mine.total_points,
                         "updated_at": _iso(mine.updated_at)}
    return {
        **season_summary(s),
        "tally": s.tally if closed else None,
        "submissions": out_subs,
        "ballots_cast": len(ballots),
        "ballots": [{"voter_did": b.voter_did, "allocations": b.allocations, "total_points": b.total_points}
                    for b in ballots] if closed else None,
        "my_ballot": my_ballot,
    }


# ── the fee collector, read through the ledger client (its mTLS and its key) ─

async def fee_collector_balance() -> Optional[Decimal]:
    """The fee collector's balance on this frame's ledger, or None when the ledger cannot say."""
    try:
        from ..teg_client import get_teg_client
        client = get_teg_client()
        r = await client._client.get(
            f"{client.base_url}{client.api_prefix}/admin/fee-collector/info",
            headers={"Authorization": f"Bearer {os.environ.get('TEG_ADMIN_API_KEY', '')}"},
        )
        if r.status_code != 200:
            logger.warning("[COMMONS] fee collector read answered %s", r.status_code)
            return None
        return Decimal(str((r.json() or {}).get("balance", "0")))
    except Exception as e:  # noqa: BLE001 — the caller decides what an unreadable balance means
        logger.warning("[COMMONS] fee collector read failed: %s", e)
        return None


def _emit(event_type: str, season_id: int, data: Dict[str, Any], key: str) -> None:
    try:
        from ..event_emitter import get_event_emitter
        get_event_emitter().emit_background(event_type=event_type, aggregate_id=f"commons-season-{season_id}",
                                            aggregate_type="Commons", data=data, idempotency_key=key)
    except Exception:  # noqa: BLE001 — an audit event never fails the step it records
        logger.warning("[COMMONS] %s for season %s not emitted", event_type, season_id, exc_info=True)


# ── the season's lifecycle ────────────────────────────────────────────────────

async def open_season(db: AsyncSession, *, admin_id: int, title: str, ends_at: _dt.datetime,
                      seed: Decimal = Decimal(0), share_percent: Optional[Decimal] = None):
    """Open a season. Its budget is the share of the fee collector's balance plus the seed, read NOW and
    published with the season: the rules cannot move after people start working to them."""
    from ..models import CommonsSeason
    require_enabled()
    if await live_season(db) is not None:
        raise CommonsRefusal(409, "season_live", "season_live: a season is already open or awaiting payment; "
                                                 "close and pay (or cancel) it first.")
    now = now_utc()
    if ends_at <= now:
        raise CommonsRefusal(422, "ends_in_past", "ends_in_past: a season must end in the future.")
    seed = Decimal(seed or 0)
    if seed < 0:
        raise CommonsRefusal(422, "negative_seed", "negative_seed: the seed cannot be negative.")
    share = fee_share_percent() if share_percent is None else min(max(Decimal(share_percent), Decimal(0)),
                                                                   Decimal(100))
    balance = await fee_collector_balance() if share > 0 else Decimal(0)
    if balance is None and seed <= 0:
        raise CommonsRefusal(503, "fee_collector_unreadable",
                             "fee_collector_unreadable: the ledger did not report the fee collector's balance, so "
                             "the season's budget cannot be set from it; retry, or open with an explicit seed.")
    budget = q((balance or Decimal(0)) * share / Decimal(100) + seed)
    cap = max_budget()
    if cap is not None and budget > cap:
        budget = q(cap)
    if budget <= 0:
        raise CommonsRefusal(422, "empty_budget", "empty_budget: the fee collector holds nothing to share and no "
                                                  "seed was given; a season with no budget pays nobody.")
    rules = {
        "ballot_points": BALLOT_POINTS,
        "min_voters_per_submission": min_voters(),
        "recipient_cap_percent": str(recipient_cap_percent()),
        "max_submissions_per_developer": max_submissions_per_developer(),
        "kinds": list(KINDS),
        "membership": {
            "min_bond_age_days": _membership.min_bond_age_days(),
            "requires_matured_bond": _membership.requires_matured_bond(),
            "presence_mode": _membership.presence_mode(),
        },
        "budget_rule": "share of the fee collector's balance at opening + seed; paid fee collector first, then treasury",
    }
    s = CommonsSeason(title=(title or "").strip()[:160] or f"Season of {now:%Y-%m}", status="open", opens_at=now,
                      ends_at=ends_at, currency=currency(), fee_share_percent=share,
                      fee_collector_balance_at_open=balance, seed=seed, budget=budget,
                      recipient_cap_percent=recipient_cap_percent(), min_voters=min_voters(), rules=rules,
                      created_by=admin_id)
    db.add(s)
    await db.commit()
    await db.refresh(s)
    _emit("CommonsSeasonOpened", s.id, {"season_id": s.id, "title": s.title, "budget": _money(s.budget),
                                        "currency": s.currency, "ends_at": _iso(s.ends_at)},
          key=f"commons-opened-{s.id}")
    return s


async def _assert_open(db: AsyncSession, season_id: int):
    s = await _season(db, season_id)
    if s.status != "open" or now_utc() > s.ends_at:
        raise CommonsRefusal(409, "season_not_open", f"season_not_open: season {s.id} is {s.status}"
                             + (" and its window has ended" if s.status == "open" else "") + ".")
    return s


async def _developer_of(db: AsyncSession, agent) -> Any:
    from ..models import Developer
    dev = await db.get(Developer, agent.creator_developer_id)
    if dev is None or not dev.is_verified or getattr(dev, "is_suspended", False) or dev.deleted_at is not None:
        raise CommonsRefusal(403, "developer_not_eligible",
                             "developer_not_eligible: only a verified, active developer's agents take part.")
    if (agent.status or "active") != "active" or (getattr(agent, "enforcement_status", None) or "active") != "active":
        raise CommonsRefusal(403, "agent_not_active", "agent_not_active: a suspended agent cannot take part.")
    return dev


def _clean_evidence(evidence: Any) -> List[Dict[str, str]]:
    items = evidence if isinstance(evidence, list) else []
    if not items:
        raise CommonsRefusal(422, "evidence_required", "evidence_required: name at least one piece of evidence "
                                                       "(a Guild order, a commit, a link, a ticket).")
    if len(items) > MAX_EVIDENCE:
        raise CommonsRefusal(422, "too_much_evidence", f"too_much_evidence: at most {MAX_EVIDENCE} items.")
    out = []
    for it in items:
        if not isinstance(it, dict):
            raise CommonsRefusal(422, "evidence_shape", "evidence_shape: each item is {type, ref, url?}.")
        typ = str(it.get("type") or "").strip().lower()
        ref = str(it.get("ref") or "").strip()
        url = str(it.get("url") or "").strip()
        if typ not in EVIDENCE_TYPES or not ref:
            raise CommonsRefusal(422, "evidence_shape", f"evidence_shape: type is one of {', '.join(EVIDENCE_TYPES)} "
                                                        "and ref is required.")
        if url and not (url.startswith("https://") or url.startswith("http://")):
            raise CommonsRefusal(422, "evidence_url", "evidence_url: a url starts with https://.")
        out.append({"type": typ, "ref": ref[:200], **({"url": url[:500]} if url else {})})
    return out


async def submit(db: AsyncSession, *, agent, season_id: int, kind: str, title: str, description: str,
                 evidence: Any):
    """Anyone may submit work: members steer the budget, they do not own it."""
    from ..models import CommonsSubmission
    require_enabled()
    s = await _assert_open(db, season_id)
    dev = await _developer_of(db, agent)
    kind = (kind or "").strip().lower()
    if kind not in KINDS:
        raise CommonsRefusal(422, "unknown_kind", f"unknown_kind: kind is one of {', '.join(KINDS)}.")
    title = (title or "").strip()
    if not (3 <= len(title) <= 200):
        raise CommonsRefusal(422, "title_length", "title_length: a title is 3 to 200 characters.")
    clean = _clean_evidence(evidence)
    n = (await db.execute(text(
        "SELECT COUNT(*) FROM commons_submissions WHERE season_id = :s AND developer_id = :d AND status <> 'withdrawn'"),
        {"s": s.id, "d": dev.id})).scalar() or 0
    if n >= max_submissions_per_developer():
        raise CommonsRefusal(429, "too_many_submissions",
                             f"too_many_submissions: at most {max_submissions_per_developer()} per developer per season.")
    x = CommonsSubmission(season_id=s.id, submitter_did=agent.did, developer_id=dev.id, kind=kind, title=title,
                          description=(description or "")[:4000], evidence=clean, status="submitted")
    db.add(x)
    await db.commit()
    await db.refresh(x)
    return x


async def validate_ballot(db: AsyncSession, *, agent, season_id: int,
                          allocations: Any) -> Tuple[Any, Dict[str, int], int, int]:
    """Everything that would refuse a ballot, checked BEFORE a phone is asked to confirm it.
    Returns (season, the allocations normalised, their total, the voter's developer id)."""
    require_enabled()
    s = await _assert_open(db, season_id)
    dev = await _developer_of(db, agent)
    if await _membership.weight_points_for(db, dev.id) <= 0:
        status = await _membership.status_for_developer(db, dev)
        raise CommonsRefusal(403, "not_a_member", _membership.not_a_member_sentence(),
                             missing=status.get("missing", []), next_step=status.get("next_step"))
    if not isinstance(allocations, dict) or not allocations:
        raise CommonsRefusal(422, "empty_ballot", "empty_ballot: give points to at least one submission.")
    clean: Dict[str, int] = {}
    for k, v in allocations.items():
        try:
            sid, pts = int(k), int(v)
        except (TypeError, ValueError):
            raise CommonsRefusal(422, "ballot_shape", "ballot_shape: allocations map submission ids to whole points.")
        if pts < 0:
            raise CommonsRefusal(422, "negative_points", "negative_points: points cannot be negative.")
        if pts:
            clean[str(sid)] = pts
    total = sum(clean.values())
    if total == 0:
        raise CommonsRefusal(422, "empty_ballot", "empty_ballot: give points to at least one submission.")
    if total > BALLOT_POINTS:
        raise CommonsRefusal(422, "too_many_points", f"too_many_points: a ballot spreads at most {BALLOT_POINTS} points "
                                                     f"(this one has {total}).")
    rows = (await db.execute(text(
        "SELECT id, developer_id, status FROM commons_submissions WHERE season_id = :s AND id = ANY(:ids)"),
        {"s": s.id, "ids": [int(k) for k in clean]})).mappings().all()
    found = {str(r["id"]): r for r in rows}
    unknown = [k for k in clean if k not in found or found[k]["status"] != "submitted"]
    if unknown:
        raise CommonsRefusal(422, "unknown_submission", "unknown_submission: these are not live submissions of "
                             f"this season: {', '.join(unknown)}.", submission_ids=unknown)
    own = [k for k in clean if int(found[k]["developer_id"]) == int(dev.id)]
    if own:
        raise CommonsRefusal(422, "own_submission", "own_submission: a member never gives points to their own "
                             f"developer's work: {', '.join(own)}.", submission_ids=own)
    return s, clean, total, dev.id


async def store_ballot(db: AsyncSession, *, season_id: int, developer_id: int, voter_did: str,
                       allocations: Dict[str, int], total: int, challenge_id: Optional[str]) -> Dict[str, Any]:
    await db.execute(text("""
        INSERT INTO commons_ballots (season_id, voter_developer_id, voter_did, allocations, total_points,
                                     presence_challenge_id, cast_at, updated_at)
        VALUES (:s, :d, :did, CAST(:a AS JSONB), :t, :c, now(), now())
        ON CONFLICT (season_id, voter_developer_id) DO UPDATE SET
            voter_did = EXCLUDED.voter_did, allocations = EXCLUDED.allocations,
            total_points = EXCLUDED.total_points, presence_challenge_id = EXCLUDED.presence_challenge_id,
            updated_at = now()
    """), {"s": int(season_id), "d": int(developer_id), "did": voter_did, "a": json.dumps(allocations),
           "t": int(total), "c": challenge_id})
    await db.commit()
    return {"season_id": int(season_id), "allocations": allocations, "total_points": int(total),
            "digest": ballot_digest(allocations)}


async def _retally(db: AsyncSession, s) -> Dict[str, Any]:
    """Tally from the ballots of those who are members NOW (a member suspended mid-season no longer counts), and
    rewrite the pending awards. Paid awards are never touched."""
    from ..models import CommonsAward
    members_now = await _membership.members(db)
    subs = (await db.execute(text(
        "SELECT id, developer_id, submitter_did, status FROM commons_submissions WHERE season_id = :s"),
        {"s": s.id})).mappings().all()
    ballots = (await db.execute(text(
        "SELECT voter_developer_id, allocations FROM commons_ballots WHERE season_id = :s"),
        {"s": s.id})).mappings().all()
    counted = [b for b in ballots if int(b["voter_developer_id"]) in members_now]
    result = tally(subs, counted, budget=Decimal(s.budget), cap_percent=Decimal(s.recipient_cap_percent),
                   min_voters_needed=int(s.min_voters))
    await db.execute(text("DELETE FROM commons_awards WHERE season_id = :s AND status = 'pending'"), {"s": s.id})
    for r in result["rows"]:
        if r["amount"] <= 0:
            continue
        db.add(CommonsAward(season_id=s.id, submission_id=r["submission_id"], recipient_did=r["recipient_did"],
                            developer_id=r["developer_id"], median_points=r["median_points"], voters=r["voters"],
                            share=r["share"], amount=r["amount"], status="pending"))
    summary = {
        "ballots_cast": len(ballots), "ballots_counted": len(counted),
        "awarded": _money(result["awarded"]), "unallocated": _money(result["unallocated"]),
        "rows": [{"submission_id": r["submission_id"], "voters": r["voters"],
                  "median_points": _money(r["median_points"]), "share": _money(r["share"]),
                  "amount": _money(r["amount"]), "capped": r["capped"], "reason": r["reason"]}
                 for r in result["rows"]],
        "tallied_at": now_utc().isoformat(),
    }
    s.tally = summary
    return summary


async def close_season(db: AsyncSession, *, admin_id: int, season_id: int):
    require_enabled()
    s = await _season(db, season_id)
    if s.status != "open":
        raise CommonsRefusal(409, "season_not_open", f"season_not_open: season {s.id} is {s.status}.")
    s.status, s.closed_at, s.closed_by = "closed", now_utc(), admin_id
    summary = await _retally(db, s)
    await db.commit()
    _emit("CommonsSeasonClosed", s.id, {"season_id": s.id, "awarded": summary["awarded"],
                                        "unallocated": summary["unallocated"], "ballots_counted": summary["ballots_counted"]},
          key=f"commons-closed-{s.id}")
    return s


async def _payment_started(db: AsyncSession, season_id: int) -> bool:
    """True once any award of the season was sent to the ledger (or settled): from then on the tally is fixed."""
    n = (await db.execute(text(
        "SELECT COUNT(*) FROM commons_awards WHERE season_id = :s AND (status <> 'pending' OR attempted_at IS NOT NULL)"),
        {"s": season_id})).scalar() or 0
    return n > 0


async def strike(db: AsyncSession, *, admin_id: int, season_id: int, submission_id: int, reason: str):
    """A reviewer removes a submission whose evidence does not hold. A closed season is tallied again."""
    from ..models import CommonsSubmission
    require_enabled()
    s = await _season(db, season_id)
    if s.status not in ("open", "closed"):
        raise CommonsRefusal(409, "season_settled", f"season_settled: season {s.id} is {s.status}.")
    x = await db.get(CommonsSubmission, int(submission_id))
    if x is None or x.season_id != s.id:
        raise CommonsRefusal(404, "submission_not_found", "submission_not_found: not a submission of this season.")
    reason = (reason or "").strip()
    if len(reason) < 5:
        raise CommonsRefusal(422, "reason_required", "reason_required: say why (at least 5 characters).")
    if s.status == "closed" and await _payment_started(db, s.id):
        raise CommonsRefusal(409, "payment_started", f"payment_started: the awards of season {s.id} are being paid, "
                                                     "so its tally is fixed; a struck submission can no longer change "
                                                     "it. Write off a failed award instead.")
    x.status, x.struck_reason, x.struck_by = "struck", reason[:240], admin_id
    if s.status == "closed":
        await _retally(db, s)
    await db.commit()
    return x


async def pay_season(db: AsyncSession, *, admin_id: int, season_id: int) -> Dict[str, Any]:
    """Pay every pending award: one waterfall payment per recipient, keyed so a re-run moves nothing.
    An exhausted waterfall pays what it can and says so; the shortfall is recorded, never invented.
    A failed payment is re-sent by the next run under the SAME key while payment_action says "retry"; past the
    window it is listed in `needs_decision` and never re-sent by a run (write_off_award settles it)."""
    from ..models import CommonsAward
    from .reward_funding import fund_reward_via_waterfall
    require_enabled()
    s = await _season(db, season_id)
    if s.status != "closed":
        raise CommonsRefusal(409, "season_not_closed", f"season_not_closed: season {s.id} is {s.status}; close it "
                                                       "first so the tally is fixed.")
    now = now_utc()
    open_rows = (await db.execute(select(CommonsAward).where(
        CommonsAward.season_id == s.id, CommonsAward.status.in_(("pending", "failed"))))).scalars().all()
    by_did: Dict[str, List[Any]] = {}
    needs_decision = []
    for a in open_rows:
        action = payment_action(a.status, a.attempted_at, now)
        if action in ("pay", "retry"):
            by_did.setdefault(a.recipient_did, []).append(a)
        elif action == "decide":
            needs_decision.append({"award_id": a.id, "recipient_did": a.recipient_did, "amount": _money(a.amount),
                                   "status": a.status, "first_attempt_at": _iso(a.attempted_at)})
    report = []
    for did, awards in sorted(by_did.items()):
        amount = q(sum((Decimal(a.amount) for a in awards), Decimal(0)))
        key = f"commons-{s.id}-{did}"
        for a in awards:          # the clock is written BEFORE the call, so a lost answer is never taken for unsent
            if a.attempted_at is None:
                a.attempted_at = now_utc()
        await db.commit()
        try:
            res = await fund_reward_via_waterfall(db, target_agent_did=did, amount=amount, reason=WATERFALL_REASON,
                                                  reference_id=f"commons-season-{s.id}", idempotency_key=key)
            funded = Decimal(str(res.get("funded_amount") or "0"))
            status = "paid" if res.get("status") == "completed" else "partial"
            for a in awards:
                part = (Decimal(a.amount) / amount) if amount > 0 else Decimal(0)
                a.status, a.idempotency_key = status, key
                a.teg_transaction_id = res.get("first_transaction_id")
                a.funded_amount = q(funded * part)
                a.shortfall = q(Decimal(a.amount) - a.funded_amount)
                a.paid_at = now_utc()
            report.append({"recipient_did": did, "amount": _money(amount), "funded": _money(funded), "status": status})
            _emit("CommonsAwardPaid", s.id, {"season_id": s.id, "recipient_did": did, "awarded": _money(amount),
                                             "funded": _money(funded), "status": status, "idempotency_key": key,
                                             "submission_ids": [a.submission_id for a in awards]},
                  key=f"commons-paid-{s.id}-{did}")
        except Exception as e:  # noqa: BLE001 — one recipient's failure does not stop the others; it is recorded
            for a in awards:
                a.status, a.error, a.idempotency_key = "failed", str(e)[:500], key
            report.append({"recipient_did": did, "amount": _money(amount), "status": "failed", "error": str(e)[:200]})
            logger.error("[COMMONS] season %s award to %s failed: %s", s.id, did, e)
        await db.commit()
    left = (await db.execute(text(
        "SELECT COUNT(*) FROM commons_awards WHERE season_id = :s AND status IN ('pending', 'failed')"),
        {"s": s.id})).scalar() or 0
    if left == 0:
        s.status, s.paid_at, s.paid_by = "paid", now_utc(), admin_id
        await db.commit()
    out = {"season": season_summary(s), "payments": report, "unpaid_awards": int(left), "needs_decision": needs_decision}
    if needs_decision:
        out["decision"] = (f"{len(needs_decision)} award(s) failed more than {int(RETRY_WINDOW.total_seconds() // 3600)} "
                           "hours after their first attempt. A run never re-sends them: the ledger no longer remembers "
                           "their key, so a re-send could pay twice if the first attempt landed. Check the recipient's "
                           "ledger rows, then write the award off (and pay it by hand through the treasury rail if "
                           "it is owed).")
    return out


async def write_off_award(db: AsyncSession, *, admin_id: int, season_id: int, award_id: int, reason: str):
    """Settle a failed award without paying it through the commons. The failed payment stays on the row (its error,
    its key, its first attempt); the write-off adds who decided and why. If the award is owed, pay it by hand through
    the treasury rail. Returns (award, awards still unpaid); the season is paid when none are left."""
    from ..models import CommonsAward
    require_enabled()
    s = await _season(db, season_id)
    if s.status != "closed":
        raise CommonsRefusal(409, "season_not_closed", f"season_not_closed: season {s.id} is {s.status}.")
    a = await db.get(CommonsAward, int(award_id))
    if a is None or a.season_id != s.id:
        raise CommonsRefusal(404, "award_not_found", "award_not_found: not an award of this season.")
    if not (a.status == "failed" or (a.status == "pending" and a.attempted_at is not None)):
        raise CommonsRefusal(409, "award_not_failed", f"award_not_failed: award {a.id} is {a.status}"
                                                      f"{'' if a.attempted_at else ' and was never sent'}; only a "
                                                      "payment that failed or never answered is written off.")
    reason = (reason or "").strip()
    if len(reason) < 5:
        raise CommonsRefusal(422, "reason_required", "reason_required: say why (at least 5 characters).")
    a.status, a.written_off_at, a.written_off_by, a.written_off_reason = "written_off", now_utc(), admin_id, reason[:240]
    await db.flush()
    left = (await db.execute(text(
        "SELECT COUNT(*) FROM commons_awards WHERE season_id = :s AND status IN ('pending', 'failed')"),
        {"s": s.id})).scalar() or 0
    if left == 0:
        s.status, s.paid_at, s.paid_by = "paid", now_utc(), admin_id
    await db.commit()
    logger.warning("[COMMONS] season %s award %s (%s, %s) written off by developer %s: %s", s.id, a.id,
                   a.recipient_did, a.amount, admin_id, a.written_off_reason)
    return a, int(left)


async def cancel_season(db: AsyncSession, *, admin_id: int, season_id: int, reason: str):
    require_enabled()
    s = await _season(db, season_id)
    if s.status not in ("open", "closed"):
        raise CommonsRefusal(409, "season_settled", f"season_settled: season {s.id} is {s.status}.")
    paid = (await db.execute(text(
        "SELECT COUNT(*) FROM commons_awards WHERE season_id = :s AND status IN ('paid', 'partial')"),
        {"s": s.id})).scalar() or 0
    if paid:
        raise CommonsRefusal(409, "season_partly_paid", "season_partly_paid: awards were paid; a paid season is "
                                                        "finished, not cancelled.")
    if await _payment_started(db, s.id):
        raise CommonsRefusal(409, "payment_started", f"payment_started: awards of season {s.id} were sent to the "
                                                     "ledger; a cancel could hide a payment that landed. Pay the "
                                                     "season again or write off its failed awards.")
    reason = (reason or "").strip()
    if len(reason) < 5:
        raise CommonsRefusal(422, "reason_required", "reason_required: say why (at least 5 characters).")
    await db.execute(text("DELETE FROM commons_awards WHERE season_id = :s AND status = 'pending'"), {"s": s.id})
    s.status, s.cancelled_at, s.cancel_reason = "cancelled", now_utc(), reason[:240]
    await db.commit()
    return s
