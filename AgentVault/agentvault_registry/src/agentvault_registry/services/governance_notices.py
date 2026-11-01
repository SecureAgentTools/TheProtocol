"""V0652 (af) (order gwo_3b80091fe506da824c40f903, agentvault2-14, 2026-10-31): governance's notices.

The gaps file (session-lead's NOTIFICATION_GAPS_2026-10-31.md): "Governance (no category at all today)": a vote you can
cast, the same vote 24 h before it closes while you have not voted, and its result. Who can vote: in member mode
(GOVERNANCE_WEIGHT_MODE=member, production's set) the registry's members; otherwise the owners of agents with an
active stake (the lock weights' holders). A proposal's opening is said when the proposal is created (once: one
proposal per POST), its closing reminder by the auto-tally worker (once per proposal, claimed on its id), its result
by whichever tally ran first (the manual route and the worker can both tally a proposal; the notice is claimed on its
id). Every function is best effort and never raises: a notice must not break a vote.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

CLOSING_NOTICE = timedelta(hours=24)
_CLICK = "/ui#/governance"


async def voters(db) -> List[int]:
    """The developers who may vote on this registry right now."""
    from agentvault_registry.services import membership
    if membership.member_mode():
        return sorted(int(d) for d in (await membership.members(db)).keys())
    rows = (await db.execute(text(
        "SELECT DISTINCT a.creator_developer_id FROM stakes s JOIN agents a ON a.did = s.agent_did "
        "WHERE s.is_active AND a.creator_developer_id IS NOT NULL"))).all()
    return sorted(int(r[0]) for r in rows)


async def _owner_of(db, did: Optional[str]) -> Optional[int]:
    if not did:
        return None
    return (await db.execute(text("SELECT creator_developer_id FROM agents WHERE did = :d"), {"d": did})).scalar()


async def _voted(db, proposal_id: int) -> set:
    rows = (await db.execute(text(
        "SELECT DISTINCT a.creator_developer_id FROM votes v JOIN agents a ON a.did = v.voter_did "
        "WHERE v.proposal_id = :p AND a.creator_developer_id IS NOT NULL"), {"p": int(proposal_id)})).all()
    return {int(r[0]) for r in rows}


def _when(ts) -> str:
    try:
        return ts.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:  # noqa: BLE001
        return str(ts)


def tell_opened(proposal_id: int, title: str, end_timestamp, proposer_did: str) -> None:
    """After a proposal is created: every developer who may vote on it, but the one who proposed it."""
    from agentvault_registry.background_tasks import push_notify

    async def _go():
        try:
            from agentvault_registry.database import get_db_context
            async with get_db_context() as db:
                devs = await voters(db)
                proposer = await _owner_of(db, proposer_did)
            devs = [d for d in devs if d != proposer]
            if devs:
                await push_notify.notify(
                    "governance.proposal_opened", devs, title="A vote you can cast",
                    message=f"“{(title or '')[:120]}” is open for votes until {_when(end_timestamp)}.",
                    tags="ballot_box", click=_CLICK)
        except Exception:  # noqa: BLE001
            logger.debug("[GOV-NOTICE] opened notice skipped", exc_info=True)

    push_notify.spawn_notice(_go())


def tell_result(proposal_id: int, title: str, outcome: str, votes_for, votes_against, proposer_did: str) -> None:
    """After a tally: the developers who voted on it, and the one who proposed it. Once per proposal."""
    from agentvault_registry.background_tasks import push_notify

    async def _go():
        try:
            if not await push_notify.claim_once(f"governance.result:{int(proposal_id)}", 400 * 86400):
                return
            from agentvault_registry.database import get_db_context
            async with get_db_context() as db:
                devs = await _voted(db, proposal_id)
                proposer = await _owner_of(db, proposer_did)
            if proposer:
                devs.add(int(proposer))
            if devs:
                word = {"PASSED": "passed", "FAILED": "did not pass", "REJECTED": "did not pass"}.get(
                    str(outcome or "").upper(), str(outcome or "was tallied").lower())
                await push_notify.notify(
                    "governance.result", sorted(devs), title="A vote was tallied",
                    message=f"“{(title or '')[:120]}” {word} ({votes_for} for, {votes_against} against).",
                    tags="ballot_box", click=_CLICK)
        except Exception:  # noqa: BLE001
            logger.debug("[GOV-NOTICE] result notice skipped", exc_info=True)

    push_notify.spawn_notice(_go())


async def remind_closing(db, now: Optional[datetime] = None) -> int:
    """The auto-tally worker's turn: a proposal that closes within 24 h (one whose whole window is longer than that)
    reminds the developers who may vote and have not. Once per proposal. Returns how many proposals reminded."""
    from agentvault_registry.background_tasks import push_notify
    now = now or datetime.now(timezone.utc)
    told = 0
    try:
        rows = (await db.execute(text(
            "SELECT id, title, end_timestamp FROM governance_proposals WHERE status = 'VOTING' "
            "AND end_timestamp > :now AND end_timestamp <= :soon AND end_timestamp - created_at > :window"),
            {"now": now, "soon": now + CLOSING_NOTICE, "window": CLOSING_NOTICE})).all()
        if not rows:
            return 0
        can = await voters(db)
        for pid, title, end_ts in rows:
            if not await push_notify.claim_once(f"governance.vote_closing:{int(pid)}", 30 * 86400):
                continue
            devs = sorted(set(can) - await _voted(db, pid))
            if devs:
                await push_notify.notify(
                    "governance.vote_closing", devs, title="A vote closes in a day",
                    message=f"“{(title or '')[:120]}” closes {_when(end_ts)}, and you have not voted.",
                    tags="ballot_box", click=_CLICK)
                told += 1
    except Exception:  # noqa: BLE001
        logger.debug("[GOV-NOTICE] closing reminders skipped", exc_info=True)
    return told
