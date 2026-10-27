"""§OURSTATE-1 — the chat logic core (OurChat, mig 0155_chat_core).

THE LAW THIS FILE ENFORCES (law 1 of the program): chat has NO money code.
Nothing in here mints, moves, escrows or converts anything. Every economic act
in a thread is a typed CARD — a versioned jsonb envelope validated against a
CLOSED vocabulary — that doors into an EXISTING rail; the service-call leg in
routers/chat.py composes the proven `/a2a-payment/buy` loop over loopback with
the CALLER's own JWT and writes the honest outcome back as a card. If a step in
here ever seems to need a money path, the step is wrong.

Structure: the decision logic (card validation, pair keys, state machine,
unread math, previews) is PURE and unit-tested without a database; the DB
functions below it are thin executors. Ordering is a per-conversation total
order: `seq` comes from an atomic `UPDATE conversations SET last_seq=last_seq+1
… RETURNING`, so there is a single writer per thread by construction. Message
identity for retries is UNIQUE(conversation, sender, client_ref) — the offline
queue and every resend are idempotent at the schema, not by convention.

Rate limits are DIRECT Redis INCR gates, per PRINCIPAL, shared across all 32+
workers — deliberately not slowapi (its key is the remote address, which is
wrong for chat behind the proxy, and a per-worker in-process limiter is the
exact §1.3 defect class this program is on record refusing to repeat). Redis
down ⇒ gates fail OPEN: they are abuse control, never availability control.

Delivery (fan_out_message) runs POST-COMMIT only (§ESDUP law: never announce
what might still roll back): WS topic per recipient developer, notify() as the
offline fallback, `chat.message.received` webhook for agent participants over
the production-proven retry rail.
"""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy import select, text as sa_text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry.models import (
    ChatBlock,
    ChatMessage,
    Conversation,
    ConversationParticipant,
)

logger = logging.getLogger(__name__)

# D6-826 (agentvault2-aa, 2026-10-26): every chat delivery ran as asyncio.create_task(...) with its result dropped. The
# event loop keeps only a weak reference to a task, so a task nothing else holds can be collected before it finishes,
# and an exception in one was never read (the create_task wrappers logged at debug, which no registry prints). The
# federation suite's chat_g1 control legs met exactly that shape: the host stored the message, the owner's hook was never
# told, and the record still held nothing minutes later. Every chat background task now goes through spawn().
_BACKGROUND: Set["asyncio.Task[Any]"] = set()
NOTIFY_BOUND_S = 30.0   # one developer's offline notice (push, in-app, mail) may take this long before it is given up


def _spawned_done(task: "asyncio.Task[Any]", what: str) -> None:
    _BACKGROUND.discard(task)
    if task.cancelled():
        logger.info("[CHAT] %s: cancelled", what)
        return
    exc = task.exception()   # retrieved here, so it is never "never retrieved"
    if exc is not None:
        logger.warning("[CHAT] %s failed: %s: %s", what, type(exc).__name__, exc)


def spawn(coro: Awaitable[Any], what: Optional[str] = None) -> "asyncio.Task[Any]":
    """Run `coro` in the background, held until it is done, its failure logged at WARNING under `what` (default: the
    coroutine's name). A task that raised and a task that never ran then read apart in the registry's log."""
    label = what or str(getattr(coro, "__qualname__", None) or "a chat background task")
    task = asyncio.create_task(coro)
    _BACKGROUND.add(task)
    task.add_done_callback(lambda t: _spawned_done(t, label))
    return task


def deliver(conv_id: str, conv_kind: str, message: dict, recipients: List[dict], sender_name: str,
            *, is_ping: bool = False, sender_owner_dev_id: Optional[int] = None) -> "asyncio.Task[Any]":
    """fan_out_message() in the background through spawn(), named by the message and its recipients' kinds."""
    kinds = sorted({str(r.get("ptype") or "?") for r in recipients or []})
    return spawn(fan_out_message(conv_id, conv_kind, message, recipients, sender_name, is_ping=is_ping,
                                 sender_owner_dev_id=sender_owner_dev_id),
                 what=f"the delivery of message {message.get('id')} (seq {message.get('seq')}) in {conv_id} "
                      f"to {len(recipients or [])} recipient(s) ({', '.join(kinds) or 'none'})")


# §TWOAGENT #26 (2026-09-23): the refusal used to promise that federation would carry a dm to such an agent, which is not
# true for an AGENT: federated threads (CHAT_FEDERATION_ENABLED) are person-to-person, by handle, and seat developers only. The only
# door to an agent on another registry is its service, through an agent_service thread. Say that, and only that.
FOREIGN_AGENT_DM_REFUSAL = ("this agent lives on another registry, and a direct message cannot reach an agent on "
                            "another registry; its services can be called now: open an agent_service conversation "
                            "and make a service call")

# ---------------------------------------------------------------------------
# Constants (the frozen v1 contract — STRATEGY_2026-08-24 §4/§9)
# ---------------------------------------------------------------------------

BODY_MAX_BYTES = 4096          # §9: body 4KB
CARD_MAX_BYTES = 8192          # §9: card 8KB
PREVIEW_LEN = 160
PAGE_MAX = 50
LIST_MAX = 50
SYNC_MAX = 200
SERVICE_INFLIGHT_STALE_S = 180  # a crashed worker's flag ages out, never bricks a thread

PAIR_KINDS = ("dm", "agent_service")

# The closed v1 card vocabulary. CORE enables the pay family + agent.card for
# clients; service.* is authored ONLY by the service-call rail (a client posting
# "I called this service" would be a fabricated record — law 4 is receipts, not
# screenshots). The remaining v1 types are RECOGNIZED but refused until their
# phase ships, with a named reason instead of a generic error.
CLIENT_POSTABLE_CARDS = frozenset({
    "pay.request", "pay.receipt", "agent.card",
    # §OURSTATE-2 WORK cards — pointers into the contracts / guild rails.
    "contract.offer", "guild.order",
    # §OURSTATE-5e media — a POINTER to a stored attachment, never bytes. The
    # upload happens on its own endpoint with its own limits; the card only
    # says WHICH file, so a thread read costs the same whatever people send.
    "media",
    # §OURSTATE-5f applet — a DECLARATIVE form description whose single action
    # is a door this app already has. Never markup, never a URL, and it fires
    # nothing: it fills a door and a human presses it.
    "applet",
    # §OURCHAT-ORG exchange.listing — a POINTER at a share listing that already
    # trades on this registry's AGORA venue. Same discipline as the WORK cards:
    # the card names a symbol, the door opens the EXISTING order ticket with it
    # prefilled, and the order is placed on the exchange rail under the actor's
    # own token. Chat still contains no money code; it contains an address.
    "exchange.listing",
    # §DEALTHREADS (O-D, 2026-08-29) — the two CLIENT-POSTABLE halves of the
    # engagement family: structured NEGOTIATION text. Nothing trusts an amount
    # on either of them — a proposal is a draft the engage rail re-mints, and a
    # counter supersedes it (refs.supersedes keeps the whole history). The four
    # rail-only siblings live in RAIL_ONLY_CARDS below.
    "engagement.proposal", "engagement.counter",
})
RAIL_ONLY_CARDS = frozenset({
    "service.call", "service.result",
    # §SHOWCASESTOCKS share.certificate — an Ed25519 attestation that a holding
    # exists, minted by the REGISTRY on the certificate rail and posted from
    # there. RAIL-ONLY for the same reason `service.result` is: a certificate a
    # client could author is not evidence of anything, and letting one be typed
    # would make every real one worthless too.
    "share.certificate",
    # §CHATDESK C5 org.work.receipt — the firm's room hears what the firm's
    # money did (treasury fund/remit, dividends, guild settlements to the
    # firm). RAIL-ONLY for the certificate's reason: a receipt a client could
    # author is not evidence, and one forgeable makes every real one worthless.
    "org.work.receipt",
    # §DEALTHREADS (O-D) — the CONTRACT transitions as thread cards, posted by
    # ONE emitter (services/deal_thread_events.py) as the money actually moves:
    #   engagement.offer     the offer MINTED (engage_agent, open_thread only)
    #   engagement.accepted  provider accepted; escrow held
    #   engagement.milestone provider delivered; client reviews
    #   engagement.settled   a release settled (terminal receipt per milestone)
    # RAIL-ONLY for the receipt's reason — a transition a client could author
    # is not a record of anything.
    "engagement.offer", "engagement.accepted",
    "engagement.milestone", "engagement.settled",
})
# §DOCSFIX D6-556 (2026-10-16): the rail that writes each rail-only card, and what its card records, for the refusal
# a client meets when it types one. The refusal named the service-call rail for all eight.
RAIL_ONLY_WRITERS = {
    "service.call": ("the service-call rail", "a service record"),
    "service.result": ("the service-call rail", "a service record"),
    "share.certificate": ("the registry's certificate rail", "a holding certificate"),
    "org.work.receipt": ("an organization's money rails", "a receipt of the organization's money"),
    "engagement.offer": ("the contract rail", "a contract transition"),
    "engagement.accepted": ("the contract rail", "a contract transition"),
    "engagement.milestone": ("the contract rail", "a contract transition"),
    "engagement.settled": ("the contract rail", "a contract transition"),
}
LATER_PHASE_CARDS = frozenset({"topup.offer"})
# The one value that means "resolved, and open". Anything else — including the
# absence of a decision — refuses, because "nobody checked" must never be
# indistinguishable from "allowed".
FIAT_DOOR_OPEN = "__open__"
KNOWN_CARD_TYPES = CLIENT_POSTABLE_CARDS | RAIL_ONLY_CARDS | LATER_PHASE_CARDS

# Redis-shared, per-principal abuse gates (§9 limits).
RL_MSG_LIMIT, RL_MSG_WINDOW_S = 60, 60            # 60 messages / minute / principal
RL_STRANGER_LIMIT, RL_STRANGER_WINDOW_S = 20, 86400   # 20 new stranger-threads / day
RL_PING_THREAD_LIMIT, RL_PING_THREAD_WINDOW_S = 1, 600  # 1 ping / 10 min / thread
RL_PING_DAY_LIMIT, RL_PING_DAY_WINDOW_S = 30, 86400     # 30 pings / day / principal


class ChatError(Exception):
    """Carries an HTTP status + a named, human-readable reason. The router
    translates; the service never imports FastAPI."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


# ---------------------------------------------------------------------------
# Pure decision logic (unit-tested without a database)
# ---------------------------------------------------------------------------

def principal_key(ptype: str, pid: Any) -> str:
    """Canonical principal key: 'dev:{id}' | 'agt:{did lowercased}' |
    'rem:{handle@registry}' (§OURSTATE-3b — a principal on a PEER registry,
    which this registry can address but never authenticate)."""
    if ptype == "developer":
        return f"dev:{int(pid)}"
    if ptype == "agent":
        return f"agt:{str(pid).lower()}"
    if ptype == "remote":
        return f"rem:{str(pid)}"
    raise ValueError(f"unknown ptype {ptype!r}")


def sender_key_of(m: Any) -> Optional[str]:
    """The principal key of a message's sender, for the three ptypes a person or an agent can be; None for a system
    row or an id this module cannot key (§TWOAGENT V0441: the thread read names remote senders through this)."""
    if getattr(m, "sender_ptype", None) in ("developer", "agent", "remote") and getattr(m, "sender_id", None):
        try:
            return principal_key(m.sender_ptype, m.sender_id)
        except (ValueError, TypeError):
            return None
    return None


def part_key(p: Any) -> str:
    """The principal key OF A PARTICIPANT ROW — the one place that knows which
    column carries the id for each ptype.

    It exists because that expression was repeated at six call sites, and
    §OURSTATE-3b added a third ptype: every copy that read
    `developer_id if ptype == 'developer' else agent_did` silently produced
    `rem:None` for a remote row. One shared predicate, asked everywhere
    (the §FANOUTFIX rule)."""
    if p.ptype == "developer":
        return principal_key("developer", p.developer_id)
    if p.ptype == "agent":
        return principal_key("agent", p.agent_did)
    return principal_key("remote", getattr(p, "remote_key", None) or "")


def counterparty_fields(p: Any) -> Dict[str, Any]:
    """The counterparty a list row or a thread names, for all three ptypes (one place; four call sites asked it by hand).
    §TWOAGENT G1 household/V0436: a principal on a peer registry carries its ADDRESS (`remote_key`), the one thing a
    client needs to block it; without it a remote counterparty could only be blocked by reading a message's sender_id."""
    return {"ptype": p.ptype, "developer_id": p.developer_id, "agent_did": p.agent_did,
            "remote_key": getattr(p, "remote_key", None) if p.ptype == "remote" else None}


def _seated_order(p: Any) -> Tuple[float, str]:
    j = getattr(p, "joined_at", None)
    try:
        t = j.timestamp() if j is not None else 0.0
    except Exception:  # noqa: BLE001
        t = 0.0
    return (t, str(getattr(p, "id", "") or ""))


def pick_counterparty(kind: Optional[str], parts: Iterable[Any], my_keys: Set[str], actor_key: str, *,
                      pair_key: Optional[str] = None, created_by: Optional[str] = None) -> Tuple[Optional[Any], bool]:
    """The participant a list row or a thread names as its counterparty, and whether it is the caller's own household.

    §TWOAGENT V0441: both call sites took "the first participant that is not me" from rows read with no ORDER BY. In a
    two-principal thread that is the other end whatever the order, but a household join (V0436) seats a THIRD principal,
    the other side's owner. ASIA's mirror of the Scrivener's thread then named EU's owner (`dev:12@https://eu…`) in the
    header and the list row instead of the agent the thread is with. The thread records who it is with, so ask it first:
    the pair of a local dm or service thread, or the principal who started a mirrored one. Otherwise the EARLIEST-seated
    participant that is not the caller's (ordered by joined_at, then id), so the answer never depends on row order.
    A room has members, never a counterparty (the list also leaves a support thread's row unnamed; it asks that itself)."""
    if kind == "org":
        return None, False
    ordered = sorted(parts, key=_seated_order)
    by_key: Dict[str, Any] = {}
    for p in ordered:
        by_key.setdefault(part_key(p), p)
    recorded: List[str] = []
    if pair_key and "|" in pair_key:
        recorded = [k for k in pair_key.split("|")[1:] if k]
    elif created_by:
        recorded = [created_by]
    for k in recorded:
        if k not in my_keys and k in by_key:
            return by_key[k], False
    for p in ordered:
        if part_key(p) not in my_keys:
            return p, False
    # Both sides are the caller's household (one of your agents buying from another of yours is a real transaction):
    # name the side that is not the CALLER.
    for k in recorded:
        if k != actor_key and k in by_key:
            return by_key[k], True
    for p in ordered:
        if part_key(p) != actor_key:
            return p, True
    return None, False


def created_by_key(ptype: Optional[str], pid: Optional[str]) -> Optional[str]:
    """The principal key of whoever started a conversation, or None when the row does not name one this module keys."""
    if not ptype or not pid or ptype not in ("developer", "agent", "remote"):
        return None
    try:
        return principal_key(ptype, pid)
    except (ValueError, TypeError):
        return None


def pair_key(kind: str, key_a: str, key_b: str) -> str:
    """Canonical unordered pair key, kind-prefixed so a dm and an agent_service
    thread between the same pair never collide. This is the one-thread-per-
    counterparty dedup (a deliberate small widening of the plan: the same
    UNIQUE column also dedupes agent_service threads, because two parallel
    threads to the same service agent is a wart, not a feature)."""
    prefix = "dm" if kind == "dm" else "svc"
    return prefix + "|" + "|".join(sorted((key_a, key_b)))


def validate_body(body: Optional[str]) -> Optional[str]:
    """Returns a refusal reason or None."""
    if body is None:
        return None
    if not isinstance(body, str):
        return "body must be a string"
    if len(body.encode("utf-8", errors="ignore")) > BODY_MAX_BYTES:
        return f"body exceeds the {BODY_MAX_BYTES // 1024}KB limit"
    return None


