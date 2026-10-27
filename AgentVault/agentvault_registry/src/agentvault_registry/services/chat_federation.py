"""§OURSTATE-3b — cross-registry threads: host + per-registry inbox relay.

THE SHAPE (strategy §10, D8 approved):

    creator's registry = HOST. It owns `seq`, and it is the only writer of it.
    every remote participant's HOME registry = RESIDENT. It keeps a MIRROR and
    serves its own people from it.

    send (resident) ──relay-send──▶ host ──assigns seq──▶ outbox ──deliver──▶ every resident
    read  (resident) ── from its own mirror. Always.

WHY THIS SHAPE AND NOT A SIMPLER ONE: a host outage must degrade to "cannot
send", never to "cannot read history". A design where residents read through
the host is one outage away from a person losing access to their own
correspondence, which is the property this whole program exists to avoid.

THE TWO IDEMPOTENCE HALVES, because at-least-once delivery is a promise you
keep on BOTH sides:
  * host: UNIQUE(conversation, seq, peer) on the outbox — a retry cannot
    enqueue the same delivery twice.
  * resident: UNIQUE(conversation, remote_seq) on messages — the same host
    message arriving twice lands once. The receive is a no-op, not an error,
    because a peer retrying is a peer doing the right thing.

WHAT DOES NOT FEDERATE, deliberately:
  * money. A federated thread carries the SAME closed card vocabulary, and
    every card is a door to a rail that authorizes at the registry that owns
    the money. `service-call` stays local by construction (it fires THIS
    registry's own /a2a-payment/buy with the caller's own JWT).
  * org rooms. A room's membership truth is one registry's org roster; a
    federated room would need a second registry to vouch for a roster it
    cannot read. dm only, v1.
  * authority. A remote participant row records who the HOST said is in the
    thread. It is not a foreign key and it grants nothing here.
"""
from __future__ import annotations

import datetime
import logging
import os
import uuid
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx
from sqlalchemy import select, text as sa_text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry.models import (
    ChatFederationOutbox,
    ChatMessage,
    Conversation,
    ConversationParticipant,
)
from agentvault_registry.services import chat_service as cs

logger = logging.getLogger(__name__)

# Delivery backoff: fast enough that a blip is invisible, slow enough that a
# dead peer costs nothing. Capped, and the queue is drained by ONE leader.
BACKOFF_SECONDS = (5, 30, 120, 600, 1800, 3600)
MAX_ATTEMPTS = 12          # ~about a day of trying, then it waits for a human
DELIVER_TIMEOUT_S = 15.0
OUTBOX_BATCH = 50


class FederationOff(Exception):
    """Raised when cross-registry chat is not enabled on this registry."""


def federation_enabled() -> bool:
    """Off by default. A registry that has not opted in must not accept a
    foreign thread — an operator moderates their own house, and that starts
    with choosing to have one."""
    return os.getenv("CHAT_FEDERATION_ENABLED", "false").strip().lower() in ("1", "true", "yes")


def self_base_url() -> str:
    """This registry's PUBLIC address — the one a peer can reach us on, in the form a peer keys us by.
    §PUBLICURL: never derive it by stripping a port off the mTLS endpoint.

    §TWOAGENT V0438: a cloud operator is provisioned without PUBLIC_BASE_URL and without BASE_URL (§V0160),
    so this answered "" there: every envelope an operator sent named no host and its parent refused it
    (422), and every remote key it minted read `x@`. The order is the explicit knob, then the ONE
    request-free reader of this node's public address (`core.public_url.public_base_url_static`: BASE_URL,
    then the PUBLIC_URL every operator carries), then REGISTRY_SELF_URL. A loopback is never an answer (a
    peer cannot reach it; REGISTRY_SELF_URL is usually one), and every answer is returned in `public_form`,
    because that is the only form `peer_base_urls` accepts: an operator's PUBLIC_URL can carry its external
    mTLS port. Returns "" only when this node's public address is genuinely unknown."""
    from ..core.public_url import public_base_url_static
    for raw in (os.getenv("PUBLIC_BASE_URL"), public_base_url_static(), os.getenv("REGISTRY_SELF_URL")):
        u = str(raw or "").strip()
        if not u or "localhost" in u or "127.0.0.1" in u:
            continue
        pub = public_form(u)
        if pub:
            return pub
    return ""


def parse_remote_key(raw: str) -> Optional[Tuple[str, str]]:
    """`handle@https://reg.example` → ('handle', 'https://reg.example').

    Split on the LAST '@' so a handle can never smuggle a second address in.
    """
    s = str(raw or "").strip().lstrip("@")
    if "@" not in s:
        return None
    handle, _, base = s.rpartition("@")
    handle = handle.strip().lstrip("@")
    base = base.strip().rstrip("/")
    if not handle or not base:
        return None
    # the scheme is case-insensitive too: `HTTPS://peer` used to gain a second prefix and parse as host `https:`
    if not base.lower().startswith(("http://", "https://")):
        base = "https://" + base
    p = urlparse(base)
    if not p.netloc:
        return None
    return handle, f"{p.scheme}://{p.netloc.lower()}"


def origin(url: str) -> str:
    """A registry address as a key carries it: scheme://host[:port], lower-cased (RFC 3986 makes both
    case-insensitive), no trailing slash."""
    u = str(url or "").strip().rstrip("/")
    p = urlparse(u) if u.lower().startswith(("http://", "https://")) else None
    if p is None or not p.netloc:
        return u.lower()
    return f"{p.scheme.lower()}://{p.netloc.lower()}{p.path}"


def remote_key(handle: str, base_url: str) -> str:
    """The ONE form of a remote principal's key: `id@origin`, lower-case. §TWOAGENT G1 step 4: every comparison of a
    key is exact (blocks, participant rows, pair keys, the relay record), so two spellings of one address were two
    principals: a block typed `x@https://Peer.example` matched nothing stored as `x@https://peer.example`. Handles are
    unique regardless of case (the lower(handle) index) and DIDs are minted lower-case, so this names nobody new."""
    return f"{str(handle).lstrip('@').lower()}@{origin(base_url)}"


