"""§FEFRAME W2 — who this registry is and who its federation peers are, in ONE answer for the console.

Before W2 the question "what is that other registry, and where does a person open it" had four answers in the backend
(routers/exchange.py and routers/registry_health.py each had a `_card_public_url`, one falling back to the federation
address minus its port and one refusing to; routers/federation_topology.py rebuilt a web origin from base_url's host
for icons; main.py's topology took base_url's host) and a fifth in the frontend: an A/B/C seed of the retired frames
with their currencies and ledger sockets hard-coded. On EU and ASIA the seed named nothing that exists.

The manifest answers once, from the peer rows federation already admitted and the cards it already verified:

  key            the registry's own name, lowercased (the peer row's name; never a letter)
  name           the name as its card states it
  display_name   the card's display name, else the name
  trust_domain   the card's SPIFFE trust domain
  role           "frame" (a sovereign mainframe with its own ledger) or "operator" (a cloud operator under a frame)
  parent         an operator's frame, by trust domain (an operator shares its frame's trust domain)
  public_url     the registry's public API origin
  console_url    where a person opens its console (from its OWN manifest; its public_url until that is read)
  currency       the settlement currency code on its card
  currency_name  the currency's name from its OWN manifest (None until read)
  theme          the card's visual theme (neural | sovereign)
  icon_url       the card's icon, made absolute on the registry's public origin
  ledger_ws      wss://<frame public host>/ws/events; an operator streams its parent's ledger
  tier           the card's identity.tier
  verified       the card signature verified (a peer); True for self

Trust rules (one place):
- A peer's public_url is taken from its card only when the card's signature verified, the URL is https on a DNS name,
  and its host is the host of the federation address the peer was admitted on (base_url): a card may not claim another
  registry's host. Otherwise the web origin of base_url (https, the host, no port) stands in, which is what the
  federation already dials.
- console_url, currency_name and ledger_ws are read from the peer's own public manifest (see `peer_manifest_fields`)
  and must be https/wss on a DNS name; a value that fails is dropped, never guessed.

Everything here is PURE (dicts in, dicts out) except `self_entry`, which reads this process's environment, so the
rules are unit-tested without a database or a network (tests/test_federation_view.py).
"""
from __future__ import annotations

import ipaddress
import os
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional
from urllib.parse import urlsplit

ROLE_FRAME = "frame"
ROLE_OPERATOR = "operator"

_LOOPBACK_NAMES = {"localhost", "localhost.localdomain"}
_DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def _dns_host(host: Optional[str]) -> Optional[str]:
    """A lowercase DNS name with at least one dot, not an IP address, not loopback; else None."""
    if not host:
        return None
    h = host.strip().lower().rstrip(".")
    if not h or h in _LOOPBACK_NAMES or "." not in h:
        return None
    try:
        ipaddress.ip_address(h.strip("[]"))
        return None
    except ValueError:
        pass
    if not all(_DNS_LABEL.match(label) for label in h.split(".")):
        return None
    return h


def web_origin(url: Optional[str], scheme: str = "https") -> Optional[str]:
    """`scheme://host` of a URL whose scheme is `scheme` and whose host is a DNS name; any port and path dropped.
    None for anything else (http, an IP, loopback, a bare name, garbage)."""
    if not url or not isinstance(url, str):
        return None
    try:
        p = urlsplit(url.strip())
    except ValueError:
        return None
    if p.scheme != scheme:
        return None
    host = _dns_host(p.hostname)
    return f"{scheme}://{host}" if host else None


def host_of(url: Optional[str]) -> Optional[str]:
    try:
        return _dns_host(urlsplit(str(url or "").strip()).hostname)
    except ValueError:
        return None


def absolute_on(origin: Optional[str], path_or_url: Optional[str]) -> Optional[str]:
    """A card's asset reference made absolute: an https URL on a DNS name stays (normalised to its origin + path),
    a root-relative path is joined to `origin`, anything else is None."""
    if not path_or_url or not isinstance(path_or_url, str):
        return None
    v = path_or_url.strip()
    if v.startswith("https://"):
        o = web_origin(v)
        if not o:
            return None
        p = urlsplit(v)
        return o + (p.path or "/") + (f"?{p.query}" if p.query else "")
    if v.startswith("/") and not v.startswith("//") and origin:
        return origin.rstrip("/") + v
    return None