def validate_card(card: Any, *, rail_author: bool = False,
                  fiat_door: Optional[str] = None) -> Optional[str]:
    """Validate a card envelope against the CLOSED v1 vocabulary.

    Returns a refusal reason or None. `rail_author=True` is set only by the
    service-call rail, which may write service.call / service.result.
    """
    if not isinstance(card, dict):
        return "card must be an object"
    unknown_keys = set(card.keys()) - {"v", "type", "data", "refs"}
    if unknown_keys:
        return f"card envelope carries unknown keys: {sorted(unknown_keys)}"
    if card.get("v") != 1:
        return "card.v must be 1 (the only card version this registry speaks)"
    ctype = card.get("type")
    if not isinstance(ctype, str) or ctype not in KNOWN_CARD_TYPES:
        return f"unknown card type {str(ctype)[:40]!r} — the vocabulary is closed"
    if ctype in LATER_PHASE_CARDS:
        # §OURSTATE-5c — `topup.offer` IS the fiat door. The validator stays
        # pure: the three locks are read once by the async caller and the
        # verdict arrives here as a value. Three states, kept distinct on
        # purpose, because collapsing the first two is how a dark feature
        # turns itself on:
        #   None            nobody resolved the door  -> refuse
        #   FIAT_DOOR_OPEN  resolved, all locks open   -> allow
        #   any other string the refusal to show       -> refuse with it
        if ctype == "topup.offer":
            if fiat_door is None:
                return "the fiat door was not resolved for this message"
            if fiat_door != FIAT_DOOR_OPEN:
                return fiat_door
            # open: fall through to the SAME structural checks every other
            # card faces. Returning here would make the money door the one
            # card type nobody validated.
        else:
            return f"card type {ctype!r} arrives in a later OurChat phase"
    if ctype in RAIL_ONLY_CARDS and not rail_author:
        rail, record = RAIL_ONLY_WRITERS.get(ctype, ("a registry rail", "a record of work or money"))
        return f"card type {ctype!r} is written only by {rail}: a client cannot author {record}"
    data = card.get("data")
    if not isinstance(data, dict):
        return "card.data must be an object"
    refs = card.get("refs")
    if refs is not None and not isinstance(refs, dict):
        return "card.refs must be an object when present"

    # Per-type required fields (strict on structure, permissive on extras).
    if ctype == "applet":
        from .chat_applet import validate_applet
        problem = validate_applet(data)
        if problem:
            return problem
    if ctype == "media":
        for f in ("attachment_id", "name", "mime", "bytes"):
            if not data.get(f):
                return f"a media card needs {f}"
        if not isinstance(data.get("bytes"), int) or data["bytes"] <= 0:
            return "media.bytes must be a positive integer"
        # A pointer cannot smuggle content: anything that looks like inline
        # data is refused HERE rather than rendered somewhere later.
        for banned in ("data", "content", "b64", "url", "src"):
            if banned in data:
                return f"a media card carries no {banned} — it points at an attachment"
    if ctype == "pay.receipt":
        # §OURSTATE-6 — a cross-frame receipt states what ARRIVED as well as
        # what was debited. Both halves or neither: an arrival amount with no
        # unit is the §FOREIGNACT defect, and this receipt is exactly where a
        # recipient reads their own number.
        if data.get("received_amount") is not None and not data.get("received_currency"):
            return "a receipt that states an arrival amount must name its currency"
    if ctype in ("engagement.proposal", "engagement.counter"):
        # §DEALTHREADS — structured NEGOTIATION text. A stated total is
        # DECORATION the engage rail re-reads before any money moves, but a
        # number without a unit is the §FOREIGNACT defect wherever it renders,
        # so total-and-currency come whole or not at all.
        title = data.get("title")
        if not isinstance(title, str) or not (1 <= len(title) <= 200):
            return f"{ctype}: data.title is required (1-200 chars)"
        if data.get("total") is not None:
            try:
                if Decimal(str(data["total"])) <= 0:
                    return f"{ctype}: data.total must be positive when stated"
            except (InvalidOperation, TypeError, ValueError):
                return f"{ctype}: data.total must be a decimal string"
            ccy = data.get("currency")
            if not isinstance(ccy, str) or not (1 <= len(ccy) <= 16):
                return f"{ctype}: a stated total must name its currency"
        note = data.get("note")
        if note is not None and (not isinstance(note, str) or len(note) > 2000):
            return f"{ctype}: data.note must be a string under 2000 chars"
        ms = data.get("milestones")
        if ms is not None:
            if not isinstance(ms, list) or len(ms) > 20:
                return f"{ctype}: data.milestones must be a list of at most 20 entries"
            for m in ms:
                if not isinstance(m, dict) or not isinstance(m.get("title"), str):
                    return f"{ctype}: each milestone needs a title"
        if ctype == "engagement.counter":
            sup = (refs or {}).get("supersedes")
            if not isinstance(sup, str) or not sup:
                return ("engagement.counter: refs.supersedes must name the message "
                        "it counters — the thread keeps the whole negotiation history")
    if ctype in ("engagement.offer", "engagement.accepted",
                 "engagement.milestone", "engagement.settled"):
        # Rail-authored transitions: every one names its contract; the money
        # types carry amount+currency whole (§FOREIGNACT).
        cid = data.get("contract_id")
        if not isinstance(cid, str) or not cid:
            return f"{ctype}: data.contract_id is required"
        if ctype in ("engagement.offer", "engagement.accepted", "engagement.settled"):
            amt_field = "amount" if ctype == "engagement.settled" else "total"
            try:
                if Decimal(str(data.get(amt_field))) < 0:
                    return f"{ctype}: data.{amt_field} must be >= 0"
            except (InvalidOperation, TypeError, ValueError):
                return f"{ctype}: data.{amt_field} must be a decimal string"
            ccy = data.get("currency")
            if not isinstance(ccy, str) or not (1 <= len(ccy) <= 16):
                return f"{ctype}: data.currency is required (1-16 chars)"
        if ctype in ("engagement.milestone", "engagement.settled"):
            if not isinstance(data.get("seq"), int) or data["seq"] < 1:
                return f"{ctype}: data.seq must be a positive integer"
    if ctype == "org.work.receipt":
        # §CHATDESK C5 — a rail-authored record of org money that ALREADY
        # moved. kind is its own closed vocabulary; amount+currency are
        # required whole, because a number without a unit is the §FOREIGNACT
        # defect landing in the one room where the firm reads its own books.
        from .org_room_events import RECEIPT_KINDS as _ORG_RECEIPT_KINDS
        if data.get("kind") not in _ORG_RECEIPT_KINDS:
            return "org.work.receipt: data.kind is not in the receipt vocabulary"
        try:
            if Decimal(str(data.get("amount"))) <= 0:
                return "org.work.receipt: data.amount must be positive"
        except (InvalidOperation, TypeError, ValueError):
            return "org.work.receipt: data.amount must be a decimal string"
        ccy = data.get("currency")
        if not isinstance(ccy, str) or not (1 <= len(ccy) <= 16):
            return "org.work.receipt: data.currency is required (1-16 chars)"
    if ctype in ("pay.request", "pay.receipt"):
        amount = data.get("amount")
        try:
            amt = Decimal(str(amount))
        except (InvalidOperation, TypeError, ValueError):
            return f"{ctype}: data.amount must be a decimal string"
        if amt <= 0:
            return f"{ctype}: data.amount must be positive"
        ccy = data.get("currency")
        if not isinstance(ccy, str) or not (1 <= len(ccy) <= 16):
            return f"{ctype}: data.currency is required (1-16 chars)"
    elif ctype == "agent.card":
        did = data.get("did")
        if not isinstance(did, str) or not did.startswith("did:"):
            return "agent.card: data.did must be a DID"
    elif ctype == "exchange.listing":
        # A pointer at a venue symbol, not a quote and never an order. The
        # symbol is the whole address; anything price-shaped on the card is
        # DECORATION that the ticket re-reads from the venue before a human
        # can act, because a price pasted into a conversation is stale the
        # moment it is sent and must never be what somebody trades against.
        sym = data.get("symbol")
        if not isinstance(sym, str) or not (1 <= len(sym) <= 16):
            return "exchange.listing: data.symbol must be the ticker (1-16 chars)"
        if not sym.replace("-", "").replace("_", "").isalnum():
            return "exchange.listing: data.symbol must be alphanumeric"
        name = data.get("display_name")
        if name is not None and (not isinstance(name, str) or len(name) > 120):
            return "exchange.listing: data.display_name must be a string under 120 chars"
        # An indicative price is optional, and if it is stated it names its
        # unit — the §FOREIGNACT rule, which this card is squarely inside:
        # the reader is looking at another registry's currency half the time.
        if data.get("last_price") is not None:
            try:
                if Decimal(str(data["last_price"])) < 0:
                    return "exchange.listing: data.last_price cannot be negative"
            except (InvalidOperation, TypeError, ValueError):
                return "exchange.listing: data.last_price must be a decimal string when present"
            if not isinstance(data.get("currency"), str) or not data["currency"]:
                return "exchange.listing: data.currency is required when a price is stated"
        # The refusals that keep it a pointer. A card that could carry a side
        # and a quantity would be an order slip, and a human tapping it would
        # be confirming somebody else's trade rather than composing their own.
        for banned in ("side", "qty", "quantity", "order", "url", "endpoint"):
            if banned in data:
                return (f"exchange.listing carries no {banned} — it points at a listing, "
                        "and the ticket is where a person chooses what to do")
    elif ctype == "share.certificate":
        # Minted by the rail, so this validates SHAPE rather than authority —
        # the authority is that only the rail can post it at all.
        sym = data.get("symbol")
        if not isinstance(sym, str) or not (1 <= len(sym) <= 16):
            return "share.certificate: data.symbol must be the ticker (1-16 chars)"
        try:
            if int(data.get("qty")) <= 0:
                return "share.certificate: data.qty must be a positive whole number of points"
        except (TypeError, ValueError):
            return "share.certificate: data.qty must be a positive whole number of points"
        # A quantity of something priced always names its unit (§FOREIGNACT).
        if not isinstance(data.get("currency"), str) or not data["currency"]:
            return "share.certificate: data.currency is required"
        if not isinstance(data.get("certificate_id"), str) or not data["certificate_id"]:
            return "share.certificate: data.certificate_id is required — the artifact is its identifier"
        if not isinstance(data.get("digest"), str) or len(data["digest"]) != 64:
            return "share.certificate: data.digest must be the sha256 of the signed claim"
    elif ctype in ("contract.offer", "guild.order"):
        # §OURSTATE-2 WORK cards: POINTERS, never authority. The card carries a
        # reference to an engagement that ALREADY exists on the contracts /
        # guild rails plus a human title; the doors on it act on those rails
        # with the actor's own token. Nothing here creates or moves anything,
        # which is why a client may post one: pointing at a record you are a
        # party to is not the same act as writing the record.
        ref = data.get("ref")
        if not isinstance(ref, str) or not (1 <= len(ref) <= 128):
            return f"{ctype}: data.ref must be the engagement reference (1-128 chars)"
        title = data.get("title")
        if not isinstance(title, str) or not (1 <= len(title) <= 200):
            return f"{ctype}: data.title is required (1-200 chars)"
        if data.get("amount") is not None:
            try:
                if Decimal(str(data["amount"])) < 0:
                    return f"{ctype}: data.amount cannot be negative"
            except (InvalidOperation, TypeError, ValueError):
                return f"{ctype}: data.amount must be a decimal string when present"
            if not isinstance(data.get("currency"), str) or not data["currency"]:
                return f"{ctype}: data.currency is required when an amount is stated"

    try:
        blob = json.dumps(card)
    except (TypeError, ValueError):
        return "card must be JSON-serializable"
    if len(blob.encode("utf-8", errors="ignore")) > CARD_MAX_BYTES:
        return f"card exceeds the {CARD_MAX_BYTES // 1024}KB limit"
    return None


def unread_count(last_seq: int, last_read_seq: int, hidden_before_seq: Optional[int]) -> int:
    """Unread is ALWAYS computed, never a counter column. Burn-for-me moves the
    floor: everything before hidden_before_seq no longer exists for this row."""
    floor = max(int(last_read_seq or 0), int(hidden_before_seq or 0))
    return max(0, int(last_seq or 0) - floor)


# The Requests-folder state machine. Key = (current_state, action) → new state.
# Anything not in the table is a refused transition with a named reason.
STATE_TRANSITIONS: Dict[Tuple[str, str], str] = {
    ("pending", "accept"): "active",
    ("pending", "decline"): "left",
    ("active", "leave"): "left",
    ("pending", "leave"): "left",
}


def transition_state(current: str, action: str) -> str:
    nxt = STATE_TRANSITIONS.get((current, action))
    if nxt is None:
        raise ChatError(409, f"cannot {action} a conversation you are {current!r} in")
    return nxt


def _money(data: dict, amount_key: str = "amount", ccy_key: str = "currency") -> str:
    """`"12.5 BVT"`, or `""`.

    §FOREIGNACT's law, applied to a preview: an amount is rendered ONLY when the
    card carries its OWN currency beside it. A number with no unit is a number
    nobody can act on; a number with the WRONG unit is worse than silence, and
    the frame's currency is the wrong guess for a card minted somewhere else
    (a `pay.receipt` on Frame-C legitimately says AVT). Missing either half ⇒
    the sentence simply omits the money and stays true.
    """
    amt = data.get(amount_key)
    ccy = data.get(ccy_key)
    if amt in (None, "") or not isinstance(ccy, str) or not ccy.strip():
        return ""
    s = str(amt)
    # 2.0000000000 reads as machine output; 2.5000000000 → 2.5, 2.0 → 2.
    if "." in s:
        s = s.rstrip("0").rstrip(".") or "0"
    return f"{s} {ccy.strip()}"


def _clip(s: Any, n: int) -> str:
    """A short, whole-looking fragment — never a word cut mid-character."""
    t = " ".join(str(s or "").split())
    return t if len(t) <= n else t[: n - 1].rstrip() + "\u2026"


def _card_sentence(card: dict) -> str:
    """ONE human sentence for each type in the closed v1 card vocabulary.

    §CHATCOHERE D7 (2026-09-01). This function used to return `f"[{type}]"`, so a
    thread list read `[service.result]` — the protocol's own type name, handed to a
    person. Measured on a cold start; it is the Commander's *"it might be for ai,
    not for me"* in its most literal form.

    Three rules the table keeps:
      1. Say WHAT HAPPENED, not what the record is called.
      2. Money only via `_money()` — amount and currency together, or neither.
      3. RAIL-ONLY cards read as RECORDS (“Answered”, “Signed holding”, “Settled”),
         because a receipt a human could mistake for a claim is worth nothing. A
         client-postable card never borrows that voice.

    An unknown type degrades to a readable label rather than a bracketed token, so
    a card family added tomorrow is merely plain instead of cryptic.
    """
    t = card.get("type") or "card"
    d = card.get("data") if isinstance(card.get("data"), dict) else {}
    m = _money(d)

    if t == "service.call":
        ask = _clip(d.get("ask"), 100)
        return f"Asked: {ask}" if ask else "Service call sent"
    if t == "service.result":
        paid = _money(d, "paid_amount", "paid_currency")
        if d.get("ok") is False or (d.get("error") and not d.get("ok")):
            why = _clip(d.get("error") or d.get("summary"), 90)
            return f"Not delivered \u2014 nothing charged{': ' + why if why else ''}"
        head = "Answered"
        if paid:
            head += f" \u2014 {paid} charged"
        note = _clip(d.get("summary"), 60)
        return f"{head}" if not note or note == "delivered" else f"{head} \u00b7 {note}"
    if t == "pay.request":
        memo = _clip(d.get("memo"), 60)
        head = f"Payment requested{': ' + m if m else ''}"
        return f"{head} \u00b7 {memo}" if memo else head
    if t == "pay.receipt":
        who = _clip(d.get("counterparty_name"), 40)
        head = f"Payment receipt{': ' + m if m else ''}"
        return f"{head} \u00b7 {who}" if who else head
    if t == "agent.card":
        return f"Shared an agent: {_clip(d.get('name'), 60)}" if d.get("name") else "Shared an agent"
    if t == "contract.offer":
        return f"Contract offer: {_clip(d.get('title'), 90)}" if d.get("title") else "Contract offer"
    if t == "guild.order":
        head = f"Guild job: {_clip(d.get('title'), 70)}" if d.get("title") else "Guild job"
        return f"{head} \u00b7 {m}" if m else head
    if t == "media":
        return f"Sent a file: {_clip(d.get('name'), 60)}" if d.get("name") else "Sent a file"
    if t == "applet":
        return f"Form to fill in: {_clip(d.get('title'), 70)}" if d.get("title") else "Form to fill in"
    if t == "exchange.listing":
        sym = _clip(d.get("symbol"), 12); nm = _clip(d.get("display_name"), 50)
        head = f"AGORA listing{': ' + sym if sym else ''}"
        return f"{head} \u00b7 {nm}" if nm else head
    if t == "share.certificate":
        qty, sym = d.get("qty"), _clip(d.get("symbol"), 12)
        if qty is not None and sym:
            return f"Signed holding: {qty} {sym}"
        return "Signed holding"
    if t == "org.work.receipt":
        memo = _clip(d.get("memo"), 70)
        head = f"Work receipt{': ' + m if m else ''}"
        return f"{head} \u00b7 {memo}" if memo else head
    if t == "engagement.proposal":
        return f"Proposed terms: {_clip(d.get('title'), 90)}" if d.get("title") else "Proposed terms"
    if t == "engagement.counter":
        mt = _money(d, "total")
        head = f"Counter-offer: {_clip(d.get('title'), 70)}" if d.get("title") else "Counter-offer"
        return f"{head} \u00b7 {mt}" if mt else head
    if t == "engagement.offer":
        mt = _money(d, "total")
        head = f"Offer sent: {_clip(d.get('title'), 70)}" if d.get("title") else "Offer sent"
        return f"{head} \u00b7 {mt}" if mt else head
    if t == "engagement.accepted":
        mt = _money(d, "total")
        return f"Offer accepted \u2014 {mt} held in escrow" if mt else "Offer accepted \u2014 escrow held"
    if t == "engagement.milestone":
        return f"Delivered: {_clip(d.get('title'), 80)}" if d.get("title") else "Milestone delivered"
    if t == "engagement.settled":
        return f"Settled \u2014 {m} released" if m else "Settled"
    if t == "topup.offer":
        return f"Top-up offer{': ' + m if m else ''}"
    return _clip(str(t).replace(".", " ").replace("_", " ").capitalize(), 60)


_SUPPORT_STATUS_WORD = {
    "open": "open", "in_progress": "being worked on",
    "resolved": "resolved", "closed": "closed",
}

# The room vocabulary, ONE English template per action. Mirrors
# `services/chat/orgRoomActions.ts::systemRowText`; the drift gate in
# tests/test_system_preview.py parses that file and FAILS if the FE gains an
# action this table lacks, so the two cannot drift silently.
_ROOM_TEMPLATE = {
    "kick": "{by} removed {target} from the room",
    "mute": "{by} muted {target}",
    "unmute": "{by} unmuted {target}",
    "mode:announce": "{by} set the room to announce-only",
    "mode:open": "{by} opened the room",
    "topic": "{by} set the topic: {value}",
    "topic:clear": "{by} cleared the topic",
    "motd": "{by} updated the room genesis",
    "assistant_on": "{by} added @assistant to this room",
    "assistant_off": "{by} removed @assistant from this room",
}


def _system_sentence(body: Optional[str], card: Optional[dict],
                     sender_name: Optional[str] = None) -> str:
    """A system row as one English sentence, for the stored list preview.

    \u26a0 \u00a7CHATCOHERE said this was "deliberately not fixed \u2014 the FE owns those
    sentences and a second table server-side is the \u00a7ORGLEAK second-copy trap".
    That drew the line in the WRONG PLACE, and its own neighbour proves it:
    `_card_sentence` renders 19 card types server-side on exactly the reasoning
    that a 160-char English hint in a list is a DIFFERENT ARTIFACT from the
    localized thread row, not a second copy of it. System rows are the same case.

    \u26a0 And the FE could not have been handed the job: `conversations.last_preview`
    is a STORED column written at post time \u2014 the list payload carries no kind,
    body or card, so there is nothing for the brain to re-render from. Doing it
    FE-side would mean new denormalized columns (a migration) for a cosmetic hint.

    \u00a7ORGLEAK is about a second AUTHORITY that can disagree about a decision.
    Neither side here decides anything; both render the same recorded fact in a
    different medium (this one has no locale, the thread's does). The real risk is
    DRIFT, so drift is what the gate covers.

    Measured live before writing (frame-c, 5 families): room.* x474 \u00b7 ping x84 \u00b7
    support.* x79 \u00b7 retention.* x18 \u00b7 free prose (the consent-review rows), which
    was previewing as `[Desk Owner d2a419 allo]` \u2014 a bracketed TRUNCATION, worse
    than the token case that prompted the slice.
    """
    raw = str(body or "").strip()
    who = (sender_name or "").strip() or "Someone"

    if raw == "ping":
        return f"{who} pinged"

    if raw.startswith("support."):
        st = raw[len("support."):]
        return f"{who} marked this ticket {_SUPPORT_STATUS_WORD.get(st, st)}."

    if raw.startswith("retention."):
        tail = raw[len("retention."):]
        if tail == "off":
            return f"{who} turned disappearing messages off \u2014 everything is kept."
        try:
            hours = int(tail.rstrip("h"))
        except (TypeError, ValueError):
            hours = 0
        if hours <= 0:
            return raw[:PREVIEW_LEN]
        return (f"{who} set messages here to disappear after {hours}h."
                if hours < 24 else
                f"{who} set messages here to disappear after {round(hours / 24)}d.")

    if raw.startswith("room."):
        c = card if isinstance(card, dict) else {}
        by = str(c.get("by_name") or c.get("by") or "An operator")
        target = str(c.get("target_name") or "a member")
        value = "" if c.get("value") is None else str(c.get("value"))
        action = raw[len("room."):]
        if action == "mode":
            key = "mode:announce" if value == "announce" else "mode:open"
        elif action == "topic":
            key = "topic" if value else "topic:clear"
        else:
            key = action
        tmpl = _ROOM_TEMPLATE.get(key)
        if tmpl is None:
            # An action this table does not know. Say what is true rather than
            # inventing a verb; the drift gate turns this into a test failure.
            return f"{by} performed a room action"
        return tmpl.format(by=by, target=target, value=value)[:PREVIEW_LEN]

    # Free prose (the consent-review rows) is ALREADY a sentence \u2014 pass it
    # through. Bracketing truncated it to 24 characters, mid-word.
    return raw[:PREVIEW_LEN]


