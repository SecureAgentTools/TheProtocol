"""§MEMBERSHIP (2026-10-02): membership from the reputation bond, one vote per member.

His word 2026-10-02 ("approved. this sounds better", "do it fully autonomously") on the design in
sessionlogs2026/DESIGN_2026-10-02_STAKING_REPLACEMENT.md § 12 (S1): staking stops being the source of
governance weight. Influence comes from membership, not from Units:

  * a developer is a MEMBER of this registry when at least one of their agents holds the reputation
    bond here (`reputation_bonds`) that it, or the owner's wallet, funded (`funded_by` self | wallet;
    a treasury backstop bond holds the treasury's own money and never makes a member), in status
    `locked` or `matured` (`matured` only where GOVERNANCE_MEMBER_REQUIRES_MATURED_BOND says so), at
    least GOVERNANCE_MEMBER_MIN_BOND_AGE_DAYS old; the agent active and not suspended; the developer
    verified, not suspended, not deleted and not a federation shadow;
  * one member, one vote. The weight grows with tenure, from 1.0 when the membership begins to 2.0
    after GOVERNANCE_MEMBER_TENURE_FULL_DAYS, so "time-weighted voting power" (Terms § 5.8) stays
    true; only its basis moves, from locked Units to time as a member;
  * nothing here reads a balance, a stake position, an AGORA point or a score. More Units never buy
    more votes; tests/test_membership.py holds that line structurally (a source scan, not a promise).

GOVERNANCE_WEIGHT_MODE=lock (the default) keeps every governance weight exactly as before (the veToken
calculator); =member switches them to this module. Every knob is read per call (env, then the network
profile, then the default), so a flip takes effect on recreate and an image carrying this module is
byte-inert where nothing is set.

The bond already carries the Sybil defence this needs: it costs Units held in escrow, it ages, and its
maturity rule asks for transactions and for ratings from counterparties owned by OTHER developers
(services/reputation_bond.py). Requiring a matured bond for a vote is one knob away once a network has
the traffic for it.
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import network_profile as _np

logger = logging.getLogger(__name__)

WEIGHT_MODES = ("lock", "member")
PRESENCE_MODES = ("off", "conditional", "required")
MEMBER_FUNDERS = ("self", "wallet")
MEMBER_BOND_STATUSES = ("locked", "matured")
MAX_WEIGHT = 2.0
# `votes.voting_power` is read back as an integer everywhere (VoteResponse, the tallies, the MCP
# contracts), so a member's weight is stored as points: 100 points = weight 1.0.
POINTS_PER_WEIGHT = 100
FLOW_WINDOW_DAYS = 30

NOT_A_MEMBER_SENTENCE = (
    "not_a_member: Only members of this registry can do this. A member is a developer with an agent "
    "holding the reputation bond here, funded by the agent or the owner's wallet, at least {days} days "
    "old (GOVERNANCE_WEIGHT_MODE=member)."
)


# ── knobs ────────────────────────────────────────────────────────────────────

def weight_mode() -> str:
    """`lock` (today's veToken weights) or `member`. An unknown value keeps today's behaviour."""
    v = (_np.knob("GOVERNANCE_WEIGHT_MODE", "lock") or "lock").strip().lower()
    if v not in WEIGHT_MODES:
        logger.error("[MEMBERSHIP] GOVERNANCE_WEIGHT_MODE=%r is not one of %s; using lock", v, WEIGHT_MODES)
        return "lock"
    return v


def member_mode() -> bool:
    return weight_mode() == "member"


def presence_mode() -> str:
    """`off`, `conditional` (a member WITH a second factor must use it) or `required` (a member
    without one cannot vote). An unknown value is read as `conditional`: never weaker than asked for
    by accident, never a lock-out by a typo."""
    v = (_np.knob("GOVERNANCE_PRESENCE_MODE", "off") or "off").strip().lower()
    if v not in PRESENCE_MODES:
        logger.error("[MEMBERSHIP] GOVERNANCE_PRESENCE_MODE=%r is not one of %s; using conditional",
                     v, PRESENCE_MODES)
        return "conditional"
    return v


def min_bond_age_days() -> int:
    return max(0, _np.int_knob("GOVERNANCE_MEMBER_MIN_BOND_AGE_DAYS", 30))


def requires_matured_bond() -> bool:
    return _np.bool_knob("GOVERNANCE_MEMBER_REQUIRES_MATURED_BOND", False)


def tenure_full_days() -> int:
    return max(1, _np.int_knob("GOVERNANCE_MEMBER_TENURE_FULL_DAYS", 365))


def not_a_member_sentence() -> str:
    return NOT_A_MEMBER_SENTENCE.format(days=min_bond_age_days())


# ── pure rules (no database; tests/test_membership.py drives them directly) ─

def _aware(t: Optional[_dt.datetime]) -> Optional[_dt.datetime]:
    if t is None:
        return None
    return t if t.tzinfo else t.replace(tzinfo=_dt.timezone.utc)


def now_utc() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def weight_for(member_since: _dt.datetime, now: _dt.datetime, full_days: int) -> float:
    """1.0 on the day the membership begins, rising in a straight line to 2.0 after `full_days`."""
    days = max(0.0, (_aware(now) - _aware(member_since)).total_seconds() / 86400.0)
    return round(1.0 + min(1.0, days / float(max(1, full_days))), 4)


def points_for(weight: float) -> int:
    return int(round(float(weight) * POINTS_PER_WEIGHT))


def bond_qualifies_at(row: Mapping[str, Any], *, min_age_days: int,
                      requires_matured: bool) -> Tuple[Optional[_dt.datetime], List[str]]:
    """When ONE bond row makes its developer a member, or None, with the reasons it does not.

    `row` carries: status, funded_by, locked_at, matured_at, agent_status, enforcement_status. The
    developer's own state (verified, suspended) is the caller's, because it is the same for every row.
    The reasons are the codes `/membership/me` reports: bond (gone), bond_funded_by_treasury,
    bond_matured, agent_suspended. Age is not a reason here: a young bond still has a date.
    """
    reasons: List[str] = []
    status = (row.get("status") or "").lower()
    funded_by = (row.get("funded_by") or "").lower()
    if status not in MEMBER_BOND_STATUSES:
        reasons.append("bond")
    if funded_by not in MEMBER_FUNDERS:
        reasons.append("bond_funded_by_treasury" if funded_by == "treasury" else "bond")
    if requires_matured and status != "matured":
        reasons.append("bond_matured")
    if (row.get("agent_status") or "active") != "active" or \
            (row.get("enforcement_status") or "active") != "active":
        reasons.append("agent_suspended")
    locked_at = _aware(row.get("locked_at"))
    if reasons or locked_at is None:
        return None, reasons or ["bond"]
    at = locked_at + _dt.timedelta(days=min_age_days)
    if requires_matured:
        matured_at = _aware(row.get("matured_at"))
        if matured_at is None:
            return None, ["bond_matured"]
        at = max(at, matured_at)
    return at, []


def member_since_from_rows(rows: Iterable[Mapping[str, Any]], *, now: _dt.datetime, min_age_days: int,
                           requires_matured: bool) -> Optional[_dt.datetime]:
    """The earliest moment any of a developer's bonds made them a member, if that moment has come."""
    best: Optional[_dt.datetime] = None
    for row in rows:
        at, _ = bond_qualifies_at(row, min_age_days=min_age_days, requires_matured=requires_matured)
        if at is not None and at <= _aware(now) and (best is None or at < best):
            best = at
    return best


# ── database reads ────────────────────────────────────────────────────────────
#
# Plain SQL on purpose: these are reads over two tables the bond rail owns, and the WHERE clause is
# the membership rule itself, so it should read like the docstring above. Every literal in the SQL
# is a constant of this module; no caller input is interpolated.

# A developer whose account deletion is pending (the 14-day cooling-off after POST /request-deletion) or done is no
# member (agentvault2-0f's finding, 2026-10-02: 30 of sbx-alpha's 41 members were swept test accounts awaiting deletion,
# and every one of them still counted toward the quorum). These are the four statuses agent_authz._dev_principal_live
# reads as "conveys nothing"; test_membership.py pins that the two rules agree. Cancelling the deletion (the status
# back to NULL) restores membership with the original member_since, which is derived from the bond's locked_at.
DELETION_STATUSES_NOT_LIVE = ("pending", "pending_deletion", "deleted", "anonymized")

_ELIGIBLE_DEVELOPER_SQL = (
    "d.is_verified AND NOT COALESCE(d.is_suspended, false) AND d.deleted_at IS NULL "
    "AND NOT COALESCE(d.is_federation_shadow, false) "
    "AND lower(COALESCE(d.deletion_status, '')) NOT IN ("
    + ", ".join(f"'{s}'" for s in DELETION_STATUSES_NOT_LIVE) + ")"
)

_MEMBER_BOND_ROWS_SQL = f"""
SELECT a.creator_developer_id AS developer_id, b.status, b.funded_by, b.locked_at, b.matured_at,
       a.status AS agent_status, a.enforcement_status
  FROM reputation_bonds b
  JOIN agents a ON a.did = b.agent_did
  JOIN developers d ON d.id = a.creator_developer_id
 WHERE b.status IN ('locked', 'matured')
   AND b.funded_by IN ('self', 'wallet')
   AND {_ELIGIBLE_DEVELOPER_SQL}
"""


async def _bond_rows_by_developer(db: AsyncSession) -> Dict[int, List[Dict[str, Any]]]:
    rows = (await db.execute(text(_MEMBER_BOND_ROWS_SQL))).mappings().all()
    out: Dict[int, List[Dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(int(r["developer_id"]), []).append(dict(r))
    return out


async def members(db: AsyncSession, now: Optional[_dt.datetime] = None) -> Dict[int, _dt.datetime]:
    """{developer_id: member_since} for every member of this registry right now."""
    now = _aware(now) or now_utc()
    min_age, matured = min_bond_age_days(), requires_matured_bond()
    out: Dict[int, _dt.datetime] = {}
    for dev_id, rows in (await _bond_rows_by_developer(db)).items():
        since = member_since_from_rows(rows, now=now, min_age_days=min_age, requires_matured=matured)
        if since is not None:
            out[dev_id] = since
    return out


async def member_since_for(db: AsyncSession, developer_id: int,
                           now: Optional[_dt.datetime] = None) -> Optional[_dt.datetime]:
    now = _aware(now) or now_utc()
    rows = (await db.execute(
        text(_MEMBER_BOND_ROWS_SQL + " AND a.creator_developer_id = :dev"), {"dev": int(developer_id)}
    )).mappings().all()
    return member_since_from_rows([dict(r) for r in rows], now=now, min_age_days=min_bond_age_days(),
                                  requires_matured=requires_matured_bond())


async def weight_points_for(db: AsyncSession, developer_id: int,
                            now: Optional[_dt.datetime] = None) -> int:
    """A member's vote in points (100 = weight 1.0); 0 for anyone who is not a member."""
    now = _aware(now) or now_utc()
    since = await member_since_for(db, developer_id, now)
    if since is None:
        return 0
    return points_for(weight_for(since, now, tenure_full_days()))


async def network_points(db: AsyncSession, now: Optional[_dt.datetime] = None) -> int:
    """The sum of every member's points: the denominator of a member-mode quorum."""
    now = _aware(now) or now_utc()
    full = tenure_full_days()
    return sum(points_for(weight_for(since, now, full)) for since in (await members(db, now)).values())


async def stats(db: AsyncSession, now: Optional[_dt.datetime] = None) -> Dict[str, Any]:
    """The public picture: how many members, who joined and who left in the last 30 days.

    `left_30d` counts developers who are not members now and whose bond ended (released or forfeited)
    inside the window after it had qualified: the honest half of a market for membership.
    """
    now = _aware(now) or now_utc()
    since_window = now - _dt.timedelta(days=FLOW_WINDOW_DAYS)
    current = await members(db, now)
    joined = sum(1 for s in current.values() if s >= since_window)
    min_age = min_bond_age_days()
    ended = (await db.execute(text(f"""
        SELECT DISTINCT a.creator_developer_id AS developer_id
          FROM reputation_bonds b
          JOIN agents a ON a.did = b.agent_did
          JOIN developers d ON d.id = a.creator_developer_id
         WHERE b.funded_by IN ('self', 'wallet')
           AND b.status IN ('released', 'forfeited')
           AND COALESCE(b.released_at, b.forfeited_at) >= :since
           AND b.locked_at + make_interval(days => :min_age) <= COALESCE(b.released_at, b.forfeited_at)
           AND {_ELIGIBLE_DEVELOPER_SQL}
    """), {"since": since_window, "min_age": min_age})).scalars().all()
    left = len({int(d) for d in ended} - set(current))
    full = tenure_full_days()
    return {
        "mode": weight_mode(),
        "members": len(current),
        "joined_30d": joined,
        "left_30d": left,
        "network_points": sum(points_for(weight_for(s, now, full)) for s in current.values()),
        "points_per_weight": POINTS_PER_WEIGHT,
        "min_bond_age_days": min_age,
        "requires_matured_bond": requires_matured_bond(),
        "tenure_full_days": full,
        "max_weight": MAX_WEIGHT,
        "presence_mode": presence_mode(),
        "as_of": now.isoformat(),
    }


# /membership/me (and member-mode voting power, which embeds it) lists at most this many bonds. A developer can run
# thousands of bonded agents (the sandbox tester's: 2,907, agentvault2-09's finding), and every vote dialog reads this
# answer; the verdict (is_member, missing, next_step) still reads EVERY bond, only the list is bounded.
AGENTS_SHOWN = 20


def _shown_order(a: Dict[str, Any]) -> tuple:
    """The bonds a person can act on lead: qualifying ones first (the one that made the member first), then those
    that will qualify (soonest first), then those that cannot qualify as they stand (stable by DID)."""
    if a["qualifies"]:
        return (0, a["qualifies_at"] or "", a["did"])
    if a["qualifies_at"]:
        return (1, a["qualifies_at"], a["did"])
    return (2, "", a["did"])


def deletion_not_live(deletion_status: Optional[str]) -> bool:
    """True while an account deletion is pending or done (DELETION_STATUSES_NOT_LIVE)."""
    return str(deletion_status or "").lower() in DELETION_STATUSES_NOT_LIVE


async def status_for_developer(db: AsyncSession, developer: Any,
                               now: Optional[_dt.datetime] = None) -> Dict[str, Any]:
    """What `/membership/me` answers: am I a member, since when, how much does my vote weigh, and if
    not, what exactly is missing. Each listed bond carries its own verdict, so the console can say "this
    agent's bond qualifies on 7 October" instead of a bare no. At most AGENTS_SHOWN bonds are listed
    (_shown_order), with agents_total / agents_qualifying / agents_shown; the verdict reads every bond."""
    now = _aware(now) or now_utc()
    min_age, matured, full = min_bond_age_days(), requires_matured_bond(), tenure_full_days()
    rows = (await db.execute(text("""
        SELECT b.agent_did, b.status, b.funded_by, b.locked_at, b.matured_at,
               a.status AS agent_status, a.enforcement_status
          FROM reputation_bonds b
          JOIN agents a ON a.did = b.agent_did
         WHERE a.creator_developer_id = :dev
         ORDER BY b.locked_at
    """), {"dev": int(developer.id)})).mappings().all()
    agents: List[Dict[str, Any]] = []
    missing: List[str] = []
    since: Optional[_dt.datetime] = None
    for r in rows:
        at, reasons = bond_qualifies_at(r, min_age_days=min_age, requires_matured=matured)
        qualifies = at is not None and at <= now
        if qualifies and (since is None or at < since):
            since = at
        if at is not None and at > now:
            reasons = reasons + ["bond_age"]
        agents.append({
            "did": r["agent_did"],
            "bond_status": r["status"],
            "funded_by": r["funded_by"],
            "locked_at": _aware(r["locked_at"]).isoformat() if r["locked_at"] else None,
            "qualifies_at": at.isoformat() if at else None,
            "qualifies": qualifies,
            "reasons": reasons,
        })
        for code in reasons:
            if code not in missing:
                missing.append(code)
    if not rows:
        missing.append("bond")
    if not getattr(developer, "is_verified", False):
        missing.append("developer_unverified")
    if getattr(developer, "is_suspended", False):
        missing.append("developer_suspended")
    deletion = deletion_not_live(getattr(developer, "deletion_status", None))
    if deletion:
        missing.append("deletion_pending")
    # The same conditions as _ELIGIBLE_DEVELOPER_SQL, so this answer and the member count never disagree.
    eligible_dev = (getattr(developer, "is_verified", False) and not getattr(developer, "is_suspended", False)
                    and not deletion and getattr(developer, "deleted_at", None) is None
                    and not getattr(developer, "is_federation_shadow", False))
    is_member = since is not None and eligible_dev
    weight = weight_for(since, now, full) if is_member else 0.0
    # The next step is a CODE the console translates, plus an English sentence for API and MCP readers,
    # plus the date when the step is "wait". One code per state, checked in the order a person would act.
    next_at: Optional[str] = None
    if is_member:
        missing, next_step = [], "none"
    elif "developer_suspended" in missing:
        next_step = "contact_support"
    elif "deletion_pending" in missing:
        next_step = "cancel_deletion"
    elif "developer_unverified" in missing:
        next_step = "verify_email"
    elif "bond_age" in missing:
        next_step = "wait_until"
        next_at = min(a["qualifies_at"] for a in agents if a["qualifies_at"])
    elif "bond_matured" in missing and any(a["bond_status"] == "locked" for a in agents):
        next_step = "wait_for_maturity"
    elif "bond_funded_by_treasury" in missing and not any(a["qualifies_at"] for a in agents):
        next_step = "use_own_funds"
    elif "agent_suspended" in missing and not any(a["qualifies_at"] for a in agents):
        next_step = "resolve_agent"
    else:
        next_step = "post_bond"
    next_text = {
        "none": None,
        "contact_support": "Your account is suspended; membership resumes when support lifts it.",
        "cancel_deletion": ("Your account is scheduled for deletion; cancel the deletion and you are a member again, "
                            "from your original member-since date."),
        "verify_email": "Verify your email address first; only verified developers are members.",
        "wait_until": f"Your bond qualifies on {next_at[:10]}; nothing else to do." if next_at else None,
        "wait_for_maturity": "This registry counts only matured bonds; the bond page shows what maturity still needs.",
        "use_own_funds": "A bond the treasury funded does not make a member; post one from the agent or your wallet.",
        "resolve_agent": "The agent holding your bond is suspended; a bond on an active agent is needed.",
        "post_bond": (f"Post the reputation bond for one of your agents (funded by the agent or your wallet); "
                      f"it makes you a member {min_age} days later."),
    }[next_step]
    shown = sorted(agents, key=_shown_order)[:AGENTS_SHOWN]
    names = {}
    if shown:                     # names for the listed bonds only, never for all of them
        names = {r["agent_did"]: r["name"] for r in (await db.execute(text(
            "SELECT agent_did, name FROM agent_cards WHERE agent_did = ANY(:dids)"),
            {"dids": [a["did"] for a in shown]})).mappings().all()}
    shown = [{"did": a["did"], "name": names.get(a["did"]) or a["did"],
              **{k: v for k, v in a.items() if k != "did"}} for a in shown]
    return {
        "mode": weight_mode(),
        "is_member": is_member,
        "member_since": since.isoformat() if is_member else None,
        "weight": weight,
        "points": points_for(weight) if is_member else 0,
        "tenure_days": int((now - since).total_seconds() // 86400) if is_member else 0,
        "tenure_full_days": full,
        "min_bond_age_days": min_age,
        "requires_matured_bond": matured,
        "presence_mode": presence_mode(),
        "agents": shown,
        "agents_total": len(agents),
        "agents_qualifying": sum(1 for a in agents if a["qualifies"]),
        "agents_shown": len(shown),
        "missing": missing,
        "next_step": next_step,
        "next_step_at": next_at,
        "next_step_text": next_text,
    }