def role_of(tier: Optional[str], peer_type: Optional[str] = None) -> Optional[str]:
    """frame | operator from the card's identity.tier first (it is signed), then the peer row's type; None when neither
    says (a `discovered` row whose card names no tier is resolved by trust domain in `resolve_parents`)."""
    t = (tier or "").strip().lower()
    if t in ("cloud-operator", "cloud_operator", "operator"):
        return ROLE_OPERATOR
    if "mainframe" in t or t in ("frame", "sovereign", "sandbox"):
        return ROLE_FRAME
    pt = (peer_type or "").strip().lower()
    if pt == "frame":
        return ROLE_FRAME
    if pt in ("cloud_operator", "cloud-operator"):
        return ROLE_OPERATOR
    return None


def key_of(name: Optional[str]) -> str:
    """The manifest key for a registry name: lowercase, every run of other characters one '-' ('Sandbox Beta' ->
    'sandbox-beta', 'EU' -> 'eu'). Peer rows spell one registry several ways (measured 2026-10-01: 'EU' on amsterdam,
    'eu' on shenzhen, 'Sandbox Beta' on sbxalphaop); every side derives the key with this one rule."""
    return re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")


def _s(v: Any) -> Optional[str]:
    return v.strip() if isinstance(v, str) and v.strip() else None


def entry_from_card(card: Mapping[str, Any] | None, *, name: str, base_url: Optional[str] = None,
                    peer_type: Optional[str] = None, verified: Optional[bool] = None) -> Dict[str, Any]:
    """One peer's entry from its peer row and cached card, before its own manifest is merged (`merge_peer_manifest`)
    and before parents are resolved (`resolve_parents`)."""
    card = card if isinstance(card, Mapping) else {}
    ident = card.get("identity") if isinstance(card.get("identity"), Mapping) else {}
    visual = card.get("visual") if isinstance(card.get("visual"), Mapping) else {}
    fees = card.get("fees") if isinstance(card.get("fees"), Mapping) else {}
    fed_origin = web_origin(base_url)
    card_public = web_origin(_s(ident.get("public_url")))
    same_host = bool(card_public) and host_of(card_public) == host_of(base_url)
    public_url = card_public if (verified and same_host) else fed_origin
    tier = _s(ident.get("tier"))
    return {
        "key": key_of(name),
        "name": _s(ident.get("registry_name")) or name.strip(),
        # display_name, theme and icon are NOT covered by the card signature (services/registry_card_signer.py):
        # a name is shown from a verified card only (the chat_federation.registry_display_names rule)
        "display_name": ((_s(ident.get("display_name")) or _s(ident.get("registry_name"))) if verified else None)
                        or name.strip(),
        "trust_domain": (_s(ident.get("trust_domain")) or "").lower() or None,
        "role": role_of(tier, peer_type),
        "parent": None,
        "public_url": public_url,
        "console_url": public_url,
        "currency": (_s(fees.get("settlement_currency")) or "").upper() or None,
        "currency_name": None,
        "theme": _s(visual.get("theme")),
        "icon_url": absolute_on(public_url, _s(visual.get("icon_url"))),
        "ledger_ws": None,
        "tier": tier,
        "verified": bool(verified),
    }


def peer_manifest_fields(manifest: Mapping[str, Any] | None, *, expect_host: Optional[str]) -> Dict[str, Any]:
    """The three fields a peer's OWN manifest (its public /api/v1/public/registry-config) contributes, validated:
    console_url (https, DNS name), ledger_ws (wss, DNS name, path /ws/events...), currency_name (a short string).
    The manifest must describe the registry it was fetched from: its self.public_url host must be `expect_host`,
    or nothing is taken from it."""
    out: Dict[str, Any] = {}
    if not isinstance(manifest, Mapping):
        return out
    me = manifest.get("self") if isinstance(manifest.get("self"), Mapping) else None
    if not me:
        return out
    if expect_host and host_of(_s(me.get("public_url"))) != expect_host:
        return out
    console = web_origin(_s(me.get("console_url")))
    if console:
        out["console_url"] = console
    lw = _s(me.get("ledger_ws"))
    if lw:
        try:
            p = urlsplit(lw)
            if p.scheme == "wss" and _dns_host(p.hostname) and p.path.startswith("/ws/events"):
                out["ledger_ws"] = f"wss://{_dns_host(p.hostname)}{p.path}"
        except ValueError:
            pass
    cn = _s(me.get("currency_name"))
    if cn and len(cn) <= 80:
        out["currency_name"] = cn
    return out