def preview_for(kind: str, body: Optional[str], card: Optional[dict],
                sender_name: Optional[str] = None) -> str:
    """The 160-char thread-list preview \u2014 a HINT, never a render.

    \u26a0 Cards used to preview as their raw type (`[service.result]`). They now
    preview as a sentence; the full render still belongs to the FE card component,
    which is a different artifact, not a second copy of this one.

    \u26a0 System rows used to preview as their vocabulary token (`[room.mode]`) \u2014
    the same defect one step over, closed by `_system_sentence`; see its note for
    why the FE could not be handed the job, and why this is not a second copy.
    """
    if kind == "card" and isinstance(card, dict):
        return _card_sentence(card)[:PREVIEW_LEN]
    if kind == "system":
        return _system_sentence(body, card, sender_name)[:PREVIEW_LEN]
    return (body or "")[:PREVIEW_LEN]


def result_client_ref(client_ref: str) -> str:
    """Deterministic client_ref for the service.result sibling of a service.call
    ask — uuid5 so a retried composition lands on the SAME idempotency row."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"ourstate-result-{client_ref}"))


# ---------------------------------------------------------------------------
# Actor plumbing (the dual-auth dict from security.get_current_actor_for_read)
# ---------------------------------------------------------------------------

class Actor:
    """Normalized authenticated principal."""

    __slots__ = ("ptype", "developer_id", "agent_did", "display_name", "system_id")

    def __init__(self, ptype: str, developer_id: Optional[int] = None,
                 agent_did: Optional[str] = None, display_name: str = "",
                 system_id: Optional[str] = None):
        self.ptype = ptype
        self.developer_id = developer_id
        self.agent_did = agent_did
        self.display_name = display_name
        # §OURSTATE-7 D — 'system' authorship. `chat_messages.sender_ptype` has
        # always allowed it (mig 0155); nothing had used it, because every
        # writer so far was a real principal. The support desk is not a
        # principal: it is a RAIL, and an admin answering a ticket must not
        # silently become a participant of the thread.
        self.system_id = system_id

    @property
    def key(self) -> str:
        if self.ptype == "system":
            return f"sys:{self.system_id or 'system'}"
        return principal_key(self.ptype,
                             self.developer_id if self.ptype == "developer" else self.agent_did)

    @property
    def sender_id(self) -> str:
        if self.ptype == "system":
            return str(self.system_id or "system")
        return str(self.developer_id) if self.ptype == "developer" else str(self.agent_did)


def actor_from_auth(actor_dict: dict) -> Actor:
    """Map the security.get_current_actor_for_read dict onto an Actor."""
    if actor_dict.get("kind") == "agent":
        agent = actor_dict.get("agent")
        return Actor("agent", agent_did=actor_dict["agent_did"],
                     display_name=getattr(agent, "name", None) or actor_dict["agent_did"])
    dev = actor_dict["developer"]
    return Actor("developer", developer_id=int(dev.id),
                 display_name=getattr(dev, "name", None) or getattr(dev, "email", "") or f"dev {dev.id}")


# ---------------------------------------------------------------------------
# Redis rate gates (shared across workers). D6-555: never OPEN. They failed open
# (no Redis, or a Redis error, let every message, stranger thread, ping and
# federated call through uncounted). Now a gate that cannot count in Redis counts
# in this worker, with the same limit and window: the limit holds per worker
# instead of across the registry, never not at all.
# ---------------------------------------------------------------------------

_LOCAL_RL: Dict[str, Tuple[int, float]] = {}    # "chat:rl:<key>" -> (count, window end on the monotonic clock)
_LOCAL_RL_MAX_KEYS = 20000
_local_rl_noted = 0.0


def _local_rate_gate(full: str, limit: int, window_s: int) -> bool:
    """The in-worker count a gate falls back to (a fixed window per key). Bounded: when it holds as many live keys as
    it may, a principal it has no room to count is refused, never let through uncounted."""
    import time as _time
    now = _time.monotonic()
    n, until = _LOCAL_RL.get(full, (0, 0.0))
    if now >= until:
        n, until = 0, now + window_s
    if full not in _LOCAL_RL and len(_LOCAL_RL) >= _LOCAL_RL_MAX_KEYS:
        for k in [k for k, (_c, u) in _LOCAL_RL.items() if u <= now]:
            del _LOCAL_RL[k]
        if len(_LOCAL_RL) >= _LOCAL_RL_MAX_KEYS:
            return False
    _LOCAL_RL[full] = (n + 1, until)
    return n + 1 <= limit


def _note_local_counting(key: str, why: Any) -> None:
    global _local_rl_noted
    import time as _time
    now = _time.monotonic()
    if now - _local_rl_noted >= 60:
        _local_rl_noted = now
        logger.warning("[CHAT] rate gates count per worker: Redis cannot count (%s; first key %s)", why, key)


async def _rate_gate(key: str, limit: int, window_s: int) -> bool:
    full = f"chat:rl:{key}"
    try:
        from agentvault_registry.background_tasks.leader import get_redis
        r = await get_redis()
        if r is not None:
            n = await r.incr(full)
            if int(n) == 1:
                await r.expire(full, window_s)
            return int(n) <= limit
        why: Any = "no Redis configured"
    except Exception as e:  # noqa: BLE001 — counted here instead (D6-555), never waved through
        why = type(e).__name__
    _note_local_counting(key, why)
    return _local_rate_gate(full, limit, window_s)


async def _rate_peek_release(key: str) -> None:
    """Undo one count after a refused action so a rejected request does not eat
    the caller's budget (best-effort): in Redis, or in this worker when Redis
    cannot count (D6-555)."""
    full = f"chat:rl:{key}"
    try:
        from agentvault_registry.background_tasks.leader import get_redis
        r = await get_redis()
        if r is not None:
            await r.decr(full)
            return
    except Exception:  # noqa: BLE001
        pass
    n, until = _LOCAL_RL.get(full, (0, 0.0))
    if n > 0:
        _LOCAL_RL[full] = (n - 1, until)


# ---------------------------------------------------------------------------
# Block primitives
# ---------------------------------------------------------------------------

def _split_key(pkey: str) -> Tuple[str, str]:
    kind, _, pid = pkey.partition(":")
    # §TWOAGENT G1 step 3 (2026-09-23): a `rem:` key is a principal on a PEER registry. It used to split as an AGENT,
    # so a block of a remote principal could not be stored under its own type (and matched nothing).
    return ({"dev": "developer", "rem": "remote"}.get(kind, "agent"), pid)


async def blocks_between(db: AsyncSession, key_a: str, key_b: str) -> Dict[str, bool]:
    """Who blocks whom between two principal keys. Returns
    {'a_blocks_b': bool, 'b_blocks_a': bool}."""
    a_t, a_i = _split_key(key_a)
    b_t, b_i = _split_key(key_b)
    rows = (await db.execute(select(ChatBlock).where(
        ((ChatBlock.blocker_ptype == a_t) & (ChatBlock.blocker_id == a_i)
         & (ChatBlock.blocked_ptype == b_t) & (ChatBlock.blocked_id == b_i)) |
        ((ChatBlock.blocker_ptype == b_t) & (ChatBlock.blocker_id == b_i)
         & (ChatBlock.blocked_ptype == a_t) & (ChatBlock.blocked_id == a_i))
    ))).scalars().all()
    out = {"a_blocks_b": False, "b_blocks_a": False}
    for r in rows:
        if principal_key(r.blocker_ptype, r.blocker_id) == key_a:
            out["a_blocks_b"] = True
        else:
            out["b_blocks_a"] = True
    return out


async def blocker_keys_against(db: AsyncSession, sender_key: str,
                               candidate_keys: Iterable[str]) -> set:
    """Of candidate_keys, which principals BLOCK the sender. One query."""
    cands = list(candidate_keys)
    if not cands:
        return set()
    s_t, s_i = _split_key(sender_key)
    rows = (await db.execute(select(ChatBlock).where(
        (ChatBlock.blocked_ptype == s_t) & (ChatBlock.blocked_id == s_i)
    ))).scalars().all()
    blockers = {principal_key(r.blocker_ptype, r.blocker_id) for r in rows}
    return blockers & set(cands)


async def create_block(db: AsyncSession, blocker: Actor, blocked_key: str) -> None:
    """Create a block and silently leave every shared pair thread. The blocked
    party never learns: their sends keep inserting; delivery skips us."""
    b_t, b_i = _split_key(blocked_key)
    if principal_key(b_t, b_i) == blocker.key:
        raise ChatError(400, "you cannot block yourself")
    exists = (await db.execute(select(ChatBlock).where(
        (ChatBlock.blocker_ptype == blocker.ptype)
        & (ChatBlock.blocker_id == blocker.sender_id)
        & (ChatBlock.blocked_ptype == b_t) & (ChatBlock.blocked_id == b_i)
    ))).scalar_one_or_none()
    if exists is None:
        db.add(ChatBlock(blocker_ptype=blocker.ptype, blocker_id=blocker.sender_id,
                         blocked_ptype=b_t, blocked_id=b_i))
    # Leave every pair thread shared with the blocked principal — this is what
    # makes the silence total: no list row, no unread, no delivery.
    # ⚠ asyncpg infers ONE type per parameter: a param used in both
    # CAST(x AS INTEGER) and lower(x) errors "lower(integer) does not exist".
    # Cast the COLUMN to text instead so every param stays text.
    await db.execute(sa_text("""
        UPDATE conversation_participants me SET state = 'left'
        WHERE me.conversation_id IN (
            SELECT p.conversation_id FROM conversation_participants p
            JOIN conversations c ON c.id = p.conversation_id AND c.kind IN ('dm','agent_service')
            WHERE p.ptype = :bt AND (
                (p.ptype = 'developer' AND p.developer_id::text = :bi)
             OR (p.ptype = 'agent' AND lower(p.agent_did) = lower(:bi))
             OR (p.ptype = 'remote' AND p.remote_key = :bi)
            )
        )
        AND me.ptype = :mt AND (
            (me.ptype = 'developer' AND me.developer_id::text = :mi)
         OR (me.ptype = 'agent' AND lower(me.agent_did) = lower(:mi))
        )
    """), {"bt": b_t, "bi": str(b_i), "mt": blocker.ptype, "mi": str(blocker.sender_id)})
    await db.commit()


async def delete_block(db: AsyncSession, blocker: Actor, blocked_key: str) -> bool:
    """Remove a block. Threads stay left — re-engaging is an explicit new
    message from the unblocking side, which reactivates their row."""
    b_t, b_i = _split_key(blocked_key)
    res = await db.execute(sa_text("""
        DELETE FROM chat_blocks
        WHERE blocker_ptype = :bt AND blocker_id = :bi
          AND blocked_ptype = :t AND blocked_id = :i
    """), {"bt": blocker.ptype, "bi": blocker.sender_id, "t": b_t, "i": b_i})
    await db.commit()
    return bool(getattr(res, "rowcount", 0))


async def list_blocks(db: AsyncSession, actor: Actor) -> List[dict]:
    rows = (await db.execute(select(ChatBlock).where(
        (ChatBlock.blocker_ptype == actor.ptype) & (ChatBlock.blocker_id == actor.sender_id)
    ).order_by(ChatBlock.created_at.desc()))).scalars().all()
    return [{"ptype": r.blocked_ptype,
             "id": r.blocked_id,
             "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]


# ---------------------------------------------------------------------------
# Principal resolution helpers
# ---------------------------------------------------------------------------

async def agent_owner_map(db: AsyncSession, dids: Iterable[str]) -> Dict[str, Optional[int]]:
    """DID → creator developer id (the notify_agent_owners resolution)."""
    ds = [d for d in dict.fromkeys(dids or []) if d]
    if not ds:
        return {}
    rows = (await db.execute(sa_text(
        "SELECT did, creator_developer_id FROM agents WHERE lower(did) = ANY(:d)"
    ), {"d": [d.lower() for d in ds]})).all()
    found = {str(r[0]).lower(): r[1] for r in rows}
    return {d: found.get(d.lower()) for d in ds}


async def display_names(db: AsyncSession, keys: Iterable[str]) -> Dict[str, str]:
    """Principal key → display name, one query per type."""
    dev_ids, agent_dids, remote_ids = [], [], []
    for k in dict.fromkeys(keys or []):
        t, i = _split_key(k)
        if t == "remote":
            remote_ids.append(i)
            continue
        (dev_ids if t == "developer" else agent_dids).append(i)
    out: Dict[str, str] = {}
    if remote_ids:
        # §TWOAGENT G1 step 4: a principal on a PEER registry was sent down the agent branch and named by nobody, so a
        # cross-registry thread listed a blank counterparty. An agent we mirror is named by its card; anyone else by
        # the address itself, never a blank.
        by_did = {rid.rpartition("@")[0].lower(): rid for rid in remote_ids if rid.lower().startswith("did:")}
        if by_did:
            rows = (await db.execute(sa_text(
                "SELECT agent_did, name FROM agent_cards WHERE lower(agent_did) = ANY(:d)"
            ), {"d": list(by_did)})).all()
            for r in rows:
                rid = by_did.get(str(r[0]).lower())
                if rid and r[1]:
                    out[f"rem:{rid}"] = r[1]
        for rid in remote_ids:
            out.setdefault(f"rem:{rid}", rid)
    if dev_ids:
        rows = (await db.execute(sa_text(
            "SELECT id, COALESCE(NULLIF(name, ''), email) FROM developers WHERE id = ANY(:ids)"
        ), {"ids": [int(i) for i in dev_ids]})).all()
        for r in rows:
            out[f"dev:{r[0]}"] = r[1] or f"dev {r[0]}"
    if agent_dids:
        # Agent display names live on agent_cards (the agents table has NO name
        # column — §DISCREFINE scar), which also covers federated mirrors.
        rows = (await db.execute(sa_text(
            "SELECT agent_did, name FROM agent_cards WHERE lower(agent_did) = ANY(:d)"
        ), {"d": [d.lower() for d in agent_dids]})).all()
        for r in rows:
            out[f"agt:{str(r[0]).lower()}"] = r[1] or str(r[0])
        for d in agent_dids:
            out.setdefault(f"agt:{d.lower()}", d)
    return out


async def _developer_exists(db: AsyncSession, dev_id: int) -> bool:
    row = (await db.execute(sa_text(
        "SELECT 1 FROM developers WHERE id = :i AND deleted_at IS NULL"
    ), {"i": int(dev_id)})).first()
    return row is not None


async def _agent_row(db: AsyncSession, did: str) -> Optional[Any]:
    """Returns (did, status, creator_developer_id) or None. ⚠ the agents table
    has NO name column (the §DISCREFINE scar) — names live on agent_cards."""
    return (await db.execute(sa_text(
        "SELECT did, status, creator_developer_id FROM agents WHERE lower(did) = lower(:d)"
    ), {"d": did})).first()


async def _agent_card_exists(db: AsyncSession, did: str) -> bool:
    """A federated MIRROR (agent_cards row with no local agents row) is a valid
    SERVICE target — §BUYSERVICE proved the whole buy loop against exactly such
    mirrors, with verify-at-issuer doing the trust work. It is NOT a valid DM
    target in CORE (no federation yet: the thread would be a void)."""
    row = (await db.execute(sa_text(
        "SELECT 1 FROM agent_cards WHERE lower(agent_did) = lower(:d) LIMIT 1"
    ), {"d": did})).first()
    return row is not None


# ---------------------------------------------------------------------------
# Membership (with the speaker-chip auto-join rule)
# ---------------------------------------------------------------------------

def _principal_clause(alias: str = "p") -> str:
    return (f"({alias}.ptype = 'developer' AND {alias}.developer_id = :m_dev) OR "
            f"({alias}.ptype = 'agent' AND lower({alias}.agent_did) = lower(:m_did))")


def _actor_params(actor: Actor) -> dict:
    return {"m_dev": actor.developer_id if actor.ptype == "developer" else -1,
            "m_did": actor.agent_did or ""}


async def _my_row(db: AsyncSession, conversation_id: str, actor: Actor) -> Optional[ConversationParticipant]:
    q = select(ConversationParticipant).where(
        ConversationParticipant.conversation_id == conversation_id)
    if actor.ptype == "developer":
        q = q.where(ConversationParticipant.ptype == "developer",
                    ConversationParticipant.developer_id == actor.developer_id)
    else:
        q = q.where(ConversationParticipant.ptype == "agent",
                    ConversationParticipant.agent_did.ilike(actor.agent_did or ""))
    return (await db.execute(q)).scalars().first()


async def thread_is_request(db: AsyncSession, conversation_id: str) -> bool:
    """D6-554: is this thread still a REQUEST? True while any participant has not accepted it (a row still 'pending').

    The one rule for what a request thread refuses (a ping, a file), whoever asks. It cannot be read from the asker's own
    row: the stranger who knocked holds an 'active' row of their own while the recipient's is 'pending'."""
    pending = (await db.execute(select(ConversationParticipant).where(
        ConversationParticipant.conversation_id == conversation_id,
        ConversationParticipant.state == "pending"))).scalars().first()
    return pending is not None


HOUSEHOLD_JOIN_CONFIRM = "household_join_confirm"