def public_form(base: str) -> str:
    """`https://op-x.example:8443` → `https://op-x.example`.

    `peer_registries.base_url` is the FEDERATION endpoint — for several peers
    that carries `:8443`, which is mTLS-only and not where a chat delivery can
    land. The rest of this app derives the public form the same way
    (`main._topo_public_url`, `agent_locations._get_public_url`): scheme +
    hostname, port dropped. Using the SAME derivation matters more than
    inventing a third answer — three functions disagreeing about a peer's
    address is how §PUBLICURL's dead-host bug happened in the first place.
    """
    u = str(base or "").strip().rstrip("/")
    if not u:
        return ""
    # the scheme is case-insensitive (the G1 step 4 rule `origin` and `parse_remote_key` follow): `HTTPS://peer`
    # used to gain a second prefix, parse as host `https` and answer "" (a peer row so spelled was no peer)
    p = urlparse(u if u.lower().startswith(("http://", "https://")) else "https://" + u)
    if not p.hostname or "." not in p.hostname:
        return ""
    return f"{p.scheme}://{p.hostname}"


async def peer_base_urls(db: AsyncSession) -> Dict[str, str]:
    """Peers we may talk to, keyed by their PUBLIC base URL. A registry we do
    not hold an ACTIVE peer row for is not a peer, and cannot open threads in
    our database."""
    rows = (await db.execute(sa_text("""
        SELECT name, base_url FROM peer_registries
        WHERE status = 'ACTIVE' AND base_url IS NOT NULL
    """))).all()
    out: Dict[str, str] = {}
    for name, url in rows:
        pub = public_form(str(url or ""))
        if pub:
            out[pub] = str(name)
    return out


async def assert_peer_allowed(db: AsyncSession, base_url: str) -> str:
    """A base URL must resolve to an ACTIVE peer row, or we do not speak to it.
    Refuses BY NAME so an operator can see which address was rejected."""
    peers = await peer_base_urls(db)
    if base_url not in peers:
        raise cs.ChatError(
            403, f"'{base_url}' is not an active federation peer of this registry")
    return peers[base_url]


# ---------------------------------------------------------------------------
# HOST side — enqueue and deliver
# ---------------------------------------------------------------------------

async def local_wire_id(db: AsyncSession, ptype: str, pid: Any) -> str:
    """The id a LOCAL principal goes by on the wire: a developer by its handle, else `dev:<id>`; an agent by its DID.

    §TWOAGENT V0441: the participant list, the household join and the relayed send all said `handle or dev:<id>`, and a
    host-local developer's MESSAGE said the bare id. So a mirror held one EU developer as two principals,
    `dev:12@https://eu…` (the seat it lists, the address a block is made with) and `12@https://eu…` (every message it
    stored), and a block of the listed address matched none of that developer's messages. One function, asked by all four."""
    if ptype == "developer":
        row = (await db.execute(sa_text("SELECT handle FROM developers WHERE id = :d"), {"d": int(pid)})).first()
        return row[0] if row and row[0] else f"dev:{int(pid)}"
    return str(pid)


async def registry_display_names(db: AsyncSession, origins: List[str]) -> Dict[str, str]:
    """origin -> the name a person reads for that registry: the registry_name on its signed, cached registry card (the
    name that registry gives itself: chat_service._registry_display_name derives this registry's own name the way the
    card builder derives registry_name, so both sides of a thread spell a registry alike), else the card's display
    name, else the peer row's name. An origin with no peer row answers its host name (§TWOAGENT V0441, the hosting
    line: the row names are slugs such as `eu`; the card says `EU`)."""
    want = {origin(o) for o in origins if o}
    out: Dict[str, str] = {}
    if not want:
        return out
    rows = (await db.execute(sa_text("""
        SELECT name, base_url, cached_registry_card, card_signature_verified FROM peer_registries
        WHERE base_url IS NOT NULL ORDER BY (UPPER(COALESCE(status, '')) = 'ACTIVE') DESC, name
    """))).all()
    for name, base, card, verified in rows:
        o = origin(public_form(str(base or "")))
        if o not in want or o in out:
            continue
        ident = card.get("identity") if isinstance(card, dict) and isinstance(card.get("identity"), dict) else {}
        shown = (ident.get("registry_name") or ident.get("display_name")) if verified else None
        out[o] = str(shown or name or urlparse(o).hostname or o)
    for o in want:
        out.setdefault(o, urlparse(o).hostname or o)
    return out


def envelope_sender(msg: ChatMessage, sender_display: str, wire_id: Optional[str] = None) -> dict:
    """§TWOAGENT G1 (2026-09-23): a sender is stated with the registry that vouches for IT. A message this host stored
    from a RESIDENT (relay-send: `sender_ptype='remote'`, `sender_id='handle@https://their.registry'`) used to go out
    stamped with the HOST's registry around the full key, so its own home mirrored it back as `handle@B@A`: a stranger
    wearing its own developer's name, and for an agent that answers automatically, a message loop.
    §TWOAGENT V0441: a LOCAL sender goes by `wire_id` (local_wire_id, the id its seat is listed under) when the caller
    has it; without it, the stored id as before."""
    if msg.sender_ptype == "remote":
        parsed = parse_remote_key(msg.sender_id or "")
        if parsed:
            return {"ptype": "remote", "id": parsed[0], "display_name": sender_display, "registry": parsed[1]}
    return {"ptype": msg.sender_ptype, "id": wire_id or msg.sender_id, "display_name": sender_display,
            # A sender is always stated with the registry that vouches for it; a bare id from another house means
            # nothing.
            "registry": self_base_url()}


