"""V0658 (k): ONE slash order for every slash, read from the TEG, with a cascade to the owner's other agents.

Every slash this registry makes drains the same configured order, through `drain` below:
  * a local ruling (services/enforcement_engine, under ENFORCEMENT_SLASH_MODE shadow or enforce);
  * a peer's slash request taken automatically (routers/federation_disputes.receive_slash_request);
  * an administrator's approval of a peer's request (routers/federation_disputes.approve_settlement).
Before V0658 a peer's request took only the defendant's cached liquid balance, whatever the order said.

The order is the enforcement policy's `slash_waterfall` (the factory default: bond, then locks, then liquid, each
capped at a share of the requested amount, `max_percent`). What each step can take is read from the TEG
(GET /admin/agent-locked-balance answers the liquid and the locked balance), never from the registry's cached balances:
  bond     the reputation bond the registry holds in escrow, from its row. The treasury already holds the units, so a
           forfeit moves nothing on the ledger: it records how much the treasury keeps (reputation_bond.forfeit).
  stake    the TEG's locked units, released by force_unstake_for_slash. The slashed units go to the treasury
           (D6-460: before V0658 only the 10% lock-break penalty did, and the slash itself was a cached number);
           the penalty comes on top of the slash, so releasing L units gives the slash at most L minus its 10%.
  liquid   the TEG's liquid units, to the treasury (/admin/treasury/receive).
  cascade  what the agent cannot cover moves on to the same developer's other agents on this registry, each through
           the same steps in the order's sequence, never past the slash amount (`max_percent` caps the whole cascade).
           Off unless the order lists it (the factory default does not), and always the last step. Those agents are
           asked in a stated order: the most held first (the registry's cached liquid, locked and bonded units; what
           each can give is then read from the TEG), then the oldest, at most CASCADE_MAX_AGENTS of them. A service
           account is never part of a cascade: the developer's `agents_unlisted_by_default`, the service-account mark
           of migration 0176, which only an administrator sets (PUT /admin/developers/{id}/admin-flags). Neither is an
           administrator's account (`is_admin` or an admin_* flag: its agents are the frame's own), a federation shadow
           or a deleted account; a deleted agent (status revoked) and a system DID are never asked.

Every move keeps delta at 0: the units go agent -> treasury on the existing rails (the TEG's unlock and its treasury
receive, fee-free), each under its own Idempotency-Key, so a repeat moves nothing twice; a lost answer is asked once more
under the same key (D6-441), and a move the TEG did not confirm is never counted. Each move is recorded once on the
ledger as SlashMoved, an audit record (skip_in_projection: the TEG's own LedgerBalanceChanged counts the units). A
slash amount is a whole number of units on every path (the peer protocol's, an enforcement action's and an
administrator's amounts are integers), so every step takes whole units. What no step could cover is the shortfall,
which the caller records.
"""
from __future__ import annotations

import copy
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from typing import Any, Dict, List, Optional, Sequence, Tuple

import httpx
from sqlalchemy import func, select

from ..config import settings
from ..crud.crud_enforcement import DEFAULT_POLICY_JSON
from ..es_ssl_helper import get_httpx_verify
from ..event_emitter import get_event_emitter
from ..models import Agent, Developer
from ..teg_client import get_teg_client

logger = logging.getLogger(__name__)

OWN_SOURCES = ("bond", "stake", "liquid")
CASCADE = "cascade"
CASCADE_MAX_AGENTS = 25
SYSTEM_DID_PREFIX = "did:theprotocol:teg_system_"
ADMIN_FLAGS = ("admin_treasury", "admin_support", "admin_enforcement", "admin_federation", "admin_platform")
SOURCE_WORDS = {"bond": "bond", "stake": "locks", "liquid": "liquid", CASCADE: "the owner's other agents"}
_KEY_MAX = 200   # the TEG keeps an Idempotency-Key in 255 characters; the ledger's event key adds a prefix