async def resolve_membership(db: AsyncSession, conv: Conversation, actor: Actor,
                             *, auto_join: bool = True, announce_ok: bool = False) -> ConversationParticipant:
    """Return the actor's participant row, applying the speaker-chip rule:
    a developer's LOCAL agents may join a thread the developer is active in,
    and vice versa — one side of the pair is one household. Anyone else: 403."""
    row = await _my_row(db, conv.id, actor)
    if row is not None:
        # §ORGLEAK — THE ROW IS NOT THE AUTHORITY, AND THIS EARLY RETURN USED TO
        # MAKE IT ONE. Measured 2026-08-28 on frame-c: a developer removed from
        # the organization entirely (verified absent from `organization_members`)
        # still read the room's full history AND posted into it, because a
        # participant row from before the removal short-circuited the org check
        # below. The discrimination that proves it was an authorization bypass
        # rather than an open room: a principal who was NEVER a participant got
        # the correct 403 from that very check.
        #
        # So for an org room the LIVE org table is re-derived on every touch —
        # which is what the docstring under this branch already promised
        # ("Participant rows are furniture, never authority").
        #
        # ⚠ `state` is deliberately NOT the test. The leaking account was
        # `state='active'`; org standing is the fact that changed. And a `left`
        # row must stay resolvable, because `open_org_room` flips it back to
        # active — rejoining your own org's room is a supported path.
        if conv.kind == "org":
            live_role = await actor_org_role(db, conv.org_id or "", actor)
            if live_role is None:
                raise ChatError(403, "you are not an active member of this organization")
            want = "owner" if live_role == "owner" else "member"
            if row.role != want:
                row.role = want   # a demotion follows you into the room
        return row
    if auto_join and conv.kind == "org":
        # §OURSTATE-2: the room's membership truth is the LIVE org table —
        # any active org member (or org-assigned agent) materializes a row
        # on first touch. Participant rows are furniture, never authority.
        role = await actor_org_role(db, conv.org_id or "", actor)
        if role is None:
            raise ChatError(403, "you are not an active member of this organization")
        row = ConversationParticipant(
            conversation_id=conv.id, ptype=actor.ptype,
            developer_id=actor.developer_id if actor.ptype == "developer" else None,
            agent_did=actor.agent_did if actor.ptype == "agent" else None,
            role="owner" if role == "owner" else "member", state="active")
        db.add(row)
        await db.flush()
        return row
    if not auto_join or conv.kind not in PAIR_KINDS:
        raise ChatError(403, "you are not a participant in this conversation")

    parts = (await db.execute(select(ConversationParticipant).where(
        ConversationParticipant.conversation_id == conv.id))).scalars().all()

    allowed = False
    if actor.ptype == "agent":
        owner = (await agent_owner_map(db, [actor.agent_did or ""])).get(actor.agent_did or "")
        allowed = owner is not None and any(
            p.ptype == "developer" and p.developer_id == owner and p.state == "active"
            for p in parts)
    else:
        agent_parts = [p.agent_did for p in parts if p.ptype == "agent" and p.state == "active" and p.agent_did]
        if agent_parts:
            owners = await agent_owner_map(db, agent_parts)
            allowed = any(o == actor.developer_id for o in owners.values())
    if not allowed:
        raise ChatError(403, "you are not a participant in this conversation")

    # §TWOAGENT G1 household seat (V0436): in a cross-registry thread the other side is a different party, so the owner
    # is never a SILENT reader. On a MIRROR the thread's host must record the join first (the home vouches for its own
    # resident, the same caller-is-home rule as every other federation write); if the host does not, nobody is seated.
    host = getattr(conv, "host_registry", None)
    grant_did = await _household_grant(db, parts, actor)
    if grant_did and (host or any(p.ptype == "remote" for p in parts)) and not announce_ok:
        # §TWOAGENT G1 (V0437): joining a CROSS-REGISTRY thread announces the owner to the other side, so a READ must
        # not do it unasked. A deliberate act (a post, a ping, an accept) is consent; a read, a mute or a mark-read asks
        # first. The code word leads the sentence (the RFC 7807 layer stringifies details), for a client to key its
        # confirm dialog on.
        key = principal_key("agent", grant_did)
        name = (await display_names(db, [key])).get(key) or grant_did
        raise ChatError(409, f"{HOUSEHOLD_JOIN_CONFIRM}: opening this thread tells the other side that you joined, as "
                             f"the owner of {name}. Open it again with join=true to continue.")
    if host:
        from agentvault_registry.services import chat_federation as _fed
        if not _fed.federation_enabled():
            raise ChatError(501, "cross-registry chat is not enabled on this registry")
        if actor.ptype != "developer" or not grant_did:
            raise ChatError(403, "an agent joins a cross-registry thread by being addressed; its owner joins through it")
        me = await _fed.announce_household_join(
            db, conv, actor, _fed.remote_key(grant_did, _fed.self_base_url()))
        if not me:
            raise ChatError(502, "the thread's host registry did not record this join; nothing changed, try again")
        again = await _my_row(db, conv.id, actor)       # a delivery may have seated us while the host answered
        if again is not None:
            return again

    row = ConversationParticipant(
        conversation_id=conv.id, ptype=actor.ptype,
        developer_id=actor.developer_id if actor.ptype == "developer" else None,
        agent_did=actor.agent_did if actor.ptype == "agent" else None,
        role="member", state="active")
    db.add(row)
    await db.flush()
    if host:
        # The host recorded this join; the home's seat is the same fact. A read never commits (get_db closes without
        # one), so without this the seat rolled back and every later read asked the host again.
        await db.commit()
    if not host and grant_did and any(p.ptype == "remote" for p in parts):
        # The HOST's own owner joining a federated thread: the same visible join, delivered to every home.
        from agentvault_registry.services import chat_federation as _fed
        if _fed.federation_enabled():
            await _fed.post_household_join(db, conv, row, actor.key, actor.display_name,
                                           principal_key("agent", grant_did), local_actor=actor)
    return row


async def _household_grant(db: AsyncSession, parts: List[ConversationParticipant], actor: Actor) -> Optional[str]:
    """The DID of the active agent participant that seats this DEVELOPER by the household rule, or None."""
    if actor.ptype != "developer":
        return None
    agent_parts = [p.agent_did for p in parts if p.ptype == "agent" and p.state == "active" and p.agent_did]
    if not agent_parts:
        return None
    owners = await agent_owner_map(db, agent_parts)
    for did in agent_parts:
        if owners.get(did) == actor.developer_id:
            return did
    return None


async def _get_conversation(db: AsyncSession, conversation_id: str) -> Conversation:
    conv = (await db.execute(select(Conversation).where(
        Conversation.id == conversation_id))).scalars().first()
    if conv is None:
        raise ChatError(404, "conversation not found")
    return conv


# ---------------------------------------------------------------------------
# Conversation create (pair kinds; dedup; Requests folder; silent blocks)
# ---------------------------------------------------------------------------

async def create_conversation(db: AsyncSession, actor: Actor, kind: str,
                              target_ptype: str, target_id: str,
                              intro_payment_ref: Optional[str] = None,
                              ) -> Tuple[Conversation, bool, ConversationParticipant]:
    """Create (or dedup-return) a pair conversation. Returns
    (conversation, created, my_row).

    Requests folder: a first message from a stranger lands the TARGET row
    'pending'. Not strangers: your own agents (and your agents' owner), and any
    agent_service target — a service agent's published card IS its public offer,
    so a service thread never sits in a requests queue no runtime will answer.
    Blocks: caller-blocks-target refuses loudly (the blocker knows); target-
    blocks-caller proceeds with the target row born 'left' — a silent void.
    """
    if kind not in PAIR_KINDS:
        raise ChatError(422, f"kind must be one of {list(PAIR_KINDS)} in this phase")
    if target_ptype not in ("developer", "agent"):
        raise ChatError(422, "target.ptype must be developer or agent")
    if kind == "agent_service" and target_ptype != "agent":
        raise ChatError(422, "an agent_service conversation targets an agent")

    # Target must exist (and, for services, be an agent row this registry knows).
    same_household = False
    if target_ptype == "developer":
        if not await _developer_exists(db, int(target_id)):
            raise ChatError(404, "target developer not found")
        if actor.ptype == "agent":
            owner = (await agent_owner_map(db, [actor.agent_did or ""])).get(actor.agent_did or "")
            same_household = owner == int(target_id)
        target_key = principal_key("developer", int(target_id))
    else:
        arow = await _agent_row(db, target_id)
        if arow is None:
            # Federated mirror: card known, identity homed elsewhere. Callable
            # as a SERVICE today (§BUYSERVICE, verify-at-issuer); DM-able only
            # once federation ships (OURSTATE-3) — say which, by name.
            if not await _agent_card_exists(db, target_id):
                raise ChatError(404, "target agent not found")
            if kind != "agent_service":
                raise ChatError(409, FOREIGN_AGENT_DM_REFUSAL)
        else:
            if str(arow[1] or "").lower() in ("revoked", "suspended"):
                raise ChatError(409, f"target agent is {arow[1]}")
            if actor.ptype == "developer" and arow[2] == actor.developer_id:
                same_household = True
            if actor.ptype == "agent":
                owners = await agent_owner_map(db, [actor.agent_did or "", target_id])
                mine, theirs = owners.get(actor.agent_did or ""), owners.get(target_id)
                same_household = mine is not None and mine == theirs
        target_key = principal_key("agent", target_id)

    if target_key == actor.key:
        raise ChatError(422, "a conversation needs a counterparty")

    blocks = await blocks_between(db, actor.key, target_key)
    if blocks["a_blocks_b"]:
        raise ChatError(403, "you have blocked this principal — unblock to start a conversation")

    pk = pair_key(kind, actor.key, target_key)
    existing = (await db.execute(select(Conversation).where(
        Conversation.dm_pair_key == pk))).scalars().first()
    if existing is not None:
        my_row = await _my_row(db, existing.id, actor)
        if my_row is None:
            my_row = await resolve_membership(db, existing, actor, announce_ok=True)
        elif my_row.state in ("left", "pending"):
            # Creating a conversation to this pair IS engaging with it.
            my_row.state = "active"
        await db.commit()
        return existing, False, my_row

    target_state = "active"
    intro_receipt: Optional[dict] = None
    if blocks["b_blocks_a"]:
        target_state = "left"          # the silent void — sender sees a normal thread
    elif kind == "dm" and not same_household:
        # Stranger: land as a request, behind the per-day gate.
        gate_key = f"stranger:{actor.key}"
        if not await _rate_gate(gate_key, RL_STRANGER_LIMIT, RL_STRANGER_WINDOW_S):
            raise ChatError(429, "daily limit for new conversations with strangers reached")

        # §OURSTATE-5a — the target's own contact policy. Only a HUMAN declares
        # one (an agent's price is its card's price: a different mechanism on a
        # different rail), and it governs a stranger's FIRST thread only. Once
        # this row exists, talking is free forever.
        if target_ptype == "developer":
            from ..services import contact_policy   # local: this module is its ChatError source
            decl = await contact_policy.declaration(db, int(target_id))
            eff = decl["effective"]
            if eff == "contacts":
                if not await contact_policy.has_existing_thread(db, actor.key, target_key):
                    raise ChatError(403, "this person accepts new threads from existing "
                                         "contacts only")
            elif eff == "priced":
                intro_receipt = await contact_policy.verify_and_consume_intro(
                    db, tx_ref=intro_payment_ref or "", payer_key=actor.key,
                    payee_developer_id=int(target_id), decl=decl)
        target_state = "pending"

    conv = Conversation(
        kind=kind, created_by_ptype=actor.ptype, created_by_id=actor.sender_id,
        dm_pair_key=pk)
    db.add(conv)
    try:
        await db.flush()
    except IntegrityError:
        # Race on the pair key: someone else created it between our SELECT and
        # flush. Re-read and reuse — the dedup is the schema, not the SELECT.
        await db.rollback()
        existing = (await db.execute(select(Conversation).where(
            Conversation.dm_pair_key == pk))).scalars().first()
        if existing is None:
            raise ChatError(500, "conversation create raced and could not recover")
        my_row = await resolve_membership(db, existing, actor, announce_ok=True)
        await db.commit()
        return existing, False, my_row

    if intro_receipt:
        # Bind the spent receipt to the thread it opened: audit, not gating.
        from ..services import contact_policy
        await contact_policy.attach_intro_to_conversation(db, intro_receipt["tx_ref"], conv.id)

    my_row = ConversationParticipant(
        conversation_id=conv.id, ptype=actor.ptype,
        developer_id=actor.developer_id if actor.ptype == "developer" else None,
        agent_did=actor.agent_did if actor.ptype == "agent" else None,
        role="owner", state="active")
    t_t, t_i = _split_key(target_key)
    their_row = ConversationParticipant(
        conversation_id=conv.id, ptype=t_t,
        developer_id=int(t_i) if t_t == "developer" else None,
        agent_did=t_i if t_t == "agent" else None,
        role="member", state=target_state)
    db.add_all([my_row, their_row])
    await db.commit()
    return conv, True, my_row


# ---------------------------------------------------------------------------
# Message insert (atomic seq; idempotent client_ref; silent block delivery)
# ---------------------------------------------------------------------------

def _validate_client_ref(client_ref: str) -> str:
    ref = str(client_ref or "").strip()
    if not (8 <= len(ref) <= 64):
        raise ChatError(422, "client_ref must be 8-64 characters (a UUID is the convention)")
    return ref


async def insert_message(db: AsyncSession, conv: Conversation,
                         my_row: Optional[ConversationParticipant],
                         sender: Actor, kind: str, body: Optional[str], card: Optional[dict],
                         client_ref: str, reply_to: Optional[str] = None,
                         *, rail_author: bool = False,
                         mark_read: bool = True,
                         before_commit: Optional[Callable[[ChatMessage], Awaitable[Any]]] = None,
                         ) -> Tuple[ChatMessage, bool]:
    """Insert one message with an atomic per-thread seq. Returns
    (message, was_duplicate). COMMITS. Never announces — the caller fans out
    post-commit (§ESDUP).

    §OURSTATE-7 D widened two things for the support rail, both guarded:

      * `my_row=None` — a RAIL write with no participant behind it (the support
        desk). Legal only with `rail_author=True`, asserted below.
      * `mark_read=False` — do NOT advance the row's read floor. The default is
        True because a principal's own send is read by definition; a reply
        WRITTEN TO someone must stay unread for them, and passing the owner's
        row with the default would have marked their incoming support reply as
        already seen.
    """
    client_ref = _validate_client_ref(client_ref)
    if kind not in ("text", "card", "system"):
        raise ChatError(422, "kind must be text, card or system")
    if my_row is None and not rail_author:
        raise ChatError(403, "only a rail may write without a participant row")
    if conv.kind == "support" and not rail_author:
        # ONE writer. A support thread mirrors the ticket, so a direct client
        # post would put words in the thread that the ticket never heard — the
        # two would disagree and the ticket is the authority. The composer's
        # door is /chat/conversations/{id}/support-reply, which writes the
        # ticket first and mirrors second.
        raise ChatError(409, "a support thread is written through the support rail — "
                             "reply to the ticket and it appears here")
    if kind == "text":
        if not (body or "").strip():
            raise ChatError(422, "a text message needs a body")
        reason = validate_body(body)
        if reason:
            raise ChatError(422, reason)
        card = None
    elif kind == "card":
        # §OURSTATE-5c — resolve the fiat door ONCE, here, and hand the
        # verdict to the pure validator. Only asked for the one card type that
        # needs it, so an ordinary message never pays for a jurisdiction read.
        door = FIAT_DOOR_OPEN
        if isinstance(card, dict) and card.get("type") == "topup.offer":
            from ..services.fiat_door import may_offer_topup
            allowed, refusal = await may_offer_topup(db)
            door = FIAT_DOOR_OPEN if allowed else (refusal or "the fiat door is closed here")
        reason = validate_card(card, rail_author=rail_author, fiat_door=door)
        if reason:
            raise ChatError(422, reason)
        reason = validate_body(body)
        if reason:
            raise ChatError(422, reason)

    # Idempotency first: a retry returns the original row, moves nothing.
    dup = (await db.execute(select(ChatMessage).where(
        ChatMessage.conversation_id == conv.id,
        ChatMessage.sender_ptype == sender.ptype,
        ChatMessage.sender_id == sender.sender_id,
        ChatMessage.client_ref == client_ref))).scalars().first()
    if dup is not None:
        return dup, True

    reply_accept = my_row is not None and my_row.state == "pending"
    if reply_accept:
        # Replying to a request IS accepting it.
        my_row.state = "active"
    if my_row is not None and my_row.state != "active":
        raise ChatError(409, "you have left this conversation")
    if not rail_author:
        # §OURSTATE-2 room speech gates (mute + announce mode). Rail-authored
        # rows (moderation system rows, service records) bypass — a room
        # operator's act must be recordable even in a room they just locked.
        await room_posting_gate(db, conv, my_row, sender)

    pv = preview_for(kind, body, card, getattr(sender, "display_name", None))
    row = (await db.execute(sa_text("""
        UPDATE conversations
        SET last_seq = last_seq + 1, last_message_at = now(), last_preview = :pv
        WHERE id = :cid
        RETURNING last_seq
    """), {"pv": pv, "cid": conv.id})).first()
    if row is None:
        raise ChatError(404, "conversation not found")
    seq = int(row[0])

    msg = ChatMessage(
        conversation_id=conv.id, seq=seq, sender_ptype=sender.ptype,
        sender_id=sender.sender_id, kind=kind, body=body, card=card,
        reply_to=reply_to, client_ref=client_ref)
    db.add(msg)
    # Sending implies having read up to your own message — otherwise your own
    # sends count into YOUR unread badge forever (battery E2 caught exactly that).
    if my_row is not None and mark_read:
        my_row.last_read_seq = max(int(my_row.last_read_seq or 0), seq)
    try:
        if before_commit is not None:
            # §TWOAGENT G1 step 4: what must exist WITH the message (a hosted federated thread's delivery rows) is
            # written in the message's own transaction, so neither can ever exist without the other.
            await db.flush()
            await before_commit(msg)
        await db.commit()
    except IntegrityError:
        # client_ref raced its own retry: the twin committed first. Return it.
        await db.rollback()
        dup = (await db.execute(select(ChatMessage).where(
            ChatMessage.conversation_id == conv.id,
            ChatMessage.sender_ptype == sender.ptype,
            ChatMessage.sender_id == sender.sender_id,
            ChatMessage.client_ref == client_ref))).scalars().first()
        if dup is None:
            raise ChatError(500, "message insert raced and could not recover")
        return dup, True
    if reply_accept:
        await _announce_reply_accept(db, conv, my_row, principal_key(sender.ptype, sender.sender_id),
                                     getattr(sender, "display_name", None))
    return msg, False


async def _announce_reply_accept(db: AsyncSession, conv: Conversation, row: ConversationParticipant,
                                 acceptor_key: str, fallback_name: Optional[str]) -> None:
    """§TWOAGENT G1 (V0437): a REPLY from a pending row is the accept, and the knocker hears it as it hears /accept.
    Only the /accept rail used to notify: a reply flipped the row silently, locally and at a cross-registry host (where
    the home's later accept announce then found the row already active and changed nothing), so a knocker whose request
    was accepted by a reply never heard chat.request.accepted. Post-commit, exactly once (the flip happens once)."""
    notice = accepted_knock_notice(conv, "pending", "active", row)
    if notice is None:
        return
    name = fallback_name or ""
    try:    # name an agent or a remote principal the way the thread list does (its card, or its address)
        name = (await display_names(db, [acceptor_key])).get(acceptor_key) or name
    except Exception as e:  # noqa: BLE001 — a label; the notice still names the acceptor by id
        logger.debug("[CHAT] reply-accept name lookup skipped: %s", e)
    spawn(notify_request_accepted(notice, name))