def message_envelope(conv: Conversation, msg: ChatMessage, sender_display: str,
                     participants: List[dict], sender_wire_id: Optional[str] = None) -> dict:
    """The wire format. Deliberately flat and self-describing: a resident must
    be able to mirror a thread it has never seen from a single delivery."""
    return {
        "v": 1,
        "host_registry": self_base_url(),
        "conversation": {
            "id": conv.id,
            "kind": conv.kind,
            "title": conv.title,
            "participants": participants,
        },
        "message": {
            "id": msg.id,
            "seq": int(msg.seq),
            "kind": msg.kind,
            "body": msg.body,
            "card": msg.card,
            "client_ref": msg.client_ref,
            "sender": envelope_sender(msg, sender_display, sender_wire_id),
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
        },
    }


async def participant_wire(db: AsyncSession, conv: Conversation) -> List[dict]:
    """Participants as the wire states them: local ones become
    `handle@thisregistry` when they have a handle, remote ones pass through."""
    rows = (await db.execute(select(ConversationParticipant).where(
        ConversationParticipant.conversation_id == conv.id))).scalars().all()
    base = self_base_url()
    out: List[dict] = []
    for p in rows:
        if p.ptype == "remote":
            out.append({"ptype": "remote", "key": p.remote_key, "state": p.state})
            continue
        if p.ptype == "developer":
            key = remote_key(await local_wire_id(db, "developer", p.developer_id), base)
        else:
            key = remote_key(p.agent_did, base)
        out.append({"ptype": "remote", "key": key, "state": p.state})
    return out


async def enqueue_delivery(db: AsyncSession, conv: Conversation, msg: ChatMessage,
                           sender_display: str) -> int:
    """Queue one message for every remote participant's home registry.

    Returns the number of rows enqueued. Commits nothing — the caller owns the
    transaction, because a delivery that exists without its message would be a
    promise about something that never happened.
    """
    if conv.host_registry:
        return 0        # we are a MIRROR; the host does the delivering
    parts = (await db.execute(select(ConversationParticipant).where(
        ConversationParticipant.conversation_id == conv.id,
        ConversationParticipant.ptype == "remote"))).scalars().all()
    if not parts:
        return 0
    targets = set()
    for p in parts:
        parsed = parse_remote_key(p.remote_key or "")
        if parsed:
            targets.add(parsed[1])
    if not targets:
        return 0
    wire = await participant_wire(db, conv)
    sender_wire_id = (await local_wire_id(db, msg.sender_ptype, msg.sender_id)
                      if msg.sender_ptype in ("developer", "agent") else None)
    payload = message_envelope(conv, msg, sender_display, wire, sender_wire_id)
    n = 0
    for base in sorted(targets):
        db.add(ChatFederationOutbox(
            id=str(uuid.uuid4()), conversation_id=conv.id, seq=int(msg.seq),
            peer_base_url=base, payload=payload))
        n += 1
    return n


async def federation_target(db: AsyncSession, base: str) -> Tuple[str, Dict[str, Any], Dict[str, str]]:
    """(dial URL, client kwargs, headers) for a peer, the way the Guild, the cross-registry delegation and the contract
    relay reach one: the ACTIVE-peer allowlist maps the public base to its mTLS federation endpoint, and the client
    presents this registry's SVID.

    §TWOAGENT G1 (2026-09-23): chat dialled the peer's PUBLIC 443 form with a licence or the internal secret. The
    console vhosts clear the licence header and the internal secret is refused from outside, so that leg had no
    credential that could land, and nothing had ever completed the round trip. Raises cs.ChatError(403) for a base
    that is not an active peer."""
    from fastapi import HTTPException
    from agentvault_registry.routers.guild import _fed_client_config, _resolve_peer_url
    try:
        target = await _resolve_peer_url(db, base)
    except HTTPException:
        raise cs.ChatError(403, f"'{base}' is not an active federation peer of this registry")
    cfg, headers = _fed_client_config(target)
    cfg["timeout"] = DELIVER_TIMEOUT_S
    # mTLS is the credential; this registry's internal secret means nothing to a peer frame.
    headers = {k: v for k, v in headers.items() if k.lower() != "x-federation-secret"}
    lic = os.environ.get("FEDERATION_LICENSE_KEY", "")
    if lic:
        headers["X-Federation-License"] = lic
    return target, cfg, headers


async def deliver_one(row: ChatFederationOutbox, db: AsyncSession) -> Tuple[bool, str]:
    """POST one envelope to a peer. Returns (delivered, detail).

    A 2xx and a 409 both count as DELIVERED: 409 is the receiver saying "I
    already have this", which is the idempotent path doing its job, not a
    failure to be retried forever.
    """
    try:
        # Only through the allowlist and this registry's SVID. The old public-form dial (a licence the console vhosts
        # clear, or the internal secret refused from outside) had no credential that could land; it is gone.
        target, kwargs, headers = await federation_target(db, row.peer_base_url)
    except cs.ChatError as e:
        return False, e.detail
    url = f"{target.rstrip('/')}/api/v1/federation/chat/deliver"
    try:
        async with httpx.AsyncClient(**kwargs) as c:
            r = await c.post(url, headers=headers, json=row.payload)
        if r.status_code < 300 or r.status_code == 409:
            return True, f"HTTP {r.status_code}"
        return False, f"HTTP {r.status_code}: {r.text[:200]}"
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {str(e)[:200]}"


async def drain_outbox(db: AsyncSession, limit: int = OUTBOX_BATCH) -> dict:
    """One pass of the host's outbox. Bounded, and it REPORTS what it did —
    a delivery worker whose only signal is silence is indistinguishable from
    one that never ran (the §BRIDGE R7-B lesson)."""
    rows = (await db.execute(select(ChatFederationOutbox).where(
        ChatFederationOutbox.delivered_at.is_(None),
        ChatFederationOutbox.next_attempt_at <= sa_text("now()"),
        ChatFederationOutbox.attempts < MAX_ATTEMPTS,
    ).order_by(ChatFederationOutbox.next_attempt_at).limit(limit))).scalars().all()

    delivered = failed = 0
    for row in rows:
        okd, detail = await deliver_one(row, db)
        row.attempts = int(row.attempts or 0) + 1
        if okd:
            row.delivered_at = datetime.datetime.now(datetime.timezone.utc)
            row.last_error = None
            delivered += 1
        else:
            idx = min(row.attempts - 1, len(BACKOFF_SECONDS) - 1)
            row.next_attempt_at = (datetime.datetime.now(datetime.timezone.utc)
                                   + datetime.timedelta(seconds=BACKOFF_SECONDS[idx]))
            row.last_error = detail
            failed += 1
    await db.commit()
    return {"considered": len(rows), "delivered": delivered, "failed": failed,
            "batch_limit": limit}