try:
    from prometheus_client import Counter as _Counter
    ENFORCEMENT_SLASH_WATERFALL = _Counter(
        "registry_enforcement_slash_waterfall_total",
        "Slash waterfall steps that absorbed value (shadow = would have; enforce = did)",
        ["mode", "source"],
    )
    ENFORCEMENT_SLASH_WATERFALL_DEFAULTED = _Counter(
        "registry_enforcement_slash_waterfall_defaulted_total",
        "Slashes that drained in the factory-default order because the resolved policy carried no waterfall",
        ["reason"],
    )
except Exception:  # noqa: BLE001 — metrics never break enforcement
    ENFORCEMENT_SLASH_WATERFALL = None
    ENFORCEMENT_SLASH_WATERFALL_DEFAULTED = None


# ── the order ────────────────────────────────────────────────────────────────────────────────────────────────────────

def order_for(policy: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The ORDER a slash drains from: the frame's resolved `slash_waterfall`, else THE factory default.

    §BATCH0911 (2026-09-11) — this was a second inline literal of the default, named at §FRAMEPOLICY
    and left because it sits on a money path. Measured before removing it: the literal equalled
    `DEFAULT_POLICY_JSON["slash_waterfall"]` byte for byte, and it was still REACHABLE — admission
    skips a stored `null` (`validate_policy_json` checks only a present value), `frame_policy.resolve`
    lets that null replace the default, and in exactly that state `explain()` reports the frame as
    running the default. The readout and the engine agreed only because two copies were equal.

    The fallback stays: a row written around the validator must not silently switch off the money
    half of enforcement. But it is now the same object the readout reports, and it says when it fires.
    Falsy-only, exactly the `or` it replaces, so every state behaves as it did.
    (V0658 (k): moved here from enforcement_engine, which every slash now drains through.)
    """
    wf = policy.get("slash_waterfall") if isinstance(policy, dict) else None
    if wf:
        return copy.deepcopy(wf)
    reason = "null" if wf is None else ("empty" if isinstance(wf, list) else type(wf).__name__)
    logger.warning(
        "[SlashOrder] the resolved policy carries no slash_waterfall (%s): draining in the "
        "factory-default order, the order the policy readout reports for this frame", reason)
    if ENFORCEMENT_SLASH_WATERFALL_DEFAULTED is not None:
        try:
            ENFORCEMENT_SLASH_WATERFALL_DEFAULTED.labels(reason=reason).inc()
        except Exception:  # noqa: BLE001 — metrics never break enforcement
            pass
    return copy.deepcopy(DEFAULT_POLICY_JSON["slash_waterfall"])


async def load_order(db) -> List[Dict[str, Any]]:
    """The order this registry runs, from its resolved policy; the factory default when the policy cannot be read
    (said and counted by order_for), so an unreadable row never switches the money half of enforcement off."""
    from . import reputation_bond as rb
    try:
        policy = await rb.policy_json(db)
    except Exception as e:  # noqa: BLE001
        logger.error("[SlashOrder] the enforcement policy could not be read (%s): the factory-default order", e)
        policy = {}
    return order_for(policy)


def enabled(step: Any) -> bool:
    """A step drains unless it says `"enabled": false` (a frame can keep a step configured and switched off)."""
    return isinstance(step, dict) and step.get("enabled", True) is not False


def units(value: Any) -> Decimal:
    """Whole units, never below zero (a slash amount is a whole number of units on every path)."""
    try:
        d = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(0)
    if not d.is_finite() or d <= 0:
        return Decimal(0)
    return d.to_integral_value(rounding=ROUND_FLOOR)


def cap(requested: Decimal, step: Dict[str, Any]) -> Decimal:
    """What a step may take: its `max_percent` of the requested amount, in whole units."""
    try:
        pct = Decimal(str(step.get("max_percent", 100)))
    except (InvalidOperation, TypeError, ValueError):
        pct = Decimal(100)
    pct = min(max(pct, Decimal(0)), Decimal(100))
    return units(requested * pct / Decimal(100))


def lock_break(take: Decimal, locked: Decimal) -> Tuple[Decimal, Decimal, Decimal]:
    """(released, penalty, net) to give `take` to a slash from `locked` units: force_unstake_for_slash's arithmetic in
    whole units. The penalty (10% of what is released) comes on top of the slash, so `net` covers `take` whenever
    lock_capacity(locked) does."""
    from .force_unstake import FORCE_UNSTAKE_PENALTY_RATE as rate
    released = min(units(Decimal(str(take)) / (1 - rate)), units(locked))
    penalty = units(released * rate)
    return released, penalty, released - penalty


def lock_capacity(locked: Decimal) -> Decimal:
    """The most `locked` units can give a slash: all of them released, less the penalty on them."""
    whole = units(locked)
    return lock_break(whole, whole)[2] if whole > 0 else Decimal(0)


def move_key(ref: str, *parts: str) -> str:
    """One Idempotency-Key per move, deterministic, so a repeat of the slash moves nothing twice. A key that would not
    fit keeps its start and a digest of the whole."""
    key = "-".join([ref, *[p for p in parts if p]])
    if len(key) <= _KEY_MAX:
        return key
    return f"{ref[:60]}-h{hashlib.sha256(key.encode()).hexdigest()[:48]}"


# ── the TEG ──────────────────────────────────────────────────────────────────────────────────────────────────────────

async def read_balances(did: str) -> Tuple[Decimal, Decimal]:
    """(liquid, locked) as the TEG holds them. Raises when the TEG cannot be read: the step then takes nothing."""
    return await get_teg_client().get_balances_admin(did)


@dataclass
class Receive:
    ok: bool
    unknown: bool = False
    error: str = ""
    tx_id: str = ""
    new_source_balance: Optional[Decimal] = None


def _never_sent(e: BaseException) -> bool:
    from .payout_outcome import never_sent
    return never_sent(e)


async def move_to_treasury(source_did: str, amount: Decimal, *, key: str, reason: str, reference_id: str) -> Receive:
    """`amount` from `source_did` to the treasury through the TEG's /admin/treasury/receive (fee-free, delta 0), under
    `key`. §DOCSFIX D6-441: an answer other than a confirmation does not say the move failed once the request reached
    the TEG (a timeout after the request went out, a 5xx, the key still held by the first request, a 400 "Treasury
    receive failed" for an error after its transfer committed). The TEG is asked once more under the same key: its
    record answers a move it already made (it never debits twice), refuses again what it refused, and makes a move that
    never ran. A move still unconfirmed after that is not counted, and a lost answer says its outcome is not known. A
    request that never reached the TEG (no connection) is not asked again."""
    from .ledger_unavailable import ledger_refusal
    url = f"{settings.TEG_API_BASE_URL.rstrip('/')}/api/v1/admin/treasury/receive"
    body = {"source_agent_id": source_did, "amount": str(amount), "reason": reason, "reference_id": reference_id}
    headers = {"Authorization": f"Bearer {settings.TEG_ADMIN_API_KEY}", "Content-Type": "application/json",
               "Idempotency-Key": key}
    error, unknown = "", False
    for ask in (1, 2):
        reached = True
        try:
            async with httpx.AsyncClient(timeout=15.0, verify=get_httpx_verify()) as client:
                resp = await client.post(url, json=body, headers=headers)
        except Exception as e:  # noqa: BLE001
            reached = not _never_sent(e)
            if reached or ask == 1:
                error = type(e).__name__
            if reached:
                unknown = True
            # a second ask that never reached the TEG learns nothing: a first answer that was lost stays unknown
            logger.error("[SlashOrder] treasury receive of %s from %s (ask %s): %s", amount, source_did, ask, e)
        else:
            if resp.status_code in (200, 201):
                data: Dict[str, Any] = {}
                try:
                    data = resp.json() or {}
                except Exception:  # noqa: BLE001 — the TEG moved the units; the cached balance can wait
                    pass
                nsb = None
                try:
                    if data.get("new_source_balance") is not None:
                        nsb = Decimal(str(data.get("new_source_balance")))
                except (InvalidOperation, TypeError, ValueError):
                    nsb = None
                return Receive(ok=True, tx_id=str(data.get("transaction_id") or ""), new_source_balance=nsb)
            error = f"HTTP {resp.status_code}"
            if ledger_refusal(resp) is not None:
                error += " (the ledger cannot record it right now; nothing moved)"
                unknown = False
            else:
                unknown = resp.status_code >= 500 or resp.status_code == 409
            logger.error("[SlashOrder] treasury receive of %s from %s refused (ask %s): %s %s", amount, source_did,
                         ask, resp.status_code, str(getattr(resp, "text", ""))[:200])
        if not reached:
            break
    if unknown:
        error = f"{error}; outcome not known, it may have moved the units"
    return Receive(ok=False, unknown=unknown, error=error)


# ── the cascade ──────────────────────────────────────────────────────────────────────────────────────────────────────

def cascade_refusal(developer: Any) -> Optional[str]:
    """Why a developer's other agents are not part of a cascade, or None when they are."""
    if developer is None:
        return "its developer is not on this registry"
    if getattr(developer, "agents_unlisted_by_default", False):
        return "a service account (developers.agents_unlisted_by_default)"
    if getattr(developer, "is_admin", False) or any(getattr(developer, f, False) for f in ADMIN_FLAGS):
        return "an administrator's account (its agents are the frame's own)"
    if getattr(developer, "is_federation_shadow", False):
        return "a federation shadow (a foreign developer's mirror)"
    if getattr(developer, "deleted_at", None) is not None:
        return "a deleted account"
    return None


def _held(agent: Any) -> Decimal:
    """The registry's cached holding of an agent, used only to ORDER the cascade (what it can give is read from the TEG)."""
    total = Decimal(0)
    for attr in ("liquid_balance", "staked_balance", "reputation_bond_amount"):
        try:
            total += Decimal(str(getattr(agent, attr, 0) or 0))
        except (InvalidOperation, TypeError, ValueError):
            pass
    return total


_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _created(agent: Any) -> datetime:
    c = getattr(agent, "created_at", None)
    if not isinstance(c, datetime):
        return _EPOCH
    return c if c.tzinfo else c.replace(tzinfo=timezone.utc)


def cascade_statement(agent: Any):
    """The defendant's developer's other agents on this registry, in the cascade's order (the most held first, then
    the oldest), not deleted and no system DID, at most CASCADE_MAX_AGENTS."""
    held = (func.coalesce(Agent.liquid_balance, 0) + func.coalesce(Agent.staked_balance, 0)
            + func.coalesce(Agent.reputation_bond_amount, 0))
    return (select(Agent)
            .where(Agent.creator_developer_id == agent.creator_developer_id,
                   Agent.did != agent.did,
                   Agent.status != "revoked",
                   Agent.did.notlike(SYSTEM_DID_PREFIX + "%"))
            .order_by(held.desc(), Agent.created_at.asc(), Agent.id.asc())
            .limit(CASCADE_MAX_AGENTS))


async def cascade_agents(db, agent: Any) -> Tuple[Optional[str], List[Any]]:
    """(why there is no cascade, or None; the agents it asks, in order)."""
    res = await db.execute(select(Developer).where(Developer.id == agent.creator_developer_id))
    refusal = cascade_refusal(res.scalar_one_or_none())
    if refusal:
        return refusal, []
    rows = list((await db.execute(cascade_statement(agent))).scalars().all())
    # the statement's rule, applied again where it is read: the order is part of the rule, whatever answered the query
    rows = [a for a in rows
            if a.did != agent.did and (getattr(a, "status", None) or "active") != "revoked"
            and not str(a.did).startswith(SYSTEM_DID_PREFIX)
            and getattr(a, "creator_developer_id", None) == agent.creator_developer_id]
    rows.sort(key=lambda a: (-_held(a), _created(a), getattr(a, "id", 0) or 0))
    return None, rows[:CASCADE_MAX_AGENTS]


# ── the drain ────────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class Move:
    """One step's part in a slash: what it was asked, what it moved (units the slash counts), and why not."""
    agent_did: str
    source: str
    asked: Decimal
    key: str
    cascade: bool = False
    sent: Decimal = Decimal(0)        # what the step asked the TEG to move (its capacity read from the TEG)
    moved: Decimal = Decimal(0)
    penalty: Decimal = Decimal(0)     # stake: the lock-break penalty that went to the treasury on top of the slash
    tx_id: str = ""
    note: str = ""
    failed: bool = False              # a move the TEG did not confirm (refused, or its answer was lost)
    unknown: bool = False             # its answer was lost: it may have moved the units

    def plan_entry(self) -> Dict[str, Any]:
        entry: Dict[str, Any] = {"source": CASCADE if self.cascade else self.source,
                                 "requested": str(self.asked), "absorbed": str(self.moved)}
        if self.cascade:
            entry["agent_did"] = self.agent_did
            entry["via"] = self.source
        if self.penalty:
            entry["penalty"] = str(self.penalty)
        if self.note:
            entry["note"] = self.note
        return entry


@dataclass
class Drained:
    requested: Decimal
    mode: str
    order: List[Dict[str, Any]]
    moves: List[Move] = field(default_factory=list)
    cascade_on: bool = False
    cascade_refused: Optional[str] = None
    cascade_asked: int = 0

    @property
    def moved(self) -> Decimal:
        return sum((m.moved for m in self.moves), Decimal(0))

    @property
    def shortfall(self) -> Decimal:
        return max(self.requested - self.moved, Decimal(0))

    @property
    def failed(self) -> List[Move]:
        return [m for m in self.moves if m.failed]

    @property
    def teg_error(self) -> str:
        return "; ".join(m.note for m in self.failed if m.note)

    @property
    def unconfirmed(self) -> Decimal:
        """The units the TEG was asked to move and did not confirm."""
        return sum((m.sent - m.moved for m in self.failed), Decimal(0))

    def plan(self) -> List[Dict[str, Any]]:
        return [m.plan_entry() for m in self.moves]

    def sources(self) -> str:
        """The steps this slash drained, in words, for the record."""
        names = [SOURCE_WORDS.get(s.get("source"), str(s.get("source"))) for s in self.order
                 if enabled(s) and (s.get("source") in OWN_SOURCES or (s.get("source") == CASCADE))]
        return ", ".join(names) or "no step"


@dataclass
class _Ctx:
    db: Any
    ref: str
    reason: str
    reference_id: str
    why: str
    actor: str
    mode: str
    slash_of: str
    liquid_key: Optional[str]
    enforcement_action_id: Any
    emitter: Any

    def key(self, did: str, source: str, cascade: bool) -> str:
        if cascade:
            return move_key(self.ref, "cascade", did, source)
        if source == "liquid" and self.liquid_key:
            return self.liquid_key
        return move_key(self.ref, source)


async def drain(db, agent: Any, amount: Any, *, ref: str, reason: str, reference_id: str, actor: str,
                why: str = "", mode: str = "enforce", liquid_key: Optional[str] = None,
                enforcement_action_id: Any = None, emitter: Any = None) -> Drained:
    """Drain `amount` from `agent` in this registry's slash order (see the module's text). mode "enforce" moves the
    units; "shadow" reads the same capacities and moves nothing. Never raises for a step: a step that cannot be read or
    is refused takes nothing and says why, and the next step drains."""
    order = await load_order(db)
    requested = units(amount)
    out = Drained(requested=requested, mode=mode, order=order)
    own = [s for s in order if enabled(s) and s.get("source") in OWN_SOURCES]
    cascade = next((s for s in order if enabled(s) and s.get("source") == CASCADE), None)
    out.cascade_on = cascade is not None
    ctx = _Ctx(db=db, ref=ref, reason=reason, reference_id=reference_id, why=why or reason, actor=actor, mode=mode,
               slash_of=agent.did, liquid_key=liquid_key, enforcement_action_id=enforcement_action_id,
               emitter=emitter if emitter is not None else get_event_emitter())
    left = await _drain_agent(ctx, agent, own, requested, requested, out, cascade=False)
    if cascade is not None and left > 0:
        budget = min(left, cap(requested, cascade))
        try:
            out.cascade_refused, others = await cascade_agents(db, agent)
        except Exception as e:  # noqa: BLE001
            out.cascade_refused, others = f"the owner's other agents could not be read: {type(e).__name__}", []
            logger.error("[SlashOrder] %s: the cascade's agents could not be read: %s", ref, e)
        for other in others:
            if budget <= 0:
                break
            out.cascade_asked += 1
            budget = await _drain_agent(ctx, other, own, requested, budget, out, cascade=True)
    logger.log(logging.INFO if mode == "enforce" else logging.WARNING,
               "[SlashOrder] %s (%s) %s: %s of %s from %s, shortfall %s, plan=%s", ref, mode,
               "TOOK" if mode == "enforce" else "WOULD TAKE", out.moved, requested, agent.did, out.shortfall, out.plan())
    return out


async def _drain_agent(ctx: _Ctx, agent: Any, steps: Sequence[Dict[str, Any]], requested: Decimal, budget: Decimal,
                       out: Drained, *, cascade: bool) -> Decimal:
    """Drain one agent through `steps`; returns the budget left."""
    balances: Optional[Tuple[Decimal, Decimal]] = None
    for step in steps:
        if budget <= 0:
            break
        source = step.get("source")
        take = min(budget, cap(requested, step))
        if take <= 0:
            continue
        move = Move(agent_did=agent.did, source=source, asked=take, key=ctx.key(agent.did, source, cascade),
                    cascade=cascade)
        out.moves.append(move)
        if source == "bond":
            await _take_bond(ctx, agent, move)
        else:
            if balances is None:
                try:
                    balances = await read_balances(agent.did)
                except Exception as e:  # noqa: BLE001
                    move.note = f"the TEG's balance could not be read ({type(e).__name__})"
                    logger.error("[SlashOrder] %s: %s's balance could not be read: %s", ctx.ref, agent.did, e)
                    continue
            if source == "stake":
                balances = await _take_stake(ctx, agent, move, balances)
            else:
                await _take_liquid(ctx, agent, move, balances)
                if balances is not None:
                    balances = (balances[0] - move.moved, balances[1])
        budget -= move.moved
        if move.moved > 0:
            if ENFORCEMENT_SLASH_WATERFALL is not None:
                try:
                    ENFORCEMENT_SLASH_WATERFALL.labels(mode=ctx.mode, source=CASCADE if cascade else str(source)).inc()
                except Exception:  # noqa: BLE001
                    pass
            if ctx.mode == "enforce":
                await _record(ctx, move)
    return budget


async def _take_bond(ctx: _Ctx, agent: Any, move: Move) -> None:
    from . import reputation_bond as rb
    try:
        bond = await rb.load_bond(ctx.db, agent.did)
    except Exception as e:  # noqa: BLE001
        move.note = f"the bond could not be read ({type(e).__name__})"
        return
    held = units(bond.amount) if bond is not None and bond.status in rb.BONDED else Decimal(0)
    give = min(move.asked, held)
    if give <= 0:
        move.note = "no reputation bond held"
        return
    if ctx.mode != "enforce":
        move.moved = give
        return
    try:
        move.moved = units(await rb.forfeit(ctx.db, agent, amount=give, reason=ctx.why, ref=move.key, actor=ctx.actor))
    except Exception as e:  # noqa: BLE001
        move.note = f"the bond was not forfeited ({type(e).__name__})"
        logger.error("[SlashOrder] %s: forfeit of %s from %s failed: %s", ctx.ref, give, agent.did, e)


async def _take_stake(ctx: _Ctx, agent: Any, move: Move,
                      balances: Tuple[Decimal, Decimal]) -> Optional[Tuple[Decimal, Decimal]]:
    """The lock step; returns the balances after it (None when they must be read again)."""
    liquid, locked = balances
    give = min(move.asked, lock_capacity(locked))
    if give <= 0:
        move.note = "nothing locked on the TEG"
        return balances
    released, penalty, net = lock_break(give, locked)
    move.sent = give
    if ctx.mode != "enforce":
        move.moved, move.penalty = give, penalty
        return liquid + (net - give), locked - released
    from .force_unstake import ForceUnstakeError, get_force_unstake_service
    try:
        res = await get_force_unstake_service().force_unstake_for_slash(
            db=ctx.db, agent_did=agent.did, required_amount=int(give),
            enforcement_action_id=ctx.enforcement_action_id, slash_ref=ctx.ref,
            reason=ctx.why, slash_key=move.key, treasury_reason=ctx.reason, reference_id=ctx.reference_id)
    except ForceUnstakeError as e:
        move.note = f"the locks were not released: {e}"
        move.failed = True
        return None
    except Exception as e:  # noqa: BLE001
        move.note = f"the locks were not released ({type(e).__name__})"
        move.failed = True
        logger.error("[SlashOrder] %s: force-unstake of %s failed: %s", ctx.ref, agent.did, e)
        return None
    move.moved = units(res.get("slashed") or 0)
    move.penalty = units(res.get("penalty_moved") or 0)
    move.tx_id = str(res.get("slash_transaction_id") or "")
    if res.get("slash_error"):
        move.note = str(res["slash_error"])
        move.failed = move.moved <= 0
        move.unknown = bool(res.get("slash_unknown"))
    return None


async def _take_liquid(ctx: _Ctx, agent: Any, move: Move, balances: Tuple[Decimal, Decimal]) -> None:
    give = min(move.asked, units(balances[0]))
    if give <= 0:
        move.note = "nothing liquid on the TEG"
        return
    move.sent = give
    if ctx.mode != "enforce":
        move.moved = give
        return
    got = await move_to_treasury(agent.did, give, key=move.key, reason=ctx.reason, reference_id=ctx.reference_id)
    if not got.ok:
        move.note, move.failed, move.unknown = got.error, True, got.unknown
        return
    move.moved, move.tx_id = give, got.tx_id
    try:
        if got.new_source_balance is not None:
            agent.liquid_balance = got.new_source_balance
        else:
            agent.liquid_balance = max(Decimal(str(agent.liquid_balance or 0)) - give, Decimal(0))
    except Exception:  # noqa: BLE001 — the cached balance can wait for the next sync
        pass


async def _record(ctx: _Ctx, move: Move) -> None:
    """One SlashMoved per move: an audit record of which slash moved whose units from which step (the TEG's own
    ledger record counts the units: the policy row skips it in the projection)."""
    if ctx.emitter is None:
        return
    from ..core.frame_currency import frame_currency
    data = {"slash_ref": ctx.ref, "slash_of": ctx.slash_of, "agent_did": move.agent_did, "source": move.source,
            "cascade": move.cascade, "amount": str(move.moved), "penalty": str(move.penalty), "key": move.key,
            "transaction_id": move.tx_id, "reason": ctx.reason, "reference_id": ctx.reference_id, "actor": ctx.actor,
            "currency": frame_currency(),
            "note": "audit only: the TEG's own ledger record of the move counts the units"}
    try:
        ok = await ctx.emitter.emit(event_type="SlashMoved", aggregate_id=move.agent_did, data=data,
                                    idempotency_key=f"slashmoved-{move.key}")
        if ok is False:
            logger.error("[SlashOrder] SlashMoved emit returned False (key %s)", move.key)
    except Exception as e:  # noqa: BLE001 — the units moved; the audit record must not undo the slash
        logger.error("[SlashOrder] SlashMoved emit failed (key %s): %s", move.key, e)