def serialize_message(m: ChatMessage) -> dict:
    if m.deleted_at is not None:
        return {"id": m.id, "conversation_id": m.conversation_id, "seq": m.seq,
                "sender_ptype": m.sender_ptype, "sender_id": m.sender_id,
                "kind": "system", "body": None, "card": None, "deleted": True,
                "reply_to": None, "client_ref": m.client_ref,
                "created_at": m.created_at.isoformat() if m.created_at else None}
    return {"id": m.id, "conversation_id": m.conversation_id, "seq": m.seq,
            "sender_ptype": m.sender_ptype, "sender_id": m.sender_id,
            "kind": m.kind, "body": m.body, "card": m.card, "deleted": False,
            "reply_to": m.reply_to, "client_ref": m.client_ref,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "edited_at": m.edited_at.isoformat() if m.edited_at else None}


# ---------------------------------------------------------------------------
# Reads: list / messages / sync
# ---------------------------------------------------------------------------

def _dev_reach_clause() -> str:
    """A developer's inbox spans their own rows PLUS their local agents' rows
    (the unread badge sums both — plan §4)."""
    return """
        (p.ptype = 'developer' AND p.developer_id = :me)
        OR (p.ptype = 'agent' AND p.agent_did IN (
            SELECT did FROM agents WHERE creator_developer_id = :me))
    """


def _reach_and_org_live(actor: Actor):
    """(reach, org_live, params) — WHOSE threads these are, in one definition.

    §CHATPOLISH: extracted so the unread TOTAL and the LIST cannot drift apart.
    A second copy of this predicate would be a second answer to "is this room
    still mine", which is exactly what §ORGLEAK was.
    """
    if actor.ptype == "developer":
        reach = _dev_reach_clause()
        params: Dict[str, Any] = {"me": actor.developer_id}
        # §ORGLEAK — the LIST must ask the same question the ACCESS path asks, or
        # a stale participant row keeps an ex-member's room on their screen until
        # they tap it and get a 403. A developer keeps an org room while they are
        # a live member, OR while one of their own agents is assigned to that org
        # (that agent's row is inside `_dev_reach_clause`, so the room is
        # legitimately theirs to see even though they hold no org role).
        org_live = """(
            EXISTS (SELECT 1 FROM organization_members om
                    WHERE om.organization_id = c.org_id
                      AND om.developer_id = :me AND om.is_active = true)
         OR EXISTS (SELECT 1 FROM agents ag
                    WHERE ag.creator_developer_id = :me
                      AND ag.organization_id = c.org_id)
        )"""
    else:
        reach = "(p.ptype = 'agent' AND lower(p.agent_did) = lower(:med))"
        params = {"med": actor.agent_did}
        org_live = """(
            EXISTS (SELECT 1 FROM agents ag
                    WHERE lower(ag.did) = lower(:med)
                      AND ag.organization_id = c.org_id)
        )"""
    return reach, org_live, params


async def unread_total(db: AsyncSession, actor: Actor) -> dict:
    """§CHATPOLISH — how many unread messages are waiting, and in how many
    threads, for the nav badge.

    The badge the §CHATDESK C2 spec asked for was never built, so the desktop
    shell had no way to say a message had arrived. This answers the same
    question `list_conversations` answers, with the same predicates, and returns
    two numbers instead of a page of rows: a global poller must not ship every
    thread's preview text to draw one chip.
    """
    reach, org_live, params = _reach_and_org_live(actor)
    params["st"] = "active"
    row = (await db.execute(sa_text(f"""
        SELECT COALESCE(SUM(u.unread), 0), COUNT(*) FILTER (WHERE u.unread > 0)
        FROM (
            SELECT SUM(GREATEST(0, c.last_seq
                                 - GREATEST(p.last_read_seq, COALESCE(p.hidden_before_seq, 0)))) AS unread
            FROM conversations c
            JOIN conversation_participants p ON p.conversation_id = c.id
            WHERE ({reach})
              AND (c.kind <> 'org' OR (EXISTS (
                    SELECT 1 FROM organizations o
                    WHERE o.id = c.org_id AND o.chat_enabled = true)
                    AND {org_live}))
              AND NOT COALESCE(p.muted, false)
            GROUP BY c.id
            HAVING MAX(CASE WHEN p.state = :st THEN 1 ELSE 0 END) = 1
        ) u
    """), params)).first()
    return {"messages": int(row[0] or 0), "threads": int(row[1] or 0)}


async def household_keys(db: AsyncSession, actor: Actor) -> Set[str]:
    """The keys that are the caller's own side of a thread: itself, a developer's agents, an agent's owner.

    §TWOAGENT V0441: the thread read asked this with the owner included for an agent, the list without it, so an agent
    whose owner had joined its thread could see its own owner named as the counterparty in the list alone."""
    my_keys = {actor.key}
    if actor.ptype == "developer":
        own = (await db.execute(sa_text(
            "SELECT did FROM agents WHERE creator_developer_id = :me"),
            {"me": actor.developer_id})).all()
        my_keys |= {principal_key("agent", r[0]) for r in own}
    elif actor.ptype == "agent":
        owner = (await agent_owner_map(db, [actor.agent_did or ""])).get(actor.agent_did or "")
        if owner is not None:
            my_keys.add(principal_key("developer", owner))
    return my_keys


async def list_conversations(db: AsyncSession, actor: Actor, state: str = "active",
                             cursor: Optional[str] = None, limit: int = 30) -> dict:
    limit = max(1, min(int(limit or 30), LIST_MAX))
    want_state = "pending" if state == "requests" else "active"

    if actor.ptype == "developer":
        reach = _dev_reach_clause()
        params: Dict[str, Any] = {"me": actor.developer_id}
        # §ORGLEAK — the LIST must ask the same question the ACCESS path asks, or
        # a stale participant row keeps an ex-member's room on their screen until
        # they tap it and get a 403. A developer keeps an org room while they are
        # a live member, OR while one of their own agents is assigned to that org
        # (that agent's row is inside `_dev_reach_clause`, so the room is
        # legitimately theirs to see even though they hold no org role).
        org_live = """(
            EXISTS (SELECT 1 FROM organization_members om
                    WHERE om.organization_id = c.org_id
                      AND om.developer_id = :me AND om.is_active = true)
         OR EXISTS (SELECT 1 FROM agents ag
                    WHERE ag.creator_developer_id = :me
                      AND ag.organization_id = c.org_id)
        )"""
    else:
        reach = "(p.ptype = 'agent' AND lower(p.agent_did) = lower(:med))"
        params = {"med": actor.agent_did}
        org_live = """(
            EXISTS (SELECT 1 FROM agents ag
                    WHERE lower(ag.did) = lower(:med)
                      AND ag.organization_id = c.org_id)
        )"""

    cursor_clause = ""
    if cursor:
        try:
            params["cursor"] = datetime.datetime.fromisoformat(cursor)
            cursor_clause = "AND c.last_message_at < :cursor"
        except ValueError:
            raise ChatError(422, "cursor must be an ISO timestamp from a prior page")

    params.update({"st": want_state, "lim": limit})
    rows = (await db.execute(sa_text(f"""
        SELECT c.id, c.kind, c.title, c.last_seq, c.last_message_at, c.last_preview,
               c.dm_pair_key, c.service_inflight_at, c.created_at,
               MAX(CASE WHEN p.state = :st THEN 1 ELSE 0 END) AS visible,
               SUM(GREATEST(0, c.last_seq - GREATEST(p.last_read_seq, COALESCE(p.hidden_before_seq, 0)))) AS unread,
               BOOL_AND(p.muted) AS muted,
               c.mode, c.topic, c.org_id, c.support_ticket_id,
               c.created_by_ptype, c.created_by_id
        FROM conversations c
        JOIN conversation_participants p ON p.conversation_id = c.id
        WHERE ({reach}) {cursor_clause}
          -- §OURSTATE-7 A1 — THE OPT-IN IS RETROACTIVE OR IT IS NOT AN OPT-IN.
          -- This list selects by PARTICIPATION, so every room opened before
          -- §OURSTATE-6 kept listing regardless of `organizations.chat_enabled`
          -- and the switch he was given only governed NEW rooms. Measured on
          -- frame-c: Acme Firm, Bullion Works x3 and Atlas Collective all read
          -- chat_enabled = false and all still appeared. A room whose org has
          -- chat off leaves the thread list and comes back under
          -- "Organizations without a room" (`list_org_rooms().enableable`) —
          -- disabling HIDES a room, it never destroys one, and the same act
          -- un-hides it.
          AND (c.kind <> 'org' OR (EXISTS (
                SELECT 1 FROM organizations o
                WHERE o.id = c.org_id AND o.chat_enabled = true)
                AND {org_live}))
        GROUP BY c.id
        HAVING MAX(CASE WHEN p.state = :st THEN 1 ELSE 0 END) = 1
        ORDER BY c.last_message_at DESC NULLS LAST
        LIMIT :lim
    """), params)).all()

    conv_ids = [r[0] for r in rows]
    parts_by_conv: Dict[str, List[ConversationParticipant]] = {}
    if conv_ids:
        parts = (await db.execute(select(ConversationParticipant).where(
            ConversationParticipant.conversation_id.in_(conv_ids)))).scalars().all()
        for p in parts:
            parts_by_conv.setdefault(p.conversation_id, []).append(p)

    # Resolve counterparty display names in one pass.
    all_keys: List[str] = []
    for plist in parts_by_conv.values():
        for p in plist:
            all_keys.append(part_key(p))
    names = await display_names(db, all_keys)

    my_keys = await household_keys(db, actor)

    items = []
    for r in rows:
        cid = r[0]
        counterparty = None
        # A room has members and a support thread has a desk — neither has a
        # counterparty principal, so neither gets one invented for it.
        # ⚠ BOTH SIDES ARE YOURS is a normal thing here — one of your agents
        # buying a service from another of your agents is a real transaction
        # with a real fee — and the row is then named by the side that is not
        # the CALLER, so a household thread reads as itself, not as a blank.
        p, same_household = (None, False) if r[1] in ("org", "support") else pick_counterparty(
            r[1], parts_by_conv.get(cid, []), my_keys, actor.key,
            pair_key=r[6], created_by=created_by_key(r[16], r[17]))
        if p is not None:
            counterparty = {**counterparty_fields(p), "name": names.get(part_key(p), "")}
            if same_household:
                counterparty["same_household"] = True
        items.append({
            "id": cid, "kind": r[1], "title": r[2], "last_seq": int(r[3] or 0),
            "last_message_at": r[4].isoformat() if r[4] else None,
            "last_preview": r[5],
            "service_inflight": bool(r[7]) and
                (datetime.datetime.now(datetime.timezone.utc) - r[7]).total_seconds() < SERVICE_INFLIGHT_STALE_S,
            "created_at": r[8].isoformat() if r[8] else None,
            "unread": int(r[10] or 0),
            "muted": bool(r[11]),
            "my_state": want_state,
            "counterparty": counterparty,
            "mode": r[12], "topic": r[13], "org_id": r[14],
            "support_ticket_id": r[15],
        })
    next_cursor = items[-1]["last_message_at"] if len(items) == limit else None
    # §TWOAGENT V0441: the list's hosting line said "Same-registry only for now." on registries where a thread with
    # another registry is live. The list says which is true here, so the line can.
    from agentvault_registry.services import chat_federation as fed
    return {"conversations": items, "next_cursor": next_cursor, "state": state,
            "cross_registry": fed.federation_enabled()}


async def list_messages(db: AsyncSession, conversation_id: str, actor: Actor,
                        before_seq: Optional[int] = None, limit: int = 40, join: bool = False) -> dict:
    conv = await _get_conversation(db, conversation_id)
    # auto_join=True: the household rule — a developer reads the thread their
    # agent is active in (and vice versa); the materialized row carries their
    # own read/burn floors from here on.
    my_row = await resolve_membership(db, conv, actor, announce_ok=join)
    limit = max(1, min(int(limit or 40), PAGE_MAX))

    q = select(ChatMessage).where(
        ChatMessage.conversation_id == conv.id,
        ChatMessage.seq > int(my_row.hidden_before_seq or 0))
    if before_seq is not None:
        q = q.where(ChatMessage.seq < int(before_seq))
    q = q.order_by(ChatMessage.seq.desc()).limit(limit)
    msgs = list(reversed((await db.execute(q)).scalars().all()))

    # §TWOAGENT V0441: a REMOTE sender is named too. The loop asked only for developers and agents, so every message a
    # peer's principal wrote read with an empty sender_name and rendered as its raw key, on both sides of the first
    # cross-registry thread (`did:…@https://asia…` on EU, `did:…@https://eu…` on ASIA), although display_names names a
    # mirrored agent by its card and anyone else by the address.
    keys = [k for k in (sender_key_of(m) for m in msgs) if k]

    # Counterparty for the thread header — a deep link lands here with no list
    # row to carry it, so the thread answers for itself.
    parts = (await db.execute(select(ConversationParticipant).where(
        ConversationParticipant.conversation_id == conv.id))).scalars().all()
    my_keys = await household_keys(db, actor)
    # 🔴 BOTH SIDES ARE YOURS — and this is not an edge case: one of your agents
    # buying a service from another of your agents is a real, priced
    # transaction. "The side that is not me" then selected NOBODY, and the
    # thread came back with no counterparty at all (measured on the Commander's
    # own demo: "This thread has no service agent to call"). The rule, the
    # fallback to the side that is not the CALLER, and the order it reads the
    # participants in all live in pick_counterparty, which `list_conversations`
    # asks too (§FANOUTFIX: one predicate, two call sites).
    counterparty = None
    p, same_household = pick_counterparty(
        conv.kind, parts, my_keys, actor.key, pair_key=getattr(conv, "dm_pair_key", None),
        created_by=created_by_key(getattr(conv, "created_by_ptype", None), getattr(conv, "created_by_id", None)))
    if p is not None:
        keys.append(part_key(p))
        counterparty = {**counterparty_fields(p), "key": part_key(p), "same_household": same_household}

    names = await display_names(db, keys)
    if counterparty:
        counterparty["name"] = names.get(counterparty.pop("key"), "")
    out = []
    for m in msgs:
        d = serialize_message(m)
        d["sender_name"] = names.get(sender_key_of(m) or "", "")
        out.append(d)
    room = None
    if conv.kind == "org":
        # Live room state travels with the page: what the wall says (genesis),
        # how it is set (mode/topic), and what YOU may do here right now —
        # can_post from your row, ops from your LIVE org role.
        my_org_role = await actor_org_role(db, conv.org_id or "", actor)
        org_row = (await db.execute(sa_text(
            "SELECT name, settings FROM organizations WHERE id = :o"), {"o": conv.org_id})).first()
        live_name = org_row[0] if org_row else None
        # §OCOPTIN — the room tells its members when its work records are
        # public (§CHATDESK visibility law: nothing about a room is ever
        # observable that the room does not say to its own participants).
        # Read LIVE from settings so an opt-out clears the banner on next open.
        from agentvault_registry.services.org_policy import transparency_public, assistant_present
        _settings = org_row[1] if org_row and isinstance(org_row[1], dict) else None
        _tp_pub = transparency_public(_settings)
        room = {"org_id": conv.org_id, "title": live_name or conv.title,
                "mode": conv.mode, "topic": conv.topic, "genesis": conv.genesis,
                "my_can_post": bool(getattr(my_row, "can_post", True)),
                "my_org_role": my_org_role,
                "my_is_operator": my_org_role in ROOM_OPS_ROLES,
                "transparency_public": _tp_pub,
                # §ROOMBRAIN — the standing banner's source, read LIVE like transparency
                "assistant_present": assistant_present(_settings)}

    return {"conversation_id": conv.id, "kind": conv.kind,
            "last_seq": int(conv.last_seq or 0),
            "my_state": my_row.state,
            "my_last_read_seq": int(my_row.last_read_seq or 0),
            "counterparty": counterparty,
            "room": room,
            "service_inflight": bool(conv.service_inflight_at) and
                (datetime.datetime.now(datetime.timezone.utc) - conv.service_inflight_at).total_seconds() < SERVICE_INFLIGHT_STALE_S,
            "messages": out,
            "page_bound": limit,
            # §OURSTATE-6 — the two facts a reader is entitled to before they
            # type anything: how long this stays here, and whose machine it
            # stays on. The hosting line is the E2EE spike's honest
            # alternative to a promise we cannot keep (§11: v1 threads are
            # registry-hosted plaintext and the app says so).
            "retention_hours": conv.retention_hours,
            # §TWOAGENT V0441: the host, and every registry that keeps a copy (thread_hosting).
            "hosting": await thread_hosting(db, conv, parts)}


async def mark_read(db: AsyncSession, conversation_id: str, actor: Actor, seq: int) -> dict:
    conv = await _get_conversation(db, conversation_id)
    my_row = await resolve_membership(db, conv, actor)
    new_seq = max(int(my_row.last_read_seq or 0), min(int(seq), int(conv.last_seq or 0)))
    my_row.last_read_seq = new_seq          # monotonic: never decreases
    if actor.ptype == "developer":
        # The unread badge sums the developer's rows PLUS their agents' rows
        # (plan §4) — reading the thread as the human clears the whole
        # household's badge, or a read thread would stay marked unread forever
        # through the hand's row.
        await db.execute(sa_text("""
            UPDATE conversation_participants p SET last_read_seq = GREATEST(p.last_read_seq, :s)
            WHERE p.conversation_id = :cid AND p.ptype = 'agent'
              AND p.agent_did IN (SELECT did FROM agents WHERE creator_developer_id = :me)
        """), {"s": new_seq, "cid": conv.id, "me": actor.developer_id})
    await db.commit()
    return {"conversation_id": conv.id, "last_read_seq": new_seq}


async def set_state(db: AsyncSession, conversation_id: str, actor: Actor, action: str) -> dict:
    conv = await _get_conversation(db, conversation_id)
    my_row = await resolve_membership(db, conv, actor, announce_ok=True)
    before = my_row.state
    my_row.state = transition_state(before, action)
    notice = accepted_knock_notice(conv, before, my_row.state, my_row)
    name = actor.display_name
    if notice is not None and actor.ptype == "agent" and actor.agent_did:
        try:    # an agent actor's display name is its DID (#5): name it by its card, as the thread list does
            key = principal_key("agent", actor.agent_did)
            name = (await display_names(db, [key])).get(key) or name
        except Exception as e:  # noqa: BLE001 — a label; the DID in the notice still identifies the acceptor
            logger.debug("[CHAT] acceptor name lookup skipped: %s", e)
    await db.commit()
    if notice is not None:
        # §TWOAGENT #2: post-commit only (§ESDUP), and the knocker's notice can never fail the accept
        spawn(notify_request_accepted(notice, name))
    if getattr(conv, "host_registry", None) and before != my_row.state and my_row.state in ("active", "left") \
            and action != "decline":
        # §TWOAGENT G1 step 2: a MIRROR's accept (or leave) must reach the thread's host, which tells the knocker.
        # A decline stays here: a refusal the knocker cannot see is the consent half of the Requests lane.
        from agentvault_registry.services import chat_federation as _fed
        pkey = _fed.remote_key(await _participant_handle(db, my_row), _fed.self_base_url())
        spawn(_fed.announce_state_to_host(conv.host_registry, conv.remote_ref, pkey, my_row.state))
    return {"conversation_id": conv.id, "my_state": my_row.state}