RELAY_RECORD_TTL_S = 7 * 24 * 3600


def _relay_record_key(host: str, remote_ref: str, client_ref: str) -> str:
    import hashlib
    h = hashlib.sha256(f"{str(host).rstrip('/')}|{remote_ref}|{client_ref}".encode()).hexdigest()[:40]
    return f"chatfed:relayed:{h}"


async def _record_relay(host: str, remote_ref: str, client_ref: str, sender_key: str) -> None:
    """Remember that THIS registry relayed (host, thread, client_ref) for `sender_key`, before the POST: a delivery
    that comes back claiming to be ours is believed only if we sent it (Session A's review of G1 step 1)."""
    try:
        from agentvault_registry.background_tasks.leader import get_redis
        r = await get_redis()
        if r is not None:
            await r.set(_relay_record_key(host, remote_ref, client_ref), sender_key, ex=RELAY_RECORD_TTL_S)
    except Exception as e:  # noqa: BLE001 — without the record the echo reads as remote, never as forged-local
        logger.warning("[CHATFED] relay record not written: %s", type(e).__name__)


async def _we_relayed(host: str, remote_ref: str, client_ref: str, sender_key: str) -> bool:
    try:
        from agentvault_registry.background_tasks.leader import get_redis
        r = await get_redis()
        if r is None:
            return False
        got = await r.get(_relay_record_key(host, remote_ref, client_ref))
        if isinstance(got, bytes):
            got = got.decode()
        return bool(got) and got == sender_key
    except Exception:  # noqa: BLE001
        return False


async def relay_to_host(db: AsyncSession, conv: Conversation, sender_key: str, sender_display: str, kind: str,
                        body: Optional[str], card: Optional[dict], client_ref: str) -> dict:
    """§TWOAGENT G1 (2026-09-23), RESIDENT side: hand a message one of OUR principals wrote in a mirrored thread to the
    thread's HOST (`POST /api/v1/federation/chat/relay-send`), which is the only writer of the seq and delivers the
    canonical copy back to every participant's home, ours included. The route existed; nothing called it, so a
    resident's reply stayed in its own mirror and the other side never saw it. Idempotent on client_ref at the host.
    Raises cs.ChatError(502) with a sentence when the host cannot take it: nothing is sent, and nothing is stored here."""
    if not conv.host_registry or not conv.remote_ref:
        raise cs.ChatError(409, "this thread is not a mirror of another registry's thread")
    target, kwargs, headers = await federation_target(db, conv.host_registry)
    payload = {"conversation_ref": conv.remote_ref, "sender_key": sender_key, "sender_display": sender_display,
               "kind": kind, "body": body, "card": card, "client_ref": client_ref}
    await _record_relay(conv.host_registry, conv.remote_ref, client_ref, sender_key)
    try:
        async with httpx.AsyncClient(**kwargs) as c:
            r = await c.post(f"{target.rstrip('/')}/api/v1/federation/chat/relay-send", headers=headers, json=payload)
    except Exception as e:  # noqa: BLE001
        logger.warning("[CHATFED] relay to %s failed: %s", conv.host_registry, type(e).__name__)
        raise cs.ChatError(502, "the thread's host registry could not be reached; your message was NOT sent")
    if r.status_code in (200, 201):
        try:
            return r.json()
        except ValueError:
            return {}
    detail = ""
    try:
        detail = str((r.json() or {}).get("detail") or "")[:240]
    except ValueError:
        pass
    raise cs.ChatError(502 if r.status_code >= 500 else r.status_code,
                       f"the thread's host registry refused the message ({r.status_code}: {detail}); it was NOT sent")


# ---------------------------------------------------------------------------
# RESIDENT side — idempotent receive
# ---------------------------------------------------------------------------

# §TWOAGENT G1 step 2 (2026-09-23): the caps agents need. An agent that answers automatically turns a relayed reply
# into the other agent's next prompt, forever, so every federated leg is capped per thread and per peer, and an
# AGENT's relayed messages have a tighter per-thread cap than a person's. Counted in Redis (the chat gate's store);
# fail-open like every chat gate, because the hard bound on money never runs through chat.
FED_RL = {
    "relay_thread": (30, 60), "relay_peer": (300, 60), "relay_agent_thread": (12, 60),
    "deliver_thread": (60, 60), "deliver_peer": (600, 60),
    "create_actor": (20, 3600),
}


async def fed_rate_ok(kind: str, *parts: str) -> bool:
    limit, window = FED_RL[kind]
    return await cs._rate_gate(f"fed:{kind}:" + ":".join(str(p) for p in parts), limit, window)


async def home_key_for_mirror(db: AsyncSession, agent_did: str) -> Optional[str]:
    """§TWOAGENT G1 step 2: `did@https://its.home` for an agent this registry holds only as a MIRRORED card whose home
    is an ACTIVE peer; None for a native agent, a non-DID, or a card whose home cannot be placed."""
    did = str(agent_did or "")
    if not did.lower().startswith("did:"):
        return None
    if (await db.execute(sa_text("SELECT 1 FROM agents WHERE did = :d"), {"d": did})).first():
        return None
    row = (await db.execute(sa_text(
        "SELECT card_data FROM agent_cards WHERE agent_did = :d AND is_active ORDER BY updated_at DESC LIMIT 1"),
        {"d": did})).first()
    card = row[0] if row and isinstance(row[0], dict) else {}
    meta = card.get("federation_metadata") if isinstance(card.get("federation_metadata"), dict) else {}
    from agentvault_registry.services.contract_xframe import resolve_peer_name
    name = None
    for cand in (meta.get("origin_registry_name"), meta.get("source_registry")):
        if cand:
            name = await resolve_peer_name(db, str(cand))
            if name:
                break
    if not name:
        return None
    base = (await db.execute(sa_text(
        "SELECT base_url FROM peer_registries WHERE name = :n AND UPPER(COALESCE(status, '')) = 'ACTIVE' LIMIT 1"),
        {"n": name})).scalar()
    pub = public_form(str(base or ""))
    return remote_key(did, pub) if pub else None