def merge_peer_manifest(entry: Dict[str, Any], fields: Mapping[str, Any]) -> Dict[str, Any]:
    e = dict(entry)
    for k in ("console_url", "ledger_ws", "currency_name"):
        if fields.get(k):
            e[k] = fields[k]
    return e


def ledger_for_frame(public_url: Optional[str]) -> Optional[str]:
    """A frame's ledger stream: /ws/events on its PUBLIC host (measured 2026-09-30: eu., asia. and sandbox-a proxy
    their own store there, 101 each). Not the console host: EU's console is the apex, whose /ws/events still led to
    the retired Frame A store, and an alias host may serve another frame's console for a while."""
    h = host_of(public_url)
    return f"wss://{h}/ws/events" if h else None


def resolve_parents(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Give every operator its frame (by trust domain) and its frame's ledger; resolve a role the card did not state
    (a registry sharing a frame's trust domain without being that frame is an operator). `entries` includes self."""
    frames_by_td: Dict[str, Dict[str, Any]] = {}
    for e in entries:
        if e.get("role") == ROLE_FRAME and e.get("trust_domain"):
            frames_by_td.setdefault(e["trust_domain"], e)
    out = []
    for e in entries:
        e = dict(e)
        td = e.get("trust_domain")
        frame = frames_by_td.get(td) if td else None
        if e.get("role") is None:
            e["role"] = ROLE_OPERATOR if (frame and frame.get("key") != e.get("key")) else ROLE_FRAME
        if e["role"] == ROLE_OPERATOR:
            e["parent"] = frame.get("key") if frame and frame.get("key") != e.get("key") else None
            if not e.get("ledger_ws") and frame:
                e["ledger_ws"] = frame.get("ledger_ws") or ledger_for_frame(frame.get("public_url"))
        else:
            e["parent"] = None
            if not e.get("ledger_ws"):
                e["ledger_ws"] = ledger_for_frame(e.get("public_url"))
        out.append(e)
    return out


def dedupe_peers(entries: Iterable[Dict[str, Any]], self_key: str, self_host: Optional[str] = None) -> List[Dict[str, Any]]:
    """One entry per key, never self (a peer row naming this registry is a fan-out echo): a verified card wins, then the
    first seen. Self is matched by key AND by public host: a row may spell this registry another way (measured on the
    sandbox 2026-10-01: sbxalphaop listed itself as a peer because its row said `sbxalphaop` and its own name was its
    container label `cloud-op-sbxalphaop`)."""
    by_key: Dict[str, Dict[str, Any]] = {}
    for e in entries:
        k = e.get("key")
        if not k or k == self_key:
            continue
        if self_host and host_of(e.get("public_url")) == self_host:
            continue
        if k not in by_key or (e.get("verified") and not by_key[k].get("verified")):
            by_key[k] = e
    return sorted(by_key.values(), key=lambda e: (e.get("role") != ROLE_FRAME, e.get("key") or ""))


def self_entry(card: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    """This registry's own entry. The environment decides the addresses (the same helpers every mail link and secret
    response uses, core/public_url); the card, when the caller has it, supplies the display fields."""
    from agentvault_registry.core import public_url as _pu

    card = card if isinstance(card, Mapping) else {}
    ident = card.get("identity") if isinstance(card.get("identity"), Mapping) else {}
    visual = card.get("visual") if isinstance(card.get("visual"), Mapping) else {}
    # The name the SIGNED CARD carries (services/registry_card_builder._build_identity_block): the federation name, never
    # an operator's container label (REGISTRY_NAME `cloud-op-sbxalphaop` beside a card and peer rows that say
    # `sbxalphaop`), so a registry's own key equals the key every peer derives for it.
    name = ((os.getenv("REGISTRY_FEDERATION_NAME", "") or "").strip() or (os.getenv("REGISTRY_NAME", "") or "").strip()
            or _s(ident.get("registry_name")) or "registry")
    public = web_origin(_pu.public_base_url_static())
    console = web_origin(_pu.public_ui_origin()) or public
    tier = _s(ident.get("tier"))
    operator = (os.getenv("MINTING_AUTHORITY", "") or "").strip().lower() == "disabled"
    role = ROLE_OPERATOR if operator else (role_of(tier) or ROLE_FRAME)
    currency = (os.getenv("FRAME_CURRENCY", "") or "").strip().upper() or None
    return {
        "key": key_of(name),
        "name": name,
        "display_name": _s(ident.get("display_name")) or name,
        "trust_domain": ((os.getenv("SPIRE_TRUST_DOMAIN", "") or "").strip().lower() or (_s(ident.get("trust_domain")) or "").lower() or None),
        "role": role,
        "parent": None,
        "public_url": public,
        "console_url": console,
        "currency": currency,
        "currency_name": (os.getenv("SETTLEMENT_CURRENCY_NAME", "") or "").strip() or None,
        "theme": _s(visual.get("theme")),
        "icon_url": absolute_on(public, _s(visual.get("icon_url"))),
        "ledger_ws": ledger_for_frame(public) if role == ROLE_FRAME else None,
        "tier": tier,
        "verified": True,
    }


# ── IO: the manifest from the peer rows, their cards and the cached peer manifests ──────────────────────────────────
# Everything above is pure; below reads the database (the ACTIVE peer rows, this registry's own card subset) and Redis
# (what each peer's own manifest said, written by background_tasks/federation_manifest_sync.py). Cached per worker for
# FRAME_MANIFEST_CACHE_SEC (30 s): the manifest is read by every console load and changes when a peer is admitted.
import json as _json
import logging as _logging
import time as _time

_log = _logging.getLogger(__name__)
PEER_FIELDS_KEY = "registry:fedview:peer:{}"          # the validated fields a peer's own manifest supplied
PEER_FIELDS_TTL = 24 * 3600                            # a quiet peer keeps its last good answer for a day
_MANIFEST_TTL = float(os.getenv("FRAME_MANIFEST_CACHE_SEC", "30") or 30)
_manifest_cache: Dict[str, Any] = {"ts": 0.0, "data": None}


def _redis_json(raw: Any) -> Dict[str, Any]:
    try:
        v = _json.loads(raw) if raw else {}
        return v if isinstance(v, dict) else {}
    except (TypeError, ValueError):
        return {}


async def cached_peer_fields(redis, key: str) -> Dict[str, Any]:
    if redis is None:
        return {}
    try:
        return _redis_json(await redis.get(PEER_FIELDS_KEY.format(key)))
    except Exception:  # noqa: BLE001 - a Redis blip must not take the manifest down
        return {}


async def _own_card_subset(db) -> Dict[str, Any]:
    """The operator-editable card subset (visual, persona) from the singleton row; the builder's LOCKED identity fields
    are derived from the environment in `self_entry`. One row, no signing: cheap on the hot path."""
    try:
        from sqlalchemy import select
        from agentvault_registry.models import RegistryCard
        row = (await db.execute(select(RegistryCard).where(RegistryCard.id == 1))).scalar_one_or_none()
        return dict(row.card_json or {}) if row is not None else {}
    except Exception as e:  # noqa: BLE001
        _log.warning("[FrameManifest] own card subset unreadable (%s): the self block uses the environment only", e)
        return {}


def _self_display_card(subset: Mapping[str, Any]) -> Dict[str, Any]:
    """Shape the stored subset like a served card for `self_entry`: visual as stored, the display name exactly as the
    card builder sets it (the subset's top-level `display_name`, else the federation name). It used to fall back to the
    operator PERSONA's display name, so sbx-alpha called itself "TheProtocol Sandbox" while its card and its peers said
    "Sandbox Alpha"."""
    ident: Dict[str, Any] = {}
    if _s(subset.get("display_name")):
        ident["display_name"] = subset.get("display_name")
    return {"identity": ident, "visual": subset.get("visual") if isinstance(subset.get("visual"), Mapping) else {}}


async def active_peer_entries(db, redis=None) -> List[Dict[str, Any]]:
    """Every ACTIVE peer row as an entry, its own manifest's fields merged when a cycle has read them."""
    from sqlalchemy import select
    from agentvault_registry.models import PeerRegistry
    rows = (await db.execute(select(PeerRegistry).where(PeerRegistry.status == "ACTIVE"))).scalars().all()
    out = []
    for r in rows:
        card = r.cached_registry_card if isinstance(r.cached_registry_card, dict) else None
        e = entry_from_card(card, name=r.name, base_url=r.base_url, peer_type=r.peer_type,
                            verified=bool(getattr(r, "card_signature_verified", False)) and card is not None)
        if not e.get("trust_domain") and getattr(r, "trust_domain", None):
            e["trust_domain"] = str(r.trust_domain).strip().lower() or None
        e = merge_peer_manifest(e, await cached_peer_fields(redis, e["key"]))
        out.append(e)
    return out


def cached_manifest() -> Optional[Dict[str, Any]]:
    """The per-worker manifest when it is fresher than FRAME_MANIFEST_CACHE_SEC, else None (the caller opens a session
    only then)."""
    if _manifest_cache["data"] is not None and _time.monotonic() - _manifest_cache["ts"] < _MANIFEST_TTL:
        return _manifest_cache["data"]
    return None


async def manifest_now() -> Optional[Dict[str, Any]]:
    """The manifest for a caller with no session of its own: the per-worker cache, else one build on a fresh session.
    None (logged) when the database cannot be read: callers serve what they have without it."""
    m = cached_manifest()
    if m is not None:
        return m
    try:
        from agentvault_registry.background_tasks.leader import get_redis
        from agentvault_registry.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            return await build_manifest(db, await get_redis())
    except Exception as e:  # noqa: BLE001
        _log.warning("[FrameManifest] unavailable: %s", e)
        return None


async def build_manifest(db, redis=None, *, use_cache: bool = True) -> Dict[str, Any]:
    """{manifest_version, self, peers[], multi_frame}. `multi_frame` = the federation has at least two FRAMES (the old
    field meant "EVENT_STORE_B_URL is set", which drew EU's single peer as "Frame B")."""
    now = _time.monotonic()
    if use_cache and _manifest_cache["data"] is not None and now - _manifest_cache["ts"] < _MANIFEST_TTL:
        return _manifest_cache["data"]
    me = self_entry(_self_display_card(await _own_card_subset(db)))
    peers = dedupe_peers(await active_peer_entries(db, redis), me["key"], host_of(me.get("public_url")))
    resolved = resolve_parents([me] + peers)
    me, peers = resolved[0], resolved[1:]
    if me["role"] == ROLE_OPERATOR and me.get("parent"):
        parent = next((p for p in peers if p["key"] == me["parent"]), None)
        if parent is not None and not me.get("ledger_ws"):
            me["ledger_ws"] = parent.get("ledger_ws")
    frames = {e["key"] for e in [me] + peers if e.get("role") == ROLE_FRAME}
    data = {
        "manifest_version": 1,
        "self": me,
        "peers": peers,
        # more than one FRAME in this federation (an operator counts its parent and the other frames, never itself)
        "multi_frame": len(frames) >= 2,
    }
    _manifest_cache.update(ts=now, data=data)
    return data


def manifest_origins(manifest: Mapping[str, Any]) -> List[str]:
    """Every browser origin the manifest names (self and peers: console and public), for the CORS allowlist."""
    out: List[str] = []
    for e in [manifest.get("self") or {}] + list(manifest.get("peers") or []):
        for k in ("console_url", "public_url"):
            o = web_origin(e.get(k))
            if o and o not in out:
                out.append(o)
    return out
