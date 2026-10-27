"""§OURSTATE-4 PULSE — the opt-in economy feed.

What a pulse IS: a small set of MOMENTS derived from work that already has a
public, verifiable record — settled guild jobs, the stars a counterparty gave,
work that traveled across registries. Each moment is a sentence about a fact,
and each carries the receipt reference that proves it.

What a pulse is NOT, and cannot become without changing this file:

  * PRESENCE. No "last seen", no "online", no typing, no read receipts. Law 6
    is not a setting here — there is no column, no timestamp and no endpoint
    from which presence could be derived. The IRC pass asked for `/seen` and it
    was rejected by name for exactly this reason.
  * BALANCES. Nothing here reads a wallet. "Earned 400 BVT this month" is a
    private fact wearing an achievement's clothes; a settled JOB COUNT is
    public because the counterparty already attested to it.
  * AUTOMATIC. Off until the person turns it on (`pocket.pulse` pref), and the
    profile says nothing about a pulse that is off — not "this user has no
    moments", which would be a claim about them.

Everything is computed ON READ from services/track_record.py, the same
registry-attested source Discover's proven-work band uses. There is no pulse
table, so there is nothing to drift, nothing to backfill, and no second
opinion about somebody's record.
"""
from __future__ import annotations

import datetime
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry.services import track_record

logger = logging.getLogger(__name__)

PULSE_PREF_KEY = "pocket.pulse"
MAX_MOMENTS = 20

# The tier ladder is the SAME one the earned-mark collar renders (§MARKGUILLOCHE
# — Proven 1 / Established 5 / Seasoned 10 / Veteran 25 / Expert 50 / Master
# 100 / Sovereign 250). Repeating the numbers here rather than importing them
# would be a second opinion about somebody's rank, which is how two surfaces
# start disagreeing about the same person.
TIERS = (("Proven", 1), ("Established", 5), ("Seasoned", 10), ("Veteran", 25),
         ("Expert", 50), ("Master", 100), ("Sovereign", 250))


def tier_for(jobs: int) -> Optional[str]:
    """The highest tier this many verified jobs reaches, or None below Proven."""
    name = None
    for label, need in TIERS:
        if jobs >= need:
            name = label
    return name


async def pulse_config(db: AsyncSession, developer_id: int) -> dict:
    """The person's pulse settings. OFF is the default and the absence of a row
    means off — never "not configured yet, assume yes"."""
    row = (await db.execute(sa_text(
        "SELECT value FROM developer_prefs WHERE developer_id = :d AND key = :k"
    ), {"d": int(developer_id), "k": PULSE_PREF_KEY})).first()
    val = row[0] if row else None
    if isinstance(val, str):
        import json
        try:
            val = json.loads(val)
        except ValueError:
            val = None
    cfg = val if isinstance(val, dict) else {}
    return {"enabled": bool(cfg.get("enabled")),
            "show_agents": cfg.get("show_agents", True) is not False,
            "note": (cfg.get("note") or "")[:200]}


def moments_from_summary(agent_name: str, did: str, s: Dict[str, Any]) -> List[dict]:
    """Turn ONE agent's attested summary into sentences.

    Every moment names its source field, so a reader can check the claim
    against the agent's own track-record page rather than trusting the
    sentence. A moment with nothing behind it is not emitted — an empty pulse
    is the honest rendering of an empty record.
    """
    out: List[dict] = []
    # ⚠ THE FIELD NAMES ARE THE PRODUCER'S, not ones that read well here:
    # `jobs_verified` / `last_verified_at` / `_starred`. The first cut invented
    # `verified_jobs` / `last_job_at`, every summary read as empty, and the
    # feature looked like "no attested work" for an agent that had just been
    # paid five stars. Never guess a column or a key — read the producer.
    jobs = int(s.get("jobs_verified") or 0)
    if jobs <= 0:
        return out

    tier = tier_for(jobs)
    if tier:
        out.append({
            "kind": "tier",
            "agent": agent_name, "did": did,
            "text": f"{agent_name} reached {tier} — {jobs} verified job(s).",
            "source": "track_record.jobs_verified",
            "at": s.get("last_verified_at"),
        })
    # ⚠ `_starred` is an INTERNAL accumulator the producer deletes before it
    # returns (track_record.py: `del s["_star_sum"], s["_starred"]`), so reading
    # it here was reading a key that can never arrive — the stars moment could
    # never fire. The producer sets `avg_stars` ONLY when at least one job was
    # starred, so `avg_stars is not None` IS "somebody gave stars", stated by
    # the one field that actually survives.
    avg = s.get("avg_stars")
    if avg is not None:
        out.append({
            "kind": "stars",
            "agent": agent_name, "did": did,
            "text": f"{agent_name} averages {avg} stars from the people who paid.",
            "source": "track_record.avg_stars",
            "at": s.get("last_verified_at"),
        })
    cross = int(s.get("cross_registry_jobs") or 0)
    if cross > 0:
        hosts = int(s.get("distinct_hosts") or 0)
        where = f" across {hosts} registries" if hosts > 1 else " on another registry"
        out.append({
            "kind": "cross_registry",
            "agent": agent_name, "did": did,
            "text": f"{agent_name} did {cross} job(s){where}.",
            "source": "track_record.cross_registry_jobs",
            "at": s.get("last_verified_at"),
        })
    return out


async def developer_pulse(db: AsyncSession, developer_id: int,
                          include_config: bool = False) -> dict:
    """The public pulse for one person: moments from the agents they own.

    Reads ONLY the attested track record. If the pulse is off, the answer says
    so and carries no moments — and it never says "no moments", because that
    would be a statement about their record rather than about their choice.
    """
    cfg = await pulse_config(db, developer_id)
    if not cfg["enabled"]:
        out = {"enabled": False, "moments": [],
               "note": "this account does not publish a pulse"}
        if include_config:
            out["config"] = cfg
        return out

    rows = (await db.execute(sa_text(
        "SELECT a.did, COALESCE(c.name, a.did) AS name "
        "FROM agents a LEFT JOIN agent_cards c ON c.agent_did = a.did "
        "WHERE a.creator_developer_id = :d AND a.status = 'active' LIMIT 200"
    ), {"d": int(developer_id)})).all()
    dids = [r[0] for r in rows]
    names = {r[0]: r[1] for r in rows}
    if not dids:
        return {"enabled": True, "moments": [], "agents": 0,
                "note": "published, and there is nothing attested to show yet"}


    summaries = await track_record.track_record_summaries(db, dids)
    moments: List[dict] = []
    for did in dids:
        s = summaries.get(did) or {}
        moments.extend(moments_from_summary(names.get(did, did), did, s))

    # Newest first where a date exists; undated moments (a tier reached with no
    # recorded last job) sort last rather than pretending to be recent.
    def _key(m: dict):
        return (0 if m.get("at") else 1, str(m.get("at") or ""))
    moments.sort(key=_key, reverse=False)
    moments = sorted(moments, key=lambda m: str(m.get("at") or ""), reverse=True)[:MAX_MOMENTS]

    # An empty list with a "how it was computed" note tells the reader nothing
    # about WHY it is empty. Say that too.
    note = ("computed from the registry-attested track record; "
            "every moment names the field it came from")
    if not moments:
        note = ("published, and there is nothing attested to show yet — "
                "finish a verified job and it appears here")
    out = {"enabled": True, "moments": moments, "agents": len(dids),
           "note": note,
           "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    if cfg["note"]:
        out["owner_note"] = cfg["note"]
    if include_config:
        out["config"] = cfg
    return out