async def announce_state_to_host(host_registry: str, remote_ref: str, participant_key: str, state: str,
                                 **join: Optional[str]) -> bool:
    """RESIDENT -> HOST: our participant accepted (or left) the thread. Only an ACCEPT or a LEAVE travels; a decline
    stays here on purpose (consent: a refusal the knocker cannot see). Best-effort, and a BACKGROUND task, so it opens
    its own session: the request's session is gone by the time this runs."""
    try:
        from agentvault_registry.database import get_db_context
        async with get_db_context() as db:
            target, kwargs, headers = await federation_target(db, host_registry)
        async with httpx.AsyncClient(**kwargs) as c:
            body = {"conversation_ref": remote_ref, "participant_key": participant_key, "state": state}
            # §TWOAGENT G1 household seat: a join names the agent it goes through, the owner's display and its row's ref
            body.update({k: v for k, v in join.items() if k in ("household_of", "participant_display", "client_ref") and v})
            r = await c.post(f"{target.rstrip('/')}/api/v1/federation/chat/state", headers=headers, json=body)
        ok = r.status_code in (200, 201)
        if not ok:
            logger.warning("[CHATFED] state %s for %s at %s answered %s", state, remote_ref, host_registry,
                           r.status_code)
        return ok
    except Exception as e:  # noqa: BLE001
        logger.warning("[CHATFED] state %s for %s not announced: %s", state, remote_ref, type(e).__name__)
        return False


async def mirror_thread_with(db: AsyncSession, actor: "cs.Actor",
                             key: str) -> Optional[Tuple[Conversation, ConversationParticipant]]:
    """The dm between this actor and `key` that the OTHER registry hosts, with the actor's row, or None.

    §TWOAGENT G1 step 4: a mirror carries no pair key (its uniqueness is (host, remote_ref)), so the pair-key lookup of
    a federated create cannot see it. Opening a dm to someone who already wrote to you from their registry must answer
    THAT thread, as a local create answers the pair's existing thread, not start a second one (and, to an agent, a
    second knock)."""
    if actor.ptype not in ("developer", "agent"):
        return None
    me_id = str(actor.developer_id) if actor.ptype == "developer" else str(actor.agent_did or "")
    row = (await db.execute(sa_text("""
        SELECT c.id FROM conversations c
        JOIN conversation_participants p ON p.conversation_id = c.id AND p.ptype = 'remote' AND p.remote_key = :k
        JOIN conversation_participants me ON me.conversation_id = c.id AND me.ptype = :mt AND (
             (me.ptype = 'developer' AND me.developer_id::text = :mi)
          OR (me.ptype = 'agent' AND lower(me.agent_did) = lower(:mi)))
        WHERE c.host_registry IS NOT NULL AND c.kind = 'dm'
        ORDER BY c.created_at ASC
        LIMIT 1
    """), {"k": key, "mt": actor.ptype, "mi": me_id})).first()
    if row is None:
        return None
    conv = (await db.execute(select(Conversation).where(Conversation.id == row[0]))).scalars().first()
    mine = (await db.execute(select(ConversationParticipant).where(
        ConversationParticipant.conversation_id == row[0],
        ConversationParticipant.ptype == actor.ptype,
        (ConversationParticipant.developer_id == actor.developer_id) if actor.ptype == "developer"
        else (ConversationParticipant.agent_did == actor.agent_did)))).scalars().first()
    if conv is None or mine is None:
        return None
    return conv, mine


async def announce_household_join(db: AsyncSession, conv: Conversation, actor: "cs.Actor", household_of: str) -> bool:
    """HOME -> HOST (§TWOAGENT G1 household seat, V0436): ask the thread's host to seat this OWNER, visibly, BEFORE the
    home seats it. Synchronous: the caller seats nobody unless the host recorded the join. The join row's client_ref is
    chosen here and recorded like a relay, so the host's notice comes home as the owner's own row, not a stranger's."""
    pkey = remote_key(await local_wire_id(db, "developer", actor.developer_id), self_base_url())
    ref = f"hjoin-{uuid.uuid4().hex[:24]}"
    await _record_relay(conv.host_registry, conv.remote_ref, ref, pkey)
    return await announce_state_to_host(conv.host_registry, conv.remote_ref, pkey, "join", household_of=household_of,
                                        participant_display=actor.display_name, client_ref=ref)


async def post_household_join(db: AsyncSession, conv: Conversation, row: ConversationParticipant, joiner_pkey: str,
                              display: str, agent_pkey: str, *, local_actor: Optional["cs.Actor"] = None,
                              client_ref: Optional[str] = None) -> ChatMessage:
    """The visible join (§TWOAGENT G1 household seat), written by the HOST: one system row naming the owner and the
    agent it joined through, committed WITH its delivery rows for every home and fanned out to the host's own residents,
    skipping any who block the joiner (a block of the owner's address still applies)."""
    names = await cs.display_names(db, [agent_pkey])
    body = f"{display} joined as the owner of {names.get(agent_pkey) or agent_pkey}."
    ref = client_ref or f"hjoin-{uuid.uuid4().hex[:24]}"

    async def _queue(m):
        try:
            await enqueue_delivery(db, conv, m, display)
        except Exception as e:  # noqa: BLE001 — refused by name, never swallowed
            await db.rollback()
            logger.warning("[CHATFED] household join not queued for %s: %s", conv.id, type(e).__name__)
            raise cs.ChatError(503, "the join could not be queued for the other registries; nothing changed") from e
    if local_actor is not None:
        msg, _dup = await cs.insert_message(db, conv, row, local_actor, "system", body, None, client_ref=ref,
                                            rail_author=True, before_commit=_queue)
    else:
        msg, _dup = await cs.insert_remote_message(db, conv, row, joiner_pkey.partition(":")[2], display, "system", body,
                                                   None, ref, before_commit=_queue, system_row=True)
    payload = cs.serialize_message(msg)
    payload["sender_name"] = display
    recipients = await cs.recipients_snapshot(db, conv, _PrincipalKey(joiner_pkey))
    cs.deliver(conv.id, conv.kind, payload, recipients, display)
    return msg