async def _participant_handle(db: AsyncSession, row: ConversationParticipant) -> str:
    """How the thread's host knows one of OUR participants: an agent by its DID, a developer by handle or dev:N."""
    if row.ptype == "agent":
        return str(row.agent_did)
    h = (await db.execute(sa_text("SELECT handle FROM developers WHERE id = :d"), {"d": row.developer_id})).first()
    return h[0] if h and h[0] else f"dev:{row.developer_id}"


async def set_muted(db: AsyncSession, conversation_id: str, actor: Actor, muted: bool) -> dict:
    conv = await _get_conversation(db, conversation_id)
    my_row = await resolve_membership(db, conv, actor)
    my_row.muted = bool(muted)
    await db.commit()
    return {"conversation_id": conv.id, "muted": my_row.muted}


async def burn_for_me(db: AsyncSession, conversation_id: str, actor: Actor) -> dict:
    """Burn-for-me: history before this point stops existing for MY side. For a
    developer that is the whole household (their row plus their local agents'
    rows — otherwise the burned thread would resurface through the hand's row).
    The honest footnote (the other side may keep copies; the registry retains
    the thread) renders client-side at the moment of burning — law 5."""
    conv = await _get_conversation(db, conversation_id)
    my_row = await resolve_membership(db, conv, actor)
    floor = int(conv.last_seq or 0)
    my_row.hidden_before_seq = floor
    my_row.last_read_seq = max(int(my_row.last_read_seq or 0), floor)
    if actor.ptype == "developer":
        await db.execute(sa_text("""
            UPDATE conversation_participants p
            SET hidden_before_seq = :s, last_read_seq = GREATEST(p.last_read_seq, :s)
            WHERE p.conversation_id = :cid AND p.ptype = 'agent'
              AND p.agent_did IN (SELECT did FROM agents WHERE creator_developer_id = :me)
        """), {"s": floor, "cid": conv.id, "me": actor.developer_id})
    await db.commit()
    return {"conversation_id": conv.id, "hidden_before_seq": my_row.hidden_before_seq}


async def sync_since(db: AsyncSession, actor: Actor, since: Optional[str]) -> dict:
    """Polling catch-up for clients and agent runtimes: every message in my
    active threads since a timestamp, hidden floors respected, bound stated."""
    try:
        ts = (datetime.datetime.fromisoformat(since) if since
              else datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24))
    except ValueError:
        raise ChatError(422, "since must be an ISO timestamp")

    if actor.ptype == "developer":
        reach = _dev_reach_clause()
        params: Dict[str, Any] = {"me": actor.developer_id}
    else:
        reach = "(p.ptype = 'agent' AND lower(p.agent_did) = lower(:med))"
        params = {"med": actor.agent_did}
    params.update({"ts": ts, "lim": SYNC_MAX})

    rows = (await db.execute(sa_text(f"""
        SELECT m.id, m.conversation_id, m.seq, m.sender_ptype, m.sender_id, m.kind,
               m.body, m.card, m.reply_to, m.client_ref, m.created_at, m.deleted_at
        FROM chat_messages m
        JOIN conversation_participants p ON p.conversation_id = m.conversation_id
        WHERE ({reach}) AND p.state = 'active'
          AND m.created_at > :ts
          AND m.seq > COALESCE(p.hidden_before_seq, 0)
        ORDER BY m.created_at ASC
        LIMIT :lim
    """), params)).all()

    msgs = []
    seen = set()
    for r in rows:
        if r[0] in seen:            # dev + their agent both in a thread → one copy
            continue
        seen.add(r[0])
        deleted = r[11] is not None
        msgs.append({"id": r[0], "conversation_id": r[1], "seq": int(r[2]),
                     "sender_ptype": r[3], "sender_id": r[4],
                     "kind": "system" if deleted else r[5],
                     "body": None if deleted else r[6],
                     "card": None if deleted else r[7],
                     "deleted": deleted,
                     "reply_to": r[8], "client_ref": r[9],
                     "created_at": r[10].isoformat() if r[10] else None})
    return {"since": ts.isoformat(), "messages": msgs,
            "truncated": len(rows) >= SYNC_MAX, "bound": SYNC_MAX}


# ---------------------------------------------------------------------------
# Delivery — POST-COMMIT ONLY (§ESDUP: never announce what might roll back)
# ---------------------------------------------------------------------------

async def pending_agent_target(db: AsyncSession, conv: Conversation, target_ptype: str,
                               target_id: str) -> Optional[str]:
    """§TWOAGENT #1: the target AGENT's DID when its row in this conversation is 'pending' (a stranger's knock sits in
    its Requests lane), else None. A sibling's thread is born 'active', a blocker's is born 'left': neither is a knock."""
    if target_ptype != "agent" or not target_id:
        return None
    row = (await db.execute(select(ConversationParticipant).where(
        ConversationParticipant.conversation_id == conv.id,
        ConversationParticipant.ptype == "agent",
        ConversationParticipant.agent_did == target_id))).scalar_one_or_none()
    return target_id if row is not None and row.state == "pending" else None


async def notify_request_received(conv_id: str, conv_kind: str, recipient_agent_did: str,
                                  message: Optional[dict], sender_name: str) -> int:
    """§TWOAGENT #1: tell the OWNER of an agent that a stranger's first message is waiting in its Requests lane.
    Owner-scoped (never broadcast): the payload is the owner's own inbound message. Best-effort, like every webhook."""
    from agentvault_registry.background_tasks.reactor_helpers import dispatch_webhook_for_agents
    return await dispatch_webhook_for_agents(
        "chat.request.received",
        {"conversation_id": conv_id, "kind": conv_kind, "recipient_agent_did": recipient_agent_did,
         "message": message, "sender_name": sender_name,
         "answer_with": "POST /api/v1/chat/conversations/{conversation_id}/accept or /decline, as the recipient agent"},
        [recipient_agent_did], source_label="chat.request")


def accepted_knock_notice(conv: Conversation, previous_state: str, new_state: str,
                          acceptor_row: ConversationParticipant) -> Optional[dict]:
    """§TWOAGENT #2 (2026-09-23): what the KNOCKER should hear when its request is accepted, or None.

    #1 told the recipient's owner that a stranger knocked; nothing told the stranger that the door opened, so the run's
    knocker polled its thread for minutes. Only a real pending -> active flip of the accepting participant's row counts
    (a repeat accept is refused by the state machine before this). A DECLINE returns None on purpose: a refusal the
    knocker cannot see is the consent half of the Requests lane, like the absence of read receipts. The knocker is the
    conversation's creator; a creator accepting its own thread is not a knock."""
    if previous_state != "pending" or new_state != "active":
        return None
    kp, kid = str(conv.created_by_ptype or ""), str(conv.created_by_id or "")
    if kp not in ("agent", "developer") or not kid:
        return None
    by_id = str(acceptor_row.agent_did if acceptor_row.ptype == "agent"
                else (acceptor_row.remote_key if acceptor_row.ptype == "remote" else acceptor_row.developer_id))
    if kp == acceptor_row.ptype and kid.lower() == by_id.lower():
        return None
    return {"conversation_id": conv.id, "kind": conv.kind, "knocker_ptype": kp, "knocker_id": kid,
            "accepted_by_ptype": acceptor_row.ptype, "accepted_by": by_id}


async def notify_request_accepted(notice: dict, accepted_by_name: str) -> int:
    """§TWOAGENT #2: deliver `accepted_knock_notice` owner-scoped: to the owner of an AGENT knocker, or to a DEVELOPER
    knocker itself. Best-effort, like every webhook: the accept has already committed and never waits on this."""
    from agentvault_registry.background_tasks.reactor_helpers import (
        dispatch_webhook_event, dispatch_webhook_for_agents)
    data = dict(notice)
    data["accepted_by_name"] = accepted_by_name
    data["reply_with"] = "POST /api/v1/chat/conversations/{conversation_id}/messages: the thread is open both ways"
    if notice.get("knocker_ptype") == "agent":
        return await dispatch_webhook_for_agents("chat.request.accepted", data, [notice["knocker_id"]],
                                                 source_label="chat.request")
    try:
        dev_id = int(notice.get("knocker_id"))
    except (TypeError, ValueError):
        return 0
    return await dispatch_webhook_event("chat.request.accepted", data, source_label="chat.request",
                                        developer_id=dev_id)


async def recipients_snapshot(db: AsyncSession, conv: Conversation,
                              sender: Actor) -> List[dict]:
    """Active participants excluding the sender, with owner resolution for
    agents and the sender's block set applied (delivery skips whoever blocks
    the sender — the silent half of the block contract)."""
    parts = (await db.execute(select(ConversationParticipant).where(
        ConversationParticipant.conversation_id == conv.id,
        ConversationParticipant.state == "active"))).scalars().all()
    out = []
    keys = []
    for p in parts:
        if p.ptype == "remote":
            # §OURSTATE-3b: a remote participant is reached by the OUTBOX, not
            # by a websocket this registry does not own. Skipping them here is
            # what keeps "delivery" meaning one thing per audience.
            continue
        k = part_key(p)
        if k == sender.key:
            continue
        keys.append(k)
        out.append({"key": k, "ptype": p.ptype, "developer_id": p.developer_id,
                    "agent_did": p.agent_did, "muted": bool(p.muted)})
    blockers = await blocker_keys_against(db, sender.key, keys)
    out = [r for r in out if r["key"] not in blockers]
    agent_dids = [r["agent_did"] for r in out if r["ptype"] == "agent" and r["agent_did"]]
    owners = await agent_owner_map(db, agent_dids)
    for r in out:
        r["owner_developer_id"] = (r["developer_id"] if r["ptype"] == "developer"
                                   else owners.get(r["agent_did"] or ""))
    return out


async def fan_out_message(conv_id: str, conv_kind: str, message: dict,
                          recipients: List[dict], sender_name: str,
                          *, is_ping: bool = False,
                          sender_owner_dev_id: Optional[int] = None) -> None:
    """Fire-and-forget delivery, called AFTER the insert committed.
    WS topic per recipient developer (including the sender's own household —
    that is cross-device sync of your own sends, not a notification); notify()
    as the offline fallback for everyone EXCEPT the sender's household
    (Redis-shared presence (§PRESENCE) + the catalog's Redis coalescing keep
    the bell sane — both guards are cross-worker; the old per-worker dict
    wording here outlived its fix); webhook for agent participants on the
    proven retry rail.

    D6-826 (agentvault2-aa, 2026-10-26): the order is the agent recipients' owners first (their hook, in a task of its
    own), then the WS sends, then the offline notices in one task of their own, each bounded. The webhook used to be
    created only after every developer's notice had been awaited, and a notice ends in the themed mail, so one slow or
    hung mail held the owner's hook back, or left it unsent."""
    try:
        from agentvault_registry.routers.websocket import manager
    except Exception:  # noqa: BLE001
        manager = None

    agent_dids = [r["agent_did"] for r in recipients if r["ptype"] == "agent" and r["agent_did"]]
    if agent_dids:
        spawn(_tell_agent_owners(conv_id, conv_kind, message, agent_dids),
              what=f"chat.message.received for message {message.get('id')} (seq {message.get('seq')}) in {conv_id} "
                   f"({len(agent_dids)} agent recipient(s))")

    envelope = {"type": "chat.ping" if is_ping else "chat.message",
                "data": {"conversation_id": conv_id, "kind": conv_kind,
                         "message": message, "sender_name": sender_name}}

    dev_targets: Dict[int, bool] = {}   # dev_id -> muted (True only if EVERY row muted)
    for r in recipients:
        dev_id = r.get("owner_developer_id")
        if dev_id is None:
            continue
        prev = dev_targets.get(int(dev_id))
        dev_targets[int(dev_id)] = r["muted"] if prev is None else (prev and r["muted"])
    if sender_owner_dev_id is not None and int(sender_owner_dev_id) not in dev_targets:
        dev_targets[int(sender_owner_dev_id)] = True   # WS sync only, never notify

    notices: List[int] = []
    for dev_id, muted in dev_targets.items():
        if manager is not None:
            try:
                await manager.broadcast_to_subscribers(f"chat:dev:{dev_id}", dict(envelope))
            except Exception as e:  # noqa: BLE001
                logger.debug("[CHAT] WS fan-out to dev %s failed: %s", dev_id, e)
        if muted or (sender_owner_dev_id is not None and dev_id == int(sender_owner_dev_id)):
            continue   # you are never notified about your own household's send
        notices.append(dev_id)
    if notices:
        spawn(_notify_absent(conv_id, message, notices, sender_name, is_ping, manager),
              what=f"the offline notices of message {message.get('id')} (seq {message.get('seq')}) in {conv_id} "
                   f"({len(notices)} developer(s))")


async def _tell_agent_owners(conv_id: str, conv_kind: str, message: dict, agent_dids: List[str]) -> int:
    """chat.message.received to the owners of the agent recipients (owner-scoped, on the webhook retry rail), and one
    INFO line naming the message and how many hooks were told, so a message whose owner heard nothing has a line."""
    from agentvault_registry.background_tasks.reactor_helpers import dispatch_webhook_for_agents
    told = await dispatch_webhook_for_agents(
        "chat.message.received",
        {"conversation_id": conv_id, "kind": conv_kind, "message": message},
        agent_dids, source_label="chat")
    logger.info("[CHAT] chat.message.received for message %s (seq %s) in %s: %d agent recipient(s), %s hook(s) told",
                message.get("id"), message.get("seq"), conv_id, len(agent_dids), told)
    return told


async def _notify_absent(conv_id: str, message: dict, notices: List[int], sender_name: str, is_ping: bool,
                         manager: Any) -> None:
    """The offline notices, one developer after another, each given NOTIFY_BOUND_S: a notice that takes longer is
    given up and logged, and the next developer is still told."""
    from agentvault_registry.background_tasks.push_notify import notify
    preview = message.get("body") or (
        f"[{(message.get('card') or {}).get('type', 'card')}]" if message.get("card") else "…")
    for dev_id in notices:
        # §PRESENCE — this used to read `manager.active_connections`, a PER-WORKER
        # dict, so it only ever suppressed the duplicate when the recipient's
        # socket happened to live on the worker handling this send: ~1 time in 39
        # on registry-a. `is_present()` asks Redis, so any worker can see a live
        # session — and it answers True ONLY on a positive result. No Redis, no
        # key, any exception ⇒ False ⇒ we notify. A duplicate bell is a nuisance;
        # a wrongly suppressed one is a message nobody is ever told about.
        has_live_session = False
        if manager is not None:
            try:
                has_live_session = await manager.is_present(str(dev_id))
            except Exception:  # noqa: BLE001
                has_live_session = False
        if has_live_session:
            continue   # they already received it live — don't double-notify
        try:
            await asyncio.wait_for(notify(
                "chat.ping" if is_ping else "chat.message", [dev_id],
                title=sender_name or "OurChat",
                message=("pinged you" if is_ping else str(preview)[:PREVIEW_LEN]),
                click=f"/ui#/pocket/ourchat/{conv_id}"), NOTIFY_BOUND_S)
        except asyncio.TimeoutError:
            logger.warning("[CHAT] the notice of message %s in %s to developer %s took over %ss: given up, the next "
                           "developer is still told", message.get("id"), conv_id, dev_id, NOTIFY_BOUND_S)
        except Exception as e:  # noqa: BLE001
            logger.warning("[CHAT] the notice of message %s in %s to developer %s failed: %s: %s",
                           message.get("id"), conv_id, dev_id, type(e).__name__, e)


# ---------------------------------------------------------------------------
# Service-call helpers (the in-flight CAS; the composition itself lives in the
# router because it needs the raw request JWT)
# ---------------------------------------------------------------------------

async def claim_service_inflight(db: AsyncSession, conversation_id: str) -> bool:
    """CAS the one-in-flight flag. True = claimed. A stale claim (crashed
    worker) older than SERVICE_INFLIGHT_STALE_S is reclaimable."""
    row = (await db.execute(sa_text("""
        UPDATE conversations SET service_inflight_at = now()
        WHERE id = :cid AND (service_inflight_at IS NULL
                             OR service_inflight_at < now() - make_interval(secs => :stale))
        RETURNING id
    """), {"cid": conversation_id, "stale": SERVICE_INFLIGHT_STALE_S})).first()
    await db.commit()
    return row is not None


async def release_service_inflight(db: AsyncSession, conversation_id: str) -> None:
    await db.execute(sa_text(
        "UPDATE conversations SET service_inflight_at = NULL WHERE id = :cid"),
        {"cid": conversation_id})
    await db.commit()


# ---------------------------------------------------------------------------
# §OURSTATE-2 — org rooms, operators, and the Genesis (mig 0156_chat_rooms)
#
# The chat is the org's admin panel, but org membership TRUTH never moves:
# roles are read LIVE from organization_members on every gate, participant
# rows are only room furniture (read floors, can_post, mute), and org removal
# is the FE calling the REAL org rail with an explicit named toggle — this
# module cannot express an org mutation by construction.
# ---------------------------------------------------------------------------

ROOM_ROLE_RANK = {"owner": 3, "admin": 2, "member": 1, "guest": 0}
ROOM_OPS_ROLES = ("owner", "admin")
ROOM_ACTIONS = ("kick", "mute", "unmute", "mode", "topic", "motd",
                # §ROOMBRAIN — add/remove @assistant (org admins; visible rows both ways)
                "assistant_on", "assistant_off")
GENESIS_MAX = 2000
GENESIS_HISTORY_KEEP = 10


def room_pair_key(org_id: str) -> str:
    return f"org|{org_id}"


def can_act_on(my_role: Optional[str], target_role: Optional[str]) -> bool:
    """Pure: an operator may act on a STRICTLY lower org rank (or on a
    principal with no org role at all — e.g. a room-joined agent)."""
    if my_role not in ROOM_OPS_ROLES:
        return False
    if target_role is None:
        return True
    return ROOM_ROLE_RANK.get(my_role, 0) > ROOM_ROLE_RANK.get(target_role, 0)


async def org_role_of(db: AsyncSession, org_id: str, developer_id: Optional[int]) -> Optional[str]:
    if developer_id is None:
        return None
    row = (await db.execute(sa_text(
        "SELECT role FROM organization_members "
        "WHERE organization_id = :o AND developer_id = :d AND is_active = true LIMIT 1"
    ), {"o": org_id, "d": int(developer_id)})).first()
    return str(row[0]).lower() if row else None


async def _agent_org_id(db: AsyncSession, did: str) -> Optional[str]:
    row = (await db.execute(sa_text(
        "SELECT organization_id FROM agents WHERE lower(did) = lower(:d)"
    ), {"d": did})).first()
    return row[0] if row and row[0] else None