class _PrincipalKey:
    """A sender known only by its principal key (the recipients snapshot reads `.key` alone)."""

    def __init__(self, key: str):
        self.key = key


async def _seat_remote_owner(db: AsyncSession, conv: Conversation, parsed: Tuple[str, str], household_of: Optional[str],
                             display: Optional[str], client_ref: Optional[str], peer_identity: str) -> dict:
    """HOST side of a household join: the caller already proved it is the joiner's home; it must also be the home of the
    ACTIVE agent participant the owner joins through (it vouches for its own residents, nobody else's)."""
    if parsed[0].lower().startswith("did:"):
        raise cs.ChatError(422, "a household join seats an OWNER (a developer); an agent joins by being addressed")
    hh = parse_remote_key(household_of or "")
    if not hh or not hh[0].lower().startswith("did:"):
        raise cs.ChatError(422, "household_of must name the agent participant the owner joins through (did@https://its.home)")
    if not await caller_is(db, peer_identity, hh[1]):
        raise cs.ChatError(403, "the calling registry is not the home of the agent it vouches for")
    hh_key = remote_key(*hh)
    agent = (await db.execute(select(ConversationParticipant).where(
        ConversationParticipant.conversation_id == conv.id, ConversationParticipant.ptype == "remote",
        ConversationParticipant.remote_key == hh_key))).scalars().first()
    if agent is None or agent.state != "active":
        raise cs.ChatError(409, "the agent this owner joins through is not an active participant of the thread")
    joiner_key = remote_key(*parsed)
    row = (await db.execute(select(ConversationParticipant).where(
        ConversationParticipant.conversation_id == conv.id, ConversationParticipant.ptype == "remote",
        ConversationParticipant.remote_key == joiner_key))).scalars().first()
    if row is not None and row.state == "active":
        return {"state": "active", "changed": False, "joined": False}
    if row is None:
        row = ConversationParticipant(conversation_id=conv.id, ptype="remote", remote_key=joiner_key,
                                      role="member", state="active")
        db.add(row)
        await db.flush()
    else:
        row.state = "active"
    msg = await post_household_join(db, conv, row, cs.principal_key("remote", joiner_key), (display or joiner_key)[:200],
                                    cs.principal_key("remote", hh_key), client_ref=client_ref)
    return {"state": "active", "changed": True, "joined": True, "seq": int(msg.seq)}


async def apply_remote_state(db: AsyncSession, conversation_ref: str, participant_key: str, state: str,
                             peer_identity: str, *, household_of: Optional[str] = None,
                             participant_display: Optional[str] = None, client_ref: Optional[str] = None) -> dict:
    """HOST side of `announce_state_to_host`: the resident's own home says its participant accepted or left. The
    caller must BE that participant's home (resolved from its SVID). An accept of a pending knock tells the
    knocker's owner, the same `chat.request.accepted` a local accept sends."""
    if state not in ("active", "left", "join"):
        raise cs.ChatError(422, "only an accept (active), a leave (left) or an owner's join travels between registries")
    parsed = parse_remote_key(participant_key or "")
    if not parsed:
        raise cs.ChatError(422, "participant_key must be id@https://their.registry")
    if not await caller_is(db, peer_identity, parsed[1]):
        raise cs.ChatError(403, "the calling registry is not that participant's home registry")
    conv = (await db.execute(select(Conversation).where(Conversation.id == conversation_ref))).scalars().first()
    if conv is None or conv.host_registry:
        raise cs.ChatError(404, "this registry does not host that thread")
    if state == "join":
        return await _seat_remote_owner(db, conv, parsed, household_of, participant_display, client_ref, peer_identity)
    part = (await db.execute(select(ConversationParticipant).where(
        ConversationParticipant.conversation_id == conv.id,
        ConversationParticipant.ptype == "remote",
        ConversationParticipant.remote_key == participant_key))).scalars().first()
    if part is None:
        raise cs.ChatError(404, "that participant is not in the thread")
    before = part.state
    if before == state:
        return {"state": state, "changed": False}
    # §TWOAGENT G1 step 4: 'left' -> 'active' is a REJOIN, the resident reopening the thread from its own home (as a
    # local reopen re-engages). Only its home can say so (caller_is above), and a rejoin is no accept: no notice.
    if state == "active" and before not in ("pending", "left"):
        raise cs.ChatError(409, f"cannot accept a thread the participant is {before!r} in")
    part.state = state
    notice = cs.accepted_knock_notice(conv, before, state, part)
    await db.commit()
    if notice is not None:
        cs.spawn(cs.notify_request_accepted(notice, parsed[0]))
    return {"state": state, "changed": True}


async def _resolve_local_principal(db: AsyncSession, sender_id: str) -> Optional[Tuple[str, str]]:
    """A sender id this registry recognises as ITS OWN: ('agent', did) for a native agent, ('developer', id) for a
    handle or dev:N; else None."""
    sid = str(sender_id or "")
    if sid.lower().startswith("did:"):
        row = (await db.execute(sa_text("SELECT did FROM agents WHERE did = :d"), {"d": sid})).first()
        return ("agent", str(row[0])) if row else None
    dev = await _resolve_local_developer(db, sid)
    return ("developer", str(dev)) if dev is not None else None


async def _resolve_local_developer(db: AsyncSession, handle: str) -> Optional[int]:
    """`dev:N` or a handle -> this registry's developer id (not deleted), or None."""
    h = str(handle or "")
    if h.startswith("dev:") and h[4:].isdigit():
        row = (await db.execute(sa_text(
            "SELECT id FROM developers WHERE id = :d AND deleted_at IS NULL"), {"d": int(h[4:])})).first()
    else:
        row = (await db.execute(sa_text(
            "SELECT id FROM developers WHERE lower(handle) = lower(:h) AND deleted_at IS NULL"), {"h": h})).first()
    return int(row[0]) if row else None


def _local_keys_from(participants: List[dict], base: str) -> List[str]:
    """Which wire participants are OURS: `x@ourbase`."""
    out = []
    for p in participants or []:
        parsed = parse_remote_key(str(p.get("key") or ""))
        if parsed and parsed[1] == origin(base):
            out.append(parsed[0])
    return out


async def caller_is(db: AsyncSession, peer_identity: Optional[str], registry_url: Optional[str]) -> bool:
    """§TWOAGENT (2026-09-23): is the authenticated CALLER the registry an envelope speaks for? The transport proves
    which registry is calling; a registry named in the payload is a claim. Both resolve through the peer table."""
    from agentvault_registry.services.contract_xframe import resolve_peer_name
    caller = None
    for cand in (peer_identity, (peer_identity or "").rstrip("/")):
        caller = await resolve_peer_name(db, cand)
        if caller:
            break
    return caller is not None and bool(registry_url) and caller == await resolve_peer_name(db, registry_url)