async def actor_org_role(db: AsyncSession, org_id: str, actor: Actor) -> Optional[str]:
    """The actor's LIVE org standing: a developer's organization_members role,
    or 'member' for an agent assigned to the org (agents hold no org roles)."""
    if actor.ptype == "developer":
        return await org_role_of(db, org_id, actor.developer_id)
    if actor.ptype == "agent" and actor.agent_did:
        if (await _agent_org_id(db, actor.agent_did)) == org_id:
            return "member"
    return None


async def open_org_room(db: AsyncSession, actor: Actor, org_id: str) -> Tuple[Conversation, bool, ConversationParticipant]:
    """Open (or dedup-return) THE room for an org. One room per org, keyed on
    the same UNIQUE pair-key column ('org|{org_id}'). Membership gate is the
    LIVE org table, not a participant row."""
    role = await actor_org_role(db, org_id, actor)
    if role is None:
        raise ChatError(403, "you are not an active member of this organization")

    org = (await db.execute(sa_text(
        "SELECT id, name, chat_enabled, chat_open_policy "
        "FROM organizations WHERE id = :o AND is_active = true"
    ), {"o": org_id})).first()
    if org is None:
        raise ChatError(404, "organization not found")

    # §OURSTATE-6 — a room exists because the org WANTED one. Off by default,
    # and who may switch it on is the org's own setting: a room nobody asked
    # for is the empty conversation that buried the real ones.
    if not bool(org[2]):
        if str(org[3] or "owner_admin") == "members" or role in ROOM_OPS_ROLES:
            await db.execute(sa_text(
                "UPDATE organizations SET chat_enabled = true WHERE id = :o"), {"o": org_id})
        else:
            raise ChatError(403, "this organization has not turned its chat on — "
                                 "an owner or admin can enable it")

    pk = room_pair_key(org_id)
    existing = (await db.execute(select(Conversation).where(
        Conversation.dm_pair_key == pk))).scalars().first()
    if existing is not None:
        my_row = await resolve_membership(db, existing, actor)
        if my_row.state == "left":
            my_row.state = "active"     # rejoining your own org's room is opening it
        await db.commit()
        return existing, False, my_row

    conv = Conversation(kind="org", org_id=org_id, title=str(org[1] or "Org room"),
                        created_by_ptype=actor.ptype, created_by_id=actor.sender_id,
                        dm_pair_key=pk)
    db.add(conv)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        existing = (await db.execute(select(Conversation).where(
            Conversation.dm_pair_key == pk))).scalars().first()
        if existing is None:
            raise ChatError(500, "room create raced and could not recover")
        my_row = await resolve_membership(db, existing, actor)
        await db.commit()
        return existing, False, my_row

    my_row = ConversationParticipant(
        conversation_id=conv.id, ptype=actor.ptype,
        developer_id=actor.developer_id if actor.ptype == "developer" else None,
        agent_did=actor.agent_did if actor.ptype == "agent" else None,
        role="owner" if role == "owner" else "member", state="active")
    db.add(my_row)
    await db.flush()

    # §ROOMUNREAD — give EVERY current org member a row the moment the room is
    # born. Rows are still not authority (resolve_membership re-derives the org
    # table on every touch), but they are what puts the room in the thread list,
    # in /sync and in the WS fan-out — so without them a room could be opened,
    # posted in, and never once signal the people it was opened for.
    # Someone who joins the org LATER still materializes on first touch, and
    # list_org_rooms counts their unread from `joined_at` until then.
    # ⚠ TWO traps in this one statement, both already in doctrine and both hit:
    #   1. asyncpg infers ONE type per parameter. `:c` was an INSERT value AND a
    #      comparison operand, so it deduced text in one place and varchar in the
    #      other: "inconsistent types deduced for parameter $1". Every use is
    #      pinned to text, and the compared COLUMN is cast, exactly as
    #      create_block() above already had to do.
    #   2. A bare try/except around a failing statement does NOT contain it — the
    #      surrounding transaction is left aborted and every later command in the
    #      request dies "current transaction is aborted". Measured: the room open
    #      returned 500 while this WARNING said it had merely been skipped. The
    #      savepoint is what makes the except honest.
    try:
        async with db.begin_nested():
            await db.execute(sa_text("""
                INSERT INTO conversation_participants
                    (id, conversation_id, ptype, developer_id, role, state,
                     last_read_seq, muted, joined_at, can_post)
                SELECT gen_random_uuid()::text, CAST(:c AS text), 'developer',
                       om.developer_id,
                       CASE WHEN lower(om.role) = 'owner' THEN 'owner' ELSE 'member' END,
                       'active', 0, false, now(), true
                FROM organization_members om
                WHERE om.organization_id::text = :o AND om.is_active = true
                  AND om.developer_id <> :me
                  AND NOT EXISTS (
                    SELECT 1 FROM conversation_participants x
                    WHERE x.conversation_id::text = CAST(:c AS text)
                      AND x.ptype = 'developer'
                      AND x.developer_id = om.developer_id)
                ON CONFLICT DO NOTHING
            """), {"c": str(conv.id), "o": str(org_id), "me": actor.developer_id or -1})
    except Exception as e:  # noqa: BLE001 — a room that opens for one is better than none
        logger.warning("org room member materialization failed for org %s: %s", org_id, e)

    # §OURSTATE-6 — the org's AGENTS are in the room from the first second.
    # 2a mirrored `organization_members`, which holds humans only, so a freshly
    # opened room contained the person who opened it and nobody to talk to —
    # on a network whose entire point is that the agents are the workforce.
    await seed_org_agents(db, conv)

    await db.commit()
    return conv, True, my_row


async def seed_org_agents(db: AsyncSession, conv: Conversation) -> int:
    """Put the org's active agents in its room. Idempotent.

    They are seeded as participants so they are ADDRESSABLE (`@name`) and
    listed in the member sheet — the same lazy participant rows a human gets,
    created eagerly here because an empty room is the thing this fixes. Their
    org membership remains the truth in `agents.organization_id`; a participant
    row is furniture, exactly as it is for humans (2a).
    """
    if conv.kind != "org" or not conv.org_id:
        return 0
    rows = (await db.execute(sa_text(
        "SELECT did FROM agents WHERE organization_id = :o AND status = 'active' "
        "ORDER BY created_at LIMIT 50"
    ), {"o": conv.org_id})).all()
    seeded = 0
    for r in rows:
        did = r[0]
        exists = (await db.execute(sa_text(
            "SELECT 1 FROM conversation_participants "
            "WHERE conversation_id = :c AND ptype = 'agent' AND agent_did = :d"
        ), {"c": conv.id, "d": did})).first()
        if exists:
            continue
        db.add(ConversationParticipant(
            conversation_id=conv.id, ptype="agent", agent_did=did,
            role="member", state="active"))
        seeded += 1
    if seeded:
        await db.flush()
    return seeded


async def list_org_rooms(db: AsyncSession, actor: Actor) -> dict:
    """The rooms section — only the orgs that ACTUALLY want a room.

    §OURSTATE-6: this used to return every org the developer belonged to,
    whether or not anyone had ever opened its room, so the section filled with
    empty conversations and the one real room was lost among them. Enabled
    rooms are listed; the rest are returned SEPARATELY as `enableable`, so an
    owner can still start one without the app pretending they already have it.
    """
    if actor.ptype != "developer":
        return {"rooms": [], "enableable": []}
    # §ROOMUNREAD — this returned NO unread count of any kind, so a room you
    # had not yet spoken in was silent: absent from the thread list (that list
    # joins participant rows, and only the opener has one), absent from /sync,
    # and rendered here with the org's TOPIC instead of the last message. Someone
    # posted "@everyone standup at 10" and every member who had never spoken saw
    # an unchanged screen. Measured on frame-c 2026-08-28.
    #
    # With a participant row the count is the normal seq arithmetic. WITHOUT one
    # there is no read pointer, so "unread" is counted from the moment you JOINED
    # THE ORG — bounded and meaningful, where `last_seq` would greet a new hire
    # with a badge of every message the room ever carried. A row in state 'left'
    # counts 0: leaving deliberately should not nag.
    rows = (await db.execute(sa_text("""
        SELECT o.id, o.name, om.role, c.id, c.mode, c.topic, c.last_message_at,
               c.last_preview, o.chat_enabled, o.chat_open_policy,
               CASE
                 WHEN c.id IS NULL THEN 0
                 WHEN p.id IS NOT NULL AND p.state = 'active'
                   THEN GREATEST(0, COALESCE(c.last_seq, 0)
                        - GREATEST(COALESCE(p.last_read_seq, 0),
                                   COALESCE(p.hidden_before_seq, 0)))
                 WHEN p.id IS NOT NULL THEN 0
                 ELSE (SELECT count(*) FROM chat_messages m
                       WHERE m.conversation_id = c.id
                         AND m.created_at > om.joined_at
                         AND m.deleted_at IS NULL)
               END AS unread
        FROM organization_members om
        JOIN organizations o ON o.id = om.organization_id AND o.is_active = true
        LEFT JOIN conversations c ON c.dm_pair_key = ('org|' || o.id)
        LEFT JOIN conversation_participants p
               ON p.conversation_id = c.id
              AND p.ptype = 'developer'
              AND p.developer_id = om.developer_id
        WHERE om.developer_id = :me AND om.is_active = true
        ORDER BY o.name
    """), {"me": actor.developer_id})).all()

    rooms, enableable = [], []
    for r in rows:
        role = str(r[2] or "member").lower()
        policy = str(r[9] or "owner_admin")
        if bool(r[8]):
            # §OURCHAT-ORG — the POLICY travels with an enabled room too. It
            # used to be returned only on the `enableable` half, so a surface
            # showing the live setting for a room that EXISTS had nothing to
            # read and fell back to a default: the desktop card displayed
            # "owners and admins" over an org whose real policy was `members`.
            # A control that shows a default as if it were the truth is the
            # label-disagrees-with-the-branch defect, on a permission.
            rooms.append({"org_id": r[0], "org_name": r[1], "my_org_role": role,
                          "conversation_id": r[3], "mode": r[4], "topic": r[5],
                          "last_message_at": r[6].isoformat() if r[6] else None,
                          "last_preview": r[7],
                          "unread": int(r[10] or 0),
                          "policy": policy,
                          "may_disable": policy == "members" or role in ROOM_OPS_ROLES})
        else:
            # Whether YOU may switch it on, said plainly rather than discovered
            # by pressing a button that 403s.
            may = policy == "members" or role in ROOM_OPS_ROLES
            enableable.append({"org_id": r[0], "org_name": r[1], "my_org_role": role,
                               "policy": policy, "may_enable": may})
    return {"rooms": rooms, "enableable": enableable}


def _registry_display_name() -> str:
    """This registry's own name, for the hosting line.

    Derived exactly the way `registry_card_builder` derives the card's
    `registry_name`, so a thread can never claim to be hosted somewhere the
    signed card disagrees with. ⚠ Cloud-ops set `REGISTRY_NAME` to the DOCKER
    CONTAINER name and carry the canonical federation name separately — using
    the wrong one would print "cloud-op-op-tokyo" at a human.
    """
    import os
    try:
        from ..config import settings
        fallback = getattr(settings, "REGISTRY_NAME", "") or ""
    except Exception:  # noqa: BLE001
        fallback = os.getenv("REGISTRY_NAME", "")
    return os.environ.get("REGISTRY_FEDERATION_NAME") or fallback or "this registry"


def hosting_summary(host: str, holders: Iterable[str], here: str, names: Dict[str, str]) -> dict:
    """The honest hosting block (§OURSTATE-6) from registry origins: `host` holds the thread, every other origin in
    `holders` keeps a copy, `here` is this registry, `names` maps an origin to the name a person reads.

    §TWOAGENT V0441: the block always named THIS registry, so ASIA's mirror of an EU-hosted thread said "Hosted by
    ASIA — the operator can read this thread" (its `host_registry` is EU), and both sides were silent about the other
    registry's copy, which that registry's operator can read just the same. Pure, so it is tested without a database."""
    copies: List[str] = []
    for o in holders:
        if o and o != host and o not in copies:
            copies.append(o)
    host_name = names.get(host) or host or "this registry"
    copy_names = [names.get(o) or o for o in copies]
    if copy_names:
        says = (f"hosted by {host_name}, copied to {', '.join(copy_names)} — the operator of each can read this "
                "thread")
    else:
        says = f"hosted by {host_name} — the operator can read this thread"
    return {"registry": host_name, "here": host == here, "copies": copy_names, "plaintext": True, "says": says}


async def thread_hosting(db: AsyncSession, conv: Any, parts: Iterable[Any]) -> dict:
    """Who holds this thread's bytes: its host and every registry a remote participant calls home (each keeps a copy).
    A thread with no remote participant and no host elsewhere is held here alone, as before."""
    here_name = _registry_display_name()
    remote = [p for p in parts if getattr(p, "ptype", None) == "remote"]
    if not getattr(conv, "host_registry", None) and not remote:
        return hosting_summary("here", ["here"], "here", {"here": here_name})
    from agentvault_registry.services import chat_federation as fed
    here = fed.origin(fed.self_base_url()) or "here"
    host = fed.origin(conv.host_registry) if getattr(conv, "host_registry", None) else here
    holders: List[str] = [host]
    for p in remote:
        parsed = fed.parse_remote_key(getattr(p, "remote_key", None) or "")
        if parsed:
            holders.append(fed.origin(parsed[1]))
    holders.append(here)
    names = await fed.registry_display_names(db, [o for o in holders if o != here])
    names[here] = here_name
    return hosting_summary(host, holders, here, names)


RETENTION_CHOICES = (1, 24, 168, 720)     # 1h · 1d · 1w · 30d


async def set_retention(db: AsyncSession, conversation_id: str, actor: Actor,
                        hours: Optional[int]) -> dict:
    """Set (or clear) this thread's disappearing timer.

    Either participant may set it, and BOTH are told: a timer one side could
    set privately would be a promise about the other side's copy that nobody
    can keep. The change posts a visible system row, the same way a moderation
    act does in a room.

    ⚠ The honest sentence, which the caller renders verbatim: this deletes the
    messages from THIS registry. It cannot reach a copy the other side already
    exported, and it does not pretend to.
    """
    conv = await _get_conversation(db, conversation_id)
    my_row = await _my_row(db, conv.id, actor)
    if my_row is None or my_row.state not in ("active", "pending"):
        raise ChatError(403, "not a participant in this conversation")
    if hours is not None:
        if int(hours) not in RETENTION_CHOICES:
            raise ChatError(422, f"a timer is one of {RETENTION_CHOICES} hours, or none")
        conv.retention_hours = int(hours)
    else:
        conv.retention_hours = None
    conv.retention_set_by = actor.key
    conv.retention_set_at = datetime.datetime.now(datetime.timezone.utc)

    body = (f"retention.{conv.retention_hours}h" if conv.retention_hours
            else "retention.off")
    msg, _dup = await insert_message(
        db, conv, my_row, actor, "system", body, None,
        client_ref=str(uuid.uuid4()), rail_author=True)

    return {"conversation_id": conv.id, "retention_hours": conv.retention_hours,
            "set_by": actor.display_name,
            "system_message": serialize_message(msg),
            "note": ("this deletes messages from this registry on a schedule; it "
                     "cannot reach a copy the other side already saved")}


async def room_posting_gate(db: AsyncSession, conv: Conversation,
                            my_row: ConversationParticipant, actor: Actor) -> None:
    """The room's speech gates, checked at insert time with LIVE org roles:
    a /muted row cannot post; announce mode admits only org owner/admin."""
    if conv.kind != "org":
        return
    if not bool(getattr(my_row, "can_post", True)):
        raise ChatError(403, "a room operator muted you here — you can read, not post")
    if conv.mode == "announce":
        role = await actor_org_role(db, conv.org_id or "", actor)
        if role not in ROOM_OPS_ROLES:
            raise ChatError(403, "this room is announce-only — org owners and admins post")


def _room_system_card(by: Actor, by_name: str, action: str,
                      target_name: Optional[str] = None, value: Optional[str] = None) -> dict:
    d: Dict[str, Any] = {"by": by.key, "by_name": by_name, "action": action}
    if target_name:
        d["target_name"] = target_name
    if value is not None:
        d["value"] = value
    return d