async def receive_delivery(db: AsyncSession, envelope: dict, peer_identity: str) -> dict:
    """Mirror one delivered message. IDEMPOTENT: the same (conversation,
    remote_seq) lands once, and a repeat is reported as such rather than
    erroring — a peer retrying is a peer behaving correctly.

    The host is taken from the ENVELOPE but must match an ACTIVE peer row; a
    registry that is not our peer cannot create threads in our database.
    """
    if not federation_enabled():
        raise FederationOff("cross-registry chat is not enabled on this registry")
    if int(envelope.get("v") or 0) != 1:
        raise cs.ChatError(422, "unsupported federation envelope version")

    host = str(envelope.get("host_registry") or "").rstrip("/")
    if not host:
        raise cs.ChatError(422, "envelope is missing its host_registry")
    await assert_peer_allowed(db, host)
    # §TWOAGENT (2026-09-23): the module promised the peer identity is checked twice; only the envelope's claim was.
    # Any active peer could create a mirror in another peer's name and write into it.
    if not await caller_is(db, peer_identity, host):
        raise cs.ChatError(403, "the calling registry is not this thread's host")

    c_in = envelope.get("conversation") or {}
    m_in = envelope.get("message") or {}
    remote_ref = str(c_in.get("id") or "")
    remote_seq = int(m_in.get("seq") or 0)
    if not remote_ref or remote_seq <= 0:
        raise cs.ChatError(422, "envelope is missing conversation id or seq")
    if str(c_in.get("kind") or "dm") != "dm":
        # Rooms do not federate in v1 — and refusing by name beats mirroring a
        # membership model this registry cannot verify.
        raise cs.ChatError(422, "only dm threads federate in this version")

    base = self_base_url()
    local_handles = _local_keys_from(c_in.get("participants") or [], base)
    if not local_handles:
        raise cs.ChatError(422, "no participant of this delivery lives on this registry")

    # Resolve OUR residents. A handle we do not know is refused: a mirror for a
    # person who is not here would be a thread nobody could ever read.
    # §TWOAGENT G1 step 2: an AGENT resident is addressed by its DID and must be a live native agent here.
    resident_ids: List[int] = []
    resident_agents: List[str] = []
    for h in local_handles:
        if h.lower().startswith("did:"):
            arow = (await db.execute(sa_text("SELECT did, status FROM agents WHERE did = :d"), {"d": h})).first()
            if arow and str(arow[1] or "").lower() not in ("revoked", "suspended"):
                resident_agents.append(str(arow[0]))
            continue
        if h.startswith("dev:") and h[4:].isdigit():
            row = (await db.execute(sa_text(
                "SELECT id FROM developers WHERE id = :d AND deleted_at IS NULL"),
                {"d": int(h[4:])})).first()
        else:
            row = (await db.execute(sa_text(
                "SELECT id FROM developers WHERE lower(handle) = lower(:h) AND deleted_at IS NULL"),
                {"h": h})).first()
        if row:
            resident_ids.append(int(row[0]))
    if not resident_ids and not resident_agents:
        raise cs.ChatError(404, "no local account matches the addressed participants")
    if not await fed_rate_ok("deliver_thread", host, remote_ref) or not await fed_rate_ok("deliver_peer", host):
        raise cs.ChatError(429, "this peer is delivering faster than this registry accepts for one thread; retry later")
    sender_in = m_in.get("sender") or {}
    first_sender_key = remote_key(str(sender_in.get("id") or "unknown"),
                                  str(sender_in.get("registry") or host).rstrip("/"))

    # ── the mirror conversation ─────────────────────────────────────────────
    conv = (await db.execute(select(Conversation).where(
        Conversation.host_registry == host,
        Conversation.remote_ref == remote_ref))).scalars().first()
    created = False
    if conv is None:
        conv = Conversation(
            kind="dm", title=c_in.get("title"),
            # §TWOAGENT G1 step 2: the thread was started by the sender on the HOST, and that is who an accept here
            # answers (over the wire, never as a local notice).
            created_by_ptype="remote", created_by_id=first_sender_key,
            host_registry=host, remote_ref=remote_ref,
            # No dm_pair_key: the pair-key column enforces one-thread-per-pair
            # for LOCAL threads, and a mirror's uniqueness is (host, remote_ref).
            dm_pair_key=None)
        db.add(conv)
        try:
            await db.flush()
            created = True
        except IntegrityError:
            await db.rollback()
            conv = (await db.execute(select(Conversation).where(
                Conversation.host_registry == host,
                Conversation.remote_ref == remote_ref))).scalars().first()
            if conv is None:
                raise cs.ChatError(500, "mirror create raced and could not recover")

    # ── participants: ours as themselves, everyone else as remote ───────────
    have = {(p.ptype, p.developer_id, p.agent_did, p.remote_key) for p in (await db.execute(
        select(ConversationParticipant).where(
            ConversationParticipant.conversation_id == conv.id))).scalars().all()}
    for did in resident_ids:
        if ("developer", did, None, None) not in have:
            db.add(ConversationParticipant(
                conversation_id=conv.id, ptype="developer", developer_id=did,
                role="member", state="active"))
    pending_agents: List[str] = []
    for ad in resident_agents:
        if ("agent", None, ad, None) not in have:
            # A first contact from another registry lands in the agent's Requests lane, like a local stranger's
            # knock: nothing reaches it as a message until it (or its runtime) accepts.
            # §TWOAGENT G1 step 3: unless the agent BLOCKS that sender: then it is seated 'left' and told nothing,
            # the silence a local block gives.
            blocked = (await cs.blocks_between(db, cs.principal_key("agent", ad),
                                               cs.principal_key("remote", first_sender_key)))["a_blocks_b"]
            db.add(ConversationParticipant(
                conversation_id=conv.id, ptype="agent", agent_did=ad, role="member",
                state="left" if blocked else "pending"))
            if not blocked:
                pending_agents.append(ad)
    for p in (c_in.get("participants") or []):
        key = str(p.get("key") or "")
        parsed = parse_remote_key(key)
        if not parsed or parsed[1] == origin(base):
            continue
        if ("remote", None, None, key) not in have:
            db.add(ConversationParticipant(
                conversation_id=conv.id, ptype="remote", remote_key=key,
                role="member", state="active"))
    await db.flush()

    # ── the message, exactly once ───────────────────────────────────────────
    dup = (await db.execute(select(ChatMessage).where(
        ChatMessage.conversation_id == conv.id,
        ChatMessage.remote_seq == remote_seq))).scalars().first()
    if dup is not None:
        await db.commit()
        return {"conversation_id": conv.id, "created": created,
                "duplicate": True, "seq": int(dup.seq), "remote_seq": remote_seq}

    sender = m_in.get("sender") or {}
    s_id, s_reg = str(sender.get("id") or "unknown"), str(sender.get("registry") or host).rstrip("/")
    sender_key = remote_key(s_id, s_reg)
    sender_ptype, sender_local = "remote", sender_key
    if origin(s_reg) == origin(base) and await _we_relayed(host, remote_ref, str(m_in.get("client_ref") or ""), sender_key):
        # §TWOAGENT G1: our OWN developer's message, relayed through the host and delivered back with the canonical
        # seq. Believed ONLY because this registry recorded that relay (thread, client_ref, sender) before sending it:
        # a host claiming our registry for a message we never relayed (say, as dev:1) stays a remote sender.
        own = await _resolve_local_principal(db, s_id)
        if own is not None:
            sender_ptype, sender_local = own
    kind = str(m_in.get("kind") or "text")
    if kind not in ("text", "card", "system"):
        raise cs.ChatError(422, f"unsupported message kind {kind!r}")
    if kind == "card":
        # The vocabulary is closed ACROSS registries too. A peer cannot teach
        # this registry a new card type by sending one.
        # §TWOAGENT (2026-09-23): as a PEER, not a rail. A rail-only card (service.result, share.certificate,
        # org.work.receipt, engagement.*) names records on its home that this registry cannot verify, and a host
        # could forge one into a resident's thread; the relay-send leg already refuses them.
        reason = cs.validate_card(m_in.get("card"), rail_author=False)
        if reason:
            raise cs.ChatError(422, f"federated card refused: {reason}")

    seq = (await db.execute(sa_text(
        "UPDATE conversations SET last_seq = last_seq + 1, last_message_at = now(), "
        "last_preview = :pv WHERE id = :cid RETURNING last_seq"),
        {"cid": conv.id,
         "pv": cs.preview_for(kind, m_in.get("body"), m_in.get("card"))})).scalar_one()

    msg = ChatMessage(
        id=str(uuid.uuid4()), conversation_id=conv.id, seq=int(seq),
        sender_ptype=sender_ptype, sender_id=sender_local,
        kind=kind, body=m_in.get("body"), card=m_in.get("card"),
        client_ref=str(m_in.get("client_ref") or f"fed-{remote_seq}"),
        remote_seq=remote_seq, origin_registry=host)
    db.add(msg)
    try:
        await db.commit()
    except IntegrityError as e:
        # The idempotent receive, won by the index rather than by the SELECT —
        # but ONLY if the row is really there now. The first cut returned
        # `duplicate` for ANY IntegrityError, so a CHECK-constraint violation
        # (sender_ptype lacked 'remote') reported every delivery as accepted
        # while storing nothing. A failure must never wear success's clothes.
        await db.rollback()
        landed = (await db.execute(select(ChatMessage).where(
            ChatMessage.conversation_id == conv.id,
            ChatMessage.remote_seq == remote_seq))).scalars().first()
        if landed is None:
            logger.error("[CHATFED] receive could not store seq=%s: %s", remote_seq, e)
            raise cs.ChatError(500, f"delivery could not be stored: {type(e).__name__}")
        return {"conversation_id": conv.id, "created": created,
                "duplicate": True, "seq": int(landed.seq), "remote_seq": remote_seq}

    return {"conversation_id": conv.id, "created": created, "duplicate": False,
            "seq": int(seq), "remote_seq": remote_seq,
            "residents": resident_ids, "resident_agents": resident_agents, "pending_agents": pending_agents,
            "sender_ptype": sender_ptype, "sender_local": sender_local,
            "sender_display": sender.get("display_name") or sender_key,
            "message_id": msg.id, "peer": peer_identity}