async def room_action(db: AsyncSession, conversation_id: str, actor: Actor,
                      action: str, target_ptype: Optional[str] = None,
                      target_id: Optional[str] = None, value: Optional[str] = None) -> dict:
    """One room operation. Gated on the LIVE org role; refuses upward action;
    EVERY act posts a visible system row in the room (the in-band audit trail
    on top of the org's own server-side audit log)."""
    if action not in ROOM_ACTIONS:
        raise ChatError(422, f"unknown room action {action!r}")
    conv = await _get_conversation(db, conversation_id)
    if conv.kind != "org":
        raise ChatError(409, "room actions run only in org rooms")
    my_row = await resolve_membership(db, conv, actor)
    my_role = await actor_org_role(db, conv.org_id or "", actor)
    if my_role not in ROOM_OPS_ROLES:
        raise ChatError(403, "room operations need an org owner or admin")

    target_row: Optional[ConversationParticipant] = None
    target_role: Optional[str] = None
    target_name = None
    if action in ("kick", "mute", "unmute"):
        if not target_ptype or target_id is None:
            raise ChatError(422, f"{action} needs a target")
        t_actor = Actor(target_ptype,
                        developer_id=int(target_id) if target_ptype == "developer" else None,
                        agent_did=str(target_id) if target_ptype == "agent" else None)
        if t_actor.key == actor.key:
            raise ChatError(422, "you cannot target yourself")
        target_row = await _my_row(db, conv.id, t_actor)
        if target_row is None:
            raise ChatError(404, "target is not in this room")
        if target_ptype == "developer":
            target_role = await org_role_of(db, conv.org_id or "", int(target_id))
        if not can_act_on(my_role, target_role):
            raise ChatError(403, f"a {my_role} cannot act on a {target_role or 'peer'} of equal or higher rank")
        names = await display_names(db, [t_actor.key])
        target_name = names.get(t_actor.key, str(target_id))

    if action == "kick":
        target_row.state = "left"           # ROOM removal only — org removal is
        target_row.can_post = True          # the FE's explicit toggle on the org rail
    elif action == "mute":
        target_row.can_post = False
    elif action == "unmute":
        target_row.can_post = True
    elif action == "mode":
        if value not in ("open", "announce"):
            raise ChatError(422, "mode is 'open' or 'announce'")
        conv.mode = value
    elif action == "topic":
        conv.topic = (value or "")[:200] or None
    elif action == "motd":
        stated = (value or "")[:GENESIS_MAX]
        old = conv.genesis or {}
        history = list(old.get("history") or [])
        if old.get("stated"):
            history.append({"stated": old.get("stated"),
                            "updated_by": old.get("updated_by"),
                            "updated_at": old.get("updated_at")})
        conv.genesis = {"stated": stated, "updated_by": actor.key,
                        "updated_by_name": actor.display_name,
                        "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        "history": history[-GENESIS_HISTORY_KEEP:]}
    elif action in ("assistant_on", "assistant_off"):
        # §ROOMBRAIN — the ONE door that writes room_assistant_present (the
        # settings PUT refuses the key, naming this op). Plain-json settings
        # column: read-modify-write the whole object (the §V0122/§ORGSPEND
        # pattern), never a jsonb operator.
        row = (await db.execute(sa_text(
            "SELECT settings FROM organizations WHERE id = :o"), {"o": conv.org_id})).first()
        merged = dict(row[0]) if row and isinstance(row[0], dict) else {}
        merged["room_assistant_present"] = (action == "assistant_on")
        await db.execute(sa_text(
            "UPDATE organizations SET settings = CAST(:s AS JSON) WHERE id = :o"
        ), {"s": json.dumps(merged), "o": conv.org_id})

    # The visible system row — server-authored, closed to clients.
    msg, _dup = await insert_message(
        db, conv, my_row, actor, "system", f"room.{action}",
        _room_system_card(actor, actor.display_name, action, target_name, value),
        client_ref=str(uuid.uuid4()), rail_author=True)

    return {"conversation_id": conv.id, "action": action,
            "mode": conv.mode, "topic": conv.topic, "genesis": conv.genesis,
            "system_message": serialize_message(msg)}


async def room_members(db: AsyncSession, conversation_id: str, actor: Actor) -> dict:
    """The room's member sheet: participant rows joined with LIVE org roles
    and display names. Any active room member may look; ops stay gated at
    room_action. Bounded to the participant table — a member who never opened
    the room is not listed (they materialize on first touch, by design)."""
    conv = await _get_conversation(db, conversation_id)
    if conv.kind != "org":
        raise ChatError(409, "member sheets exist only for org rooms")
    await resolve_membership(db, conv, actor)   # 403s non-members

    parts = (await db.execute(select(ConversationParticipant).where(
        ConversationParticipant.conversation_id == conv.id,
        ConversationParticipant.state == "active"))).scalars().all()

    dev_roles: Dict[int, str] = {}
    dev_ids = [p.developer_id for p in parts if p.ptype == "developer" and p.developer_id is not None]
    if dev_ids:
        rows = (await db.execute(sa_text(
            "SELECT developer_id, role FROM organization_members "
            "WHERE organization_id = :o AND is_active = true AND developer_id = ANY(:d)"
        ), {"o": conv.org_id, "d": dev_ids})).all()
        dev_roles = {int(r[0]): str(r[1]).lower() for r in rows}

    keys = [part_key(p)
            for p in parts]
    names = await display_names(db, keys)

    members = []
    for p in parts:
        k = part_key(p)
        members.append({
            "ptype": p.ptype,
            "developer_id": p.developer_id,
            "agent_did": p.agent_did,
            "name": names.get(k, ""),
            "org_role": dev_roles.get(int(p.developer_id)) if p.ptype == "developer" and p.developer_id is not None else None,
            "can_post": bool(getattr(p, "can_post", True)),
            "is_me": k == actor.key,
        })
    members.sort(key=lambda m: (-(ROOM_ROLE_RANK.get(m["org_role"] or "", -1)), (m["name"] or "").lower()))
    return {"conversation_id": conv.id, "org_id": conv.org_id,
            "members": members, "note": "members who have opened the room"}


# ---------------------------------------------------------------------------
# §OURSTATE-2 — AWAY MODE v1 (the Bouncer, stage-only)
#
# The IRC bouncer kept your name on the channel while you slept. Here your
# stand-in is an economic actor with its own identity — so the ONE thing it
# may never do is act economically. v1 law, enforced in this module:
#
#   * ONE reply per thread, ever (idempotent on client_ref `away-{conv}`).
#   * It DISCLOSES itself as software, by name, in the first sentence.
#   * It offers only what is already free: who it is, and how to ask for a
#     quote. It spends NOTHING, accepts NOTHING, signs NOTHING — no money
#     card, no service call, no contract. Everything the stranger wants is
#     STAGED for the owner, who reads every word because the thread is theirs.
#   * Strangers only (a request-state thread), dm only — NEVER an org room,
#     never an existing conversation.
#   * Off by default; per-thread kill switch; the owner's designation lives in
#     the allowlisted `pocket.away` pref (no new table, no new authority).
# ---------------------------------------------------------------------------

AWAY_PREF_KEY = "pocket.away"


async def away_config(db: AsyncSession, developer_id: int) -> Optional[dict]:
    """The owner's away designation, or None. Shape (FE-owned):
    {enabled: bool, agent_did: str, note?: str, threads_off?: [conv_id]}"""
    row = (await db.execute(sa_text(
        "SELECT value FROM developer_prefs WHERE developer_id = :d AND key = :k"
    ), {"d": int(developer_id), "k": AWAY_PREF_KEY})).first()
    if not row or not row[0]:
        return None
    val = row[0]
    if isinstance(val, str):
        try:
            val = json.loads(val)
        except ValueError:
            return None
    return val if isinstance(val, dict) else None


def away_should_answer(cfg: Optional[dict], conv_kind: str, target_state: str,
                       conversation_id: str) -> bool:
    """Pure: the v1 gate. Strangers (pending) + dm only, enabled, designated,
    and this thread not individually silenced."""
    if not cfg or not cfg.get("enabled") or not cfg.get("agent_did"):
        return False
    if conv_kind != "dm" or target_state != "pending":
        return False
    off = cfg.get("threads_off") or []
    return conversation_id not in off


def away_disclosure(agent_name: str, owner_name: str, note: str = "",
                    authority: Optional[dict] = None) -> str:
    """The disclosure sentence (law 3: software says so, first, by name).
    Assembled here so the wording cannot drift between call sites.

    §OURSTATE-5b: when a LIVE capability plus a liability mandate actually back
    this stand-in, the second sentence states the ceiling instead of denying
    one. With no authority — the default, and the case for every existing
    designation — the v1 wording stands unchanged, word for word.
    """
    if authority and authority.get("authorized"):
        from ..services.chat_authority import authority_sentence
        middle = authority_sentence(authority, agent_name, owner_name)
    else:
        middle = (f"I can tell you what I do and quote a price; I cannot accept work, "
                  f"sign anything or move money.")
    line = (f"{agent_name} here — I am software, answering while {owner_name} is away. "
            f"{middle} {owner_name} reads this thread.")
    if note:
        line += f"\n\n{owner_name} left a note: {note.strip()[:280]}"
    return line


async def away_answer(db: AsyncSession, conv: Conversation, owner_dev_id: int) -> Optional[dict]:
    """Post the ONE away reply as the designated agent. Returns the serialized
    message, or None when away is off / already answered / the designation no
    longer holds. Never raises into the caller's request path."""
    try:
        cfg = await away_config(db, owner_dev_id)
        their = await _my_row(db, conv.id, Actor("developer", developer_id=owner_dev_id))
        if their is None or not away_should_answer(cfg, conv.kind, their.state, conv.id):
            return None

        did = str(cfg["agent_did"])
        row = await _agent_row(db, did)
        # The designation must still hold RIGHT NOW: the agent must exist, be
        # active, and still belong to the owner. A revoked or transferred agent
        # simply stops answering — the stand-in cannot outlive its mandate.
        if row is None or str(row[1] or "").lower() not in ("active", ""):
            return None
        if row[2] is None or int(row[2]) != int(owner_dev_id):
            return None

        names = await display_names(db, [principal_key("agent", did),
                                         principal_key("developer", owner_dev_id)])
        agent_name = names.get(principal_key("agent", did), "This agent")
        owner_name = names.get(principal_key("developer", owner_dev_id), "the owner")

        speaker = Actor("agent", agent_did=did, display_name=agent_name)
        agent_row = await _my_row(db, conv.id, speaker)
        if agent_row is None:
            agent_row = ConversationParticipant(
                conversation_id=conv.id, ptype="agent", agent_did=did,
                role="member", state="active")
            db.add(agent_row)
            await db.flush()

        # §OURSTATE-5b — resolved LIVE, at the moment of speaking. If the owner
        # revoked the grant an hour ago, the stand-in says it cannot commit
        # anything; there is no cached ceiling to be wrong about.
        from ..services.chat_authority import authority_snapshot
        authority = await authority_snapshot(
            db, developer_id=owner_dev_id, agent_did=did,
            token_id=cfg.get("capability_token_id"))

        msg, dup = await insert_message(
            db, conv, agent_row, speaker, "text",
            away_disclosure(agent_name, owner_name, str(cfg.get("note") or ""), authority),
            None, client_ref=f"away-{conv.id}", rail_author=True)
        if dup:
            return None      # one reply per thread, ever
        out = serialize_message(msg)
        out["sender_name"] = agent_name
        return out
    except Exception as e:  # noqa: BLE001 — the stand-in never breaks the send
        logger.warning("[CHAT] away answer failed on %s: %s", conv.id, e)
        return None


async def away_digest(db: AsyncSession, actor: Actor, limit: int = 30) -> dict:
    """"While you were away": the threads your stand-in answered, each with what
    the stranger said afterwards — STAGED, never accepted. Bounds stated."""
    if actor.ptype != "developer":
        return {"threads": [], "note": "away digests belong to a developer account"}
    limit = max(1, min(int(limit or 30), LIST_MAX))
    rows = (await db.execute(sa_text("""
        SELECT c.id, c.last_seq, c.last_message_at, c.last_preview,
               m.seq AS away_seq, m.created_at AS away_at, p.last_read_seq
        FROM chat_messages m
        JOIN conversations c ON c.id = m.conversation_id
        JOIN conversation_participants p
          ON p.conversation_id = c.id AND p.ptype = 'developer' AND p.developer_id = :me
        WHERE m.client_ref = ('away-' || c.id)
        ORDER BY m.created_at DESC
        LIMIT :lim
    """), {"me": actor.developer_id, "lim": limit})).all()

    out = []
    for r in rows:
        out.append({
            "conversation_id": r[0],
            "last_seq": int(r[1] or 0),
            "last_message_at": r[2].isoformat() if r[2] else None,
            "last_preview": r[3],
            "answered_at": r[5].isoformat() if r[5] else None,
            "since_you_were_away": max(0, int(r[1] or 0) - int(r[4] or 0)),
            "unread": max(0, int(r[1] or 0) - int(r[6] or 0)),
        })
    return {"threads": out, "count": len(out),
            "note": f"threads your stand-in answered (newest {limit}); "
                    "nothing was accepted, paid or signed"}


# ---------------------------------------------------------------------------
# §OURSTATE-3 REACH — handles: an opt-in ADDRESS, not an identity (mig 0157)
#
# `@name` exists so a person can be reached without publishing a numeric id.
# It resolves to a developer this registry already knows; the profile it opens
# obeys the EXISTING `profile_visibility`, so claiming a handle publishes
# nothing that was private. Reserved words are refused BY NAME rather than
# silently mangled — a claim that half-works is worse than one that is denied.
# ---------------------------------------------------------------------------

HANDLE_RE = __import__("re").compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{2,31}$")
HANDLE_RESERVED = frozenset({
    "admin", "administrator", "root", "system", "protocol", "theprotocol",
    "registry", "support", "help", "api", "assistant", "ourstate", "ourchat", "chat",
    "operator", "treasury", "auditor", "security", "official", "staff",
    "me", "you", "all", "everyone", "here", "channel", "null", "undefined",
})


def validate_handle(raw: Any) -> Optional[str]:
    """Returns a refusal reason or None. Shape first, then the reserved set."""
    if not isinstance(raw, str):
        return "handle must be a string"
    h = raw.strip().lstrip("@")
    if not HANDLE_RE.match(h):
        return ("a handle is 3-32 characters, starts alphanumeric, and uses "
                "only letters, digits, '-' and '_'")
    if h.lower() in HANDLE_RESERVED:
        return f"'{h}' is reserved by the registry"
    return None


def normalize_handle(raw: str) -> str:
    return raw.strip().lstrip("@")


async def claim_handle(db: AsyncSession, developer_id: int, raw: str) -> dict:
    """Claim (or re-claim) a handle. One per account; a taken name refuses with
    that word, never a generic 409."""
    reason = validate_handle(raw)
    if reason:
        raise ChatError(422, reason)
    h = normalize_handle(raw)
    taken = (await db.execute(sa_text(
        "SELECT id FROM developers WHERE lower(handle) = lower(:h) AND id <> :me"
    ), {"h": h, "me": int(developer_id)})).first()
    if taken:
        raise ChatError(409, f"'{h}' is already taken")
    await db.execute(sa_text(
        "UPDATE developers SET handle = :h, handle_claimed_at = now() WHERE id = :me"
    ), {"h": h, "me": int(developer_id)})
    await db.commit()
    return {"handle": h, "claimed": True}


async def resolve_handle(db: AsyncSession, raw: str) -> Optional[int]:
    """`@name` → developer id, or None. Lowercased on both sides, always."""
    h = normalize_handle(str(raw or ""))
    if not h:
        return None
    row = (await db.execute(sa_text(
        "SELECT id FROM developers WHERE lower(handle) = lower(:h) "
        "AND deleted_at IS NULL AND is_suspended = false"
    ), {"h": h})).first()
    return int(row[0]) if row else None


async def public_profile(db: AsyncSession, handle: str) -> dict:
    """The public card behind a handle. Honors `profile_visibility` — a
    'private' profile resolves as REACHABLE but says nothing else about the
    person, because being addressable and being on display are two different
    consents."""
    h = normalize_handle(handle)
    row = (await db.execute(sa_text("""
        SELECT id, handle, display_name, name, bio, avatar_url, website_url,
               github_url, twitter_handle, company, profile_visibility,
               flare_tier, selected_encirclement_flare, flare_encirclement_variant,
               flare_encirclement_overlay, handle_claimed_at
        FROM developers
        WHERE lower(handle) = lower(:h) AND deleted_at IS NULL AND is_suspended = false
    """), {"h": h})).first()
    if row is None:
        raise ChatError(404, f"no account carries the handle '{h}'")
    public = str(row[10] or "public").lower() == "public"
    out = {
        "handle": row[1],
        "developer_id": int(row[0]),
        "reachable": True,
        "visibility": "public" if public else "private",
        "claimed_at": row[15].isoformat() if row[15] else None,
    }
    if public:
        out.update({
            "display_name": row[2] or row[3] or row[1],
            "bio": row[4], "avatar_url": row[5], "website_url": row[6],
            "github_url": row[7], "twitter_handle": row[8], "company": row[9],
            "flare": {"tier": row[11], "encirclement": row[12],
                      "variant": row[13], "overlay": row[14]} if row[11] else None,
        })
    else:
        # Named honestly rather than 404'd: the handle IS reachable, and
        # pretending otherwise would make "no such person" and "prefers not to
        # be listed" indistinguishable.
        out["note"] = "this account is reachable by handle but does not publish a profile"

    # §OURSTATE-5a — the terms travel with the card, on BOTH visibilities.
    # A stranger has to learn the price BEFORE they can pay it, and a private
    # profile that silently refuses a paid intro would be a toll booth with no
    # sign. What is published is only the ENFORCED shape (policy, amount,
    # currency, and which agent receives it) — never the person's balances,
    # never their other agents.
    from ..services import contact_policy as cp
    decl = await cp.declaration(db, int(row[0]))
    out["contact"] = {
        "policy": decl["effective"], "declared": decl["policy"],
        "price": decl["price"] if decl["effective"] == "priced" else None,
        "currency": decl["currency"] if decl["effective"] == "priced" else None,
        "purse_did": decl["purse_did"] if decl["effective"] == "priced" else None,
    }
    if public:
        out["genesis_card"] = cp.genesis_card(decl, out.get("display_name") or h)
    return out


async def insert_remote_message(db: AsyncSession, conv: Conversation,
                                part: ConversationParticipant,
                                sender_key: str, sender_display: str,
                                kind: str, body: Optional[str], card: Optional[dict],
                                client_ref: str, *,
                                before_commit: Optional[Callable[[ChatMessage], Awaitable[Any]]] = None,
                                system_row: bool = False,
                                ) -> Tuple[ChatMessage, bool]:
    """§OURSTATE-3b — insert a message a PEER relayed to us as the host.

    Separate from insert_message on purpose: the sender is a `remote_key`, not
    a principal this registry can authenticate, so it must never travel through
    the code path whose whole job is stamping the authenticated caller. Here
    the peer channel authenticated the REGISTRY and the participant row says
    that key belongs in this thread; those two facts are the authorization, and
    they are checked by the caller (routers/chat_federation.py).
    """
    client_ref = _validate_client_ref(client_ref)
    if kind == "system" and system_row:
        # §TWOAGENT G1 household seat: the HOST writes this row (a visible join), never a peer's relay
        card = None
    elif kind not in ("text", "card"):
        raise ChatError(422, "a relayed message is text or card")
    if kind in ("text", "system"):
        reason = validate_body(body)
        if reason:
            raise ChatError(422, reason)
        if not (body or "").strip():
            raise ChatError(422, "a text message needs a body")
        card = None
    else:
        # The closed vocabulary applies to peers too — rail_author=False,
        # because a remote CLIENT wrote this, not our own rail.
        # This second site validates a card WITHOUT a database read available;
        # `topup.offer` therefore stays refused here by construction, which is
        # the safe direction for a money door.
        reason = validate_card(card, rail_author=False)
        if reason:
            raise ChatError(422, reason)

    dup = (await db.execute(select(ChatMessage).where(
        ChatMessage.conversation_id == conv.id,
        ChatMessage.sender_ptype == "remote",
        ChatMessage.sender_id == sender_key,
        ChatMessage.client_ref == client_ref))).scalars().first()
    if dup is not None:
        return dup, True

    reply_accept = part.state == "pending"
    if reply_accept:
        part.state = "active"

    seq = (await db.execute(sa_text(
        "UPDATE conversations SET last_seq = last_seq + 1, last_message_at = now(), "
        "last_preview = :pv WHERE id = :cid RETURNING last_seq"),
        {"cid": conv.id, "pv": preview_for(kind, body, card)})).scalar_one()

    msg = ChatMessage(
        id=str(uuid.uuid4()), conversation_id=conv.id, seq=int(seq),
        sender_ptype="remote", sender_id=sender_key,
        kind=kind, body=body, card=card, client_ref=client_ref)
    db.add(msg)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        dup = (await db.execute(select(ChatMessage).where(
            ChatMessage.conversation_id == conv.id,
            ChatMessage.sender_ptype == "remote",
            ChatMessage.sender_id == sender_key,
            ChatMessage.client_ref == client_ref))).scalars().first()
        if dup is None:
            raise ChatError(500, "relayed insert raced and could not recover")
        return dup, True
    if before_commit is not None:
        await before_commit(msg)        # §TWOAGENT G1 step 4: the delivery rows commit WITH the message
    await db.commit()
    if reply_accept:
        await _announce_reply_accept(db, conv, part, principal_key("remote", sender_key), sender_display)
    return msg, False
