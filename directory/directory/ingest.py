"""The Directory's ingest: PULL the signed public feeds of a federation component, verify, index.

Who can emit into the Directory (his question): NOBODY pushes. The Directory dials the registries it admits and reads
their public feeds over TLS. Admission = the anchors its operator chose + the frames those anchors federate with + the
operators those frames license, each with a registry card whose EdDSA signature verifies against the registry's own JWKS.
An agent reaches the index only through its registry's own onboarding (bootstrap token, bond, IRONKEY) — the Directory
adds no second door. A registry whose parent lists it as anything but admitted, or whose card stops verifying, is kept
but marked (verified=0 / federation_status) and its cards stop refreshing. The target design pulls a cursor feed over
mTLS under an operator identity; this trial pulls the PUBLIC endpoints, which is what an external Directory will do too.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import urllib.parse

import httpx

from agentvault_registry.identifiers import agent_did_parts, agent_did_suffix_shape
from agentvault_registry.services.registry_card_signer import SIGNED_CANONICAL_PATHS, extract_paths
from agentvault_registry.services.registry_card_signer_impl import verify_with_jwk
from agentvault_registry.services.reputation_bond import extension_from_card as bond_ext, is_bonded_status, money_str
from agentvault_registry.services.enforcement_propagation import extension_from_card as enf_ext, is_enforced_status

from .store import Store, now

log = logging.getLogger("directory.ingest")

ANCHORS = [a.strip().rstrip("/") for a in os.environ.get("DIRECTORY_ANCHORS", "").split(",") if a.strip()]
SYNC_SECONDS = int(os.environ.get("DIRECTORY_SYNC_SECONDS", "60"))
MAX_HOPS = int(os.environ.get("DIRECTORY_MAX_HOPS", "1"))
CARD_LIMIT = int(os.environ.get("DIRECTORY_CARD_LIMIT", "5000"))
FRAME_TIERS = ("sovereign-mainframe", "regional-mainframe", "frame", "sandbox")

# §DIRFEED — three knobs that decide how much of a registry a cycle re-reads.
#
# EXTRACT_VERSION is what this code TAKES OUT of a card read. Bump it whenever that changes (a new field, a
# different derivation): the next cycle re-reads every card in full instead of trusting the stored epoch. The
# trial earned this the hard way — the registry image gained `agent_did` on the read, no card's `updated_at`
# moved, and the index stayed blind until the database was deleted by hand.
# 3 (§TWOAGENT #10, 2026-09-23): the registries state a native card's bond, enforcement and listing on the single-card
# read from V0437 on (they served stored card_data before, so every native card read as unbonded), and the enforcement
# flag is now read from the extension's `status` (the block has never carried an `is_enforced` field, so it read false).
EXTRACT_VERSION = 3
# A cursor pass can never see something GO AWAY: a deleted or deactivated card simply stops appearing in a feed
# nobody re-reads. Every FULL_EVERY cycles the Directory reads a registry whole and marks what it no longer
# publishes as unreachable (never deletes).
FULL_EVERY = int(os.environ.get("DIRECTORY_FULL_EVERY", "30"))
# The manual re-read switch (an operator's "forget what you think you know"), without deleting the index.
FORCE_FULL = os.environ.get("DIRECTORY_FORCE_FULL", "").strip().lower() in ("1", "true", "yes", "on")

# §DISCPANEL (his ask 2026-09-06): "hop distance configurable for the discovery for each registry … because
# registries will have different hardware and might want to store more discovered agents locally when they have
# enough resources for it." DIRECTORY_MAX_HOPS is the default budget; DIRECTORY_HOPS_BY_REGISTRY overrides it
# PER SOURCE, keyed by the registry's card name or by its host — a node with room indexes further out than one
# without, and neither has to agree with the other. Example:
#   DIRECTORY_HOPS_BY_REGISTRY={"EU": 3, "amsterdam": 0, "asia.theprotocol.cloud": 2}
# A budget of 0 means "index this registry's own cards, follow nothing further from it".
def _hops_by_registry() -> Dict[str, int]:
    raw = (os.environ.get("DIRECTORY_HOPS_BY_REGISTRY", "") or "").strip()
    if not raw:
        return {}
    try:
        v = json.loads(raw)
        return {str(k).strip().lower(): int(n) for k, n in v.items()} if isinstance(v, dict) else {}
    except Exception as e:  # noqa: BLE001 — a malformed map must not silently become "no overrides"
        log.warning("DIRECTORY_HOPS_BY_REGISTRY is not a JSON object of name->int (%s); using the default for every source", e)
        return {}


HOPS_BY_REGISTRY = _hops_by_registry()


def hop_budget(name: Optional[str], base: Optional[str]) -> int:
    """The depth this Directory walks FROM that source: its own override, else the global default."""
    host = (base or "").split("://")[-1].split("/")[0].split(":")[0].lower()
    for key in ((name or "").strip().lower(), host):
        if key and key in HOPS_BY_REGISTRY:
            return max(0, HOPS_BY_REGISTRY[key])
    return MAX_HOPS



# ── THE CRAWL LEG'S IDENTITY (§MTLSGAP 2026-09-08) ──────────────────────────────────────────
# His question: *"i need to know if mtls is setup to directory otherwise we need to set this up
# too. everything is mtls enforced."* It was not, in either direction. The Directory held no SVID
# at all — no `/certs`, no `/spire` mount — so it could not present a client certificate even in
# principle, and it crawled every frame anonymously.
#
# It now carries `spiffe://<its frame>/service/directory` and OFFERS it on every crawl. Where the
# far side asks for a client cert it gets one and the hop is mutual; where it does not (a public
# console vhost, which is how a REMOTE frame must be crawled — a federated index cannot require
# every frame it indexes to be on its identity network) the crawl works exactly as before. That
# asymmetry is deliberate: turning on `ssl_verify_client optional_no_ca` at a frame's edge makes
# this leg mutual with no further change here.
#
# ⚠ VERIFY IS CHOSEN BY THE TARGET, NOT BY US. Port 443 (or a default) means a public host with a
# webPKI certificate, so the system CAs are correct and the SPIRE bundle would refuse it; any
# other port is a SPIRE-served endpoint on the fabric, where the bundle is correct and the system
# CAs would refuse it. This is the same rule `svid_client.get_client_cert_config()` applies, and
# getting it backwards is the §FABRICVERIFY class — a verify chooser that looks right and fails
# one whole population.
#
# ⚠ AND UNKNOWN IS NOT EMPTY: with no cert files the Directory says so ONCE at startup and keeps
# crawling. An index that stops indexing because it has no identity yet is a worse failure than
# an index that indexes anonymously and reports it.
_CERT_DIR = os.environ.get("DIRECTORY_CERT_DIR", "/certs")


def _client_identity() -> Tuple[Optional[Tuple[str, str]], Optional[str]]:
    """(cert, key) to present on every crawl, and the SPIRE bundle to verify fabric names with."""
    cert = os.path.join(_CERT_DIR, "svid.0.pem")
    key = os.path.join(_CERT_DIR, "svid.0.key")
    bundle = os.path.join(_CERT_DIR, "bundle.0.pem")
    if not (os.path.exists(cert) and os.path.exists(key)):
        return None, None
    return (cert, key), (bundle if os.path.exists(bundle) else None)


def _verify_for(url: str, bundle: Optional[str]):
    """System CAs for a public host, the SPIRE bundle for a fabric one."""
    try:
        from urllib.parse import urlparse
        port = urlparse(url).port
    except Exception:
        port = None
    if port is None or port == 443:
        return True
    return bundle or True


from .agora_listings import fetch_listings  # noqa: E402  (no registry import: the reader-gate CI job runs without it)
from .board import pull_board  # noqa: E402  (§MEMBERSHIP phase C; registry-free like agora_listings)


async def fetch_json(client: httpx.AsyncClient, url: str) -> Tuple[Optional[Any], Optional[str]]:
    try:
        r = await client.get(url)
        if r.status_code == 200:
            return r.json(), None
        return None, f"http {r.status_code}"
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {str(e)[:120]}"


def verify_card(card: Dict[str, Any], jwks: Optional[Dict[str, Any]]) -> Tuple[bool, str]:
    """The registry card's own EdDSA signature against the registry's own JWKS — the same reconstruction the
    federation sync performs: the card's OWN declared signed_canonical + the freshness anchor, expiry refused."""
    sig = card.get("signature") or {}
    if not (sig.get("value") and sig.get("kid")):
        return False, "unsigned"
    if not jwks:
        return False, "jwks unreachable"
    key = next((k for k in jwks.get("keys", []) if k.get("kid") == sig.get("kid")), None)
    if key is None:
        return False, "kid not in jwks"
    payload = extract_paths(card, sig.get("signed_canonical") or SIGNED_CANONICAL_PATHS)
    if sig.get("signed_at") is not None:
        payload["_signed_at"] = sig.get("signed_at")
    if sig.get("expires_at") is not None:
        payload["_expires_at"] = sig.get("expires_at")
    try:
        ok = verify_with_jwk(payload, sig["value"], key)
    except Exception as e:  # noqa: BLE001
        return False, f"verify error {type(e).__name__}"
    if not ok:
        return False, "signature invalid"
    if sig.get("expires_at"):
        try:
            exp = dt.datetime.fromisoformat(str(sig["expires_at"]).replace("Z", "+00:00"))
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=dt.timezone.utc)
            if exp < dt.datetime.now(dt.timezone.utc):
                return False, "signature expired"
        except Exception:  # noqa: BLE001
            return False, "expiry unreadable"
    return True, "ok"


def _abs(base: str, path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    return path if path.startswith("http") else base.rstrip("/") + "/" + path.lstrip("/")


async def sync_registry(client: httpx.AsyncClient, store: Store, base: str, hop: int, fed_status: Optional[str]) -> Optional[Dict[str, Any]]:
    card, err = await fetch_json(client, f"{base}/.well-known/registry-card.json")
    if card is None:
        # an unreachable registry keeps its row and its cards; it is marked, never deleted (his answer 3)
        name = next((r["name"] for r in store.list_registries() if (r.get("public_url") or "").rstrip("/") == base), None)
        if name:
            store.set_registry_field(name, reachable=0, last_error=err, last_sync_at=now())
        return None
    ident = card.get("identity") or {}
    oper = card.get("operator") or {}
    jwks_url = _abs(base, (card.get("signature") or {}).get("jwks_url")) or f"{base}/.well-known/registry-jwks.json"
    jwks, _ = await fetch_json(client, jwks_url)
    verified, reason = verify_card(card, jwks)
    name = str(ident.get("registry_name") or "").strip()
    if not name:
        return None
    store.upsert_registry(
        name=name, trust_domain=(ident.get("trust_domain") or "").lower(), tier=ident.get("tier"),
        public_url=base, did_namespace=ident.get("did_namespace"), verified=1 if verified else 0, reason=reason,
        reachable=1, card_epoch=((card.get("lifecycle") or {}).get("card_etag")),
        location=oper.get("location_label"), latitude=oper.get("latitude"), longitude=oper.get("longitude"),
        parent_name=None, federation_status=fed_status, hop=hop, last_sync_at=now(), last_error=None,
        agents_indexed=(store.get_registry(name) or {}).get("agents_indexed", 0), card_json=json.dumps(card)[:200000],
        currency=(((card.get("fees") or {}).get("settlement_currency") if isinstance(card.get("fees"), dict) else None) or None),
    )
    return {"name": name, "trust_domain": (ident.get("trust_domain") or "").lower(), "tier": ident.get("tier"), "base": base, "verified": verified}


async def _index_page(client: httpx.AsyncClient, store: Store, reg: Dict[str, Any],
                      items: List[Any], feed: bool, force_detail: bool,
                      seen: List[str], ctr: Dict[str, Any]) -> None:
    """Index ONE page of a source's cards. Split out of `pull_cards` by §DIRPAGE so the walk can
    call it per page; the body is unchanged from the single-page version. `ctr` carries the three
    running values across pages (detail_reads, changed, max_epoch) because the walk owns them."""
    base, name = reg["base"], reg["name"]
    for it in items:
        cid = str(it.get("id") or "")
        if not cid:
            continue
        summary_epoch = it.get("updated_at") if feed else None
        if feed:
            seen.append(cid)
            if summary_epoch and str(summary_epoch) > str(ctr["max_epoch"] or ""):
                ctr["max_epoch"] = str(summary_epoch)
            if not force_detail and summary_epoch is not None and store.agent_epoch(cid) == str(summary_epoch):
                continue          # unchanged: the whole point of the feed — no detail read
        detail, derr = await fetch_json(client, f"{base}/api/v1/agent-cards/{cid}")
        ctr["detail_reads"] += 1
        if detail is None:
            continue
        cd = detail.get("card_data") or {}
        # NATIVE = no federation_metadata.source_registry (a mirror keeps its origin there; the list summary's
        # origin_registry_name is not populated for mirrors) — the same origin signal the G5 guard reads. Under
        # the cursor feed the server has already filtered; this stays as the check for a legacy registry.
        fm = cd.get("federation_metadata") if isinstance(cd.get("federation_metadata"), dict) else {}
        if fm.get("source_registry"):
            continue
        if not feed:
            seen.append(cid)
        updated = detail.get("updated_at") or summary_epoch
        if not feed and store.agent_epoch(cid) == updated and not force_detail:
            continue
        # the DID when the registry exposes it (agent_did on the read AND on the summary since §DIDWIDEN-1c /
        # §DIRFEED, card_data.did on mirrors and sim cards); a card is indexed either way, keyed by its card id
        did = detail.get("agent_did") or it.get("agent_did") or cd.get("did") or None
        issuer = agent_did_parts(str(did))[1] if did else None
        b = bond_ext(cd) or {}
        e = enf_ext(cd) or {}
        bond = {"status": b.get("status") or "none", "is_bonded": bool(is_bonded_status(b.get("status"))) if b else False,
                "amount": money_str(b.get("amount")) if b else None, "currency": b.get("currency") if b else None}
        enforcement = {"is_enforced": bool(is_enforced_status(e.get("status"))), "status": e.get("status")} if e else {"is_enforced": False, "status": None}
        store.upsert_agent(
            id=cid, did=(str(did) if did else None), name=detail.get("name"), hri=cd.get("humanReadableId"), description=detail.get("description"),
            is_active=1 if detail.get("is_active") else 0, updated_at=updated, source=name, source_td=reg["trust_domain"],
            issuer=issuer, shape=(agent_did_suffix_shape(str(did)) if did else None), home=name, bond_json=json.dumps(bond),
            enforcement_json=json.dumps(enforcement), verified=1 if reg["verified"] else 0, reachable=1, fetched_at=now(),
            card_json=json.dumps(cd)[:100000],
        )
        ctr["changed"] += 1


async def pull_cards(client: httpx.AsyncClient, store: Store, reg: Dict[str, Any], *, full: bool,
                     force_detail: bool = False) -> Dict[str, Any]:
    """Index the registry's NATIVE cards (its mirrors of other registries' agents are indexed from their origin).

    Two shapes, and the registry itself says which one it can serve:

      cursor — `?natives_only=true&updated_since=<the epoch we walked to>`; the registry filters, the SUMMARY
               carries the DID and the epoch, and a DETAIL read happens only for a card that actually changed.
      legacy — the registry ignored both parameters (FastAPI drops an unknown query param silently, so the ONLY
               honest signal is the `applied_filters` echo in the body): read the whole list and one detail per
               card, exactly as the first trial did.

    A cursor page is ordered ASC, so when a page is full the newest rows are the ones left behind and
    `max(updated_at)` over the page is still a safe cursor — the walk continues on the next cycle. A full pass
    additionally SWEEPS: whatever the source no longer publishes is marked unreachable.
    """
    base, name = reg["base"], reg["name"]
    row = store.get_registry(name) or {}

    # §DIRPAGE (2026-09-09) — WALK THE SOURCE, DO NOT READ ONE PAGE OF IT.
    #
    # THE DEFECT THIS REPLACES, measured the day the legacy frames joined the index: this asked for
    # ONE page of CARD_LIMIT and stopped. Frame-C publishes 5,502 natives, so the index held exactly
    # 5,000 and the cycle reported `more=false` — a truncated read claiming completeness, with the
    # answer sitting in the reply we already had (`pagination.total_pages: 2`). Raising the cap is
    # not available: /agent-cards/ declares `limit le=5000`, and 20000 made every source answer 422.
    #
    # 🔴 AND THE TRUNCATION WAS THE SMALLER HALF. A `full` pass SWEEPS whatever it did not see. It
    # ran with NO cursor, so it read the NEWEST CARD_LIMIT rows in DESC order — while the cursor
    # walk indexes forward from the oldest. Once an incremental walk had indexed past a page, the
    # next full pass would have marked those live agents GONE. A partial read must never sweep.
    #
    # The walk is a CURSOR, not an offset: `updated_since` is inclusive and the server orders
    # (updated_at ASC, id ASC) — a real partition, so a row that shifts between pages cannot be
    # double-counted or dropped (§DIRFEED-2 put that tiebreak there for exactly this). A full pass
    # is therefore just a cursor walk from the beginning, which is why `full` starts at EPOCH
    # instead of sending no cursor at all. No row cap — his word, "it shouldnt have a limit for now".
    EPOCH = "1970-01-01T00:00:00"
    stored_cursor = (row.get("cards_cursor") or None)
    cursor = EPOCH if full else stored_cursor
    seen: List[str] = []
    detail_reads = changed = 0
    pages = 0
    listed = 0
    max_epoch = cursor
    feed = False
    complete = False              # the walk reached a short page: the source says that is all
    stalled = False               # a same-instant cluster wider than one page — say it, never loop

    while True:
        q = f"limit={CARD_LIMIT}&natives_only=true"
        if cursor:
            q += "&updated_since=" + urllib.parse.quote(str(cursor))
        lst, err = await fetch_json(client, f"{base}/api/v1/agent-cards/?{q}")
        if lst is None:
            # a page failed mid-walk: keep what we indexed, but NEVER sweep on a partial read
            if pages == 0:
                return {"error": err, "mode": "unreachable"}
            break
        applied = lst.get("applied_filters") if isinstance(lst, dict) else None
        page_feed = bool(applied)   # the echo, never the status code: an ignored param also answers 200
        items = (lst.get("items") if isinstance(lst, dict) else lst) or []
        if pages == 0:
            feed = page_feed
        pages += 1
        listed += len(items)
        page_start_epoch = max_epoch

        ctr = {"detail_reads": 0, "changed": 0, "max_epoch": max_epoch}
        await _index_page(client, store, reg, items, feed, force_detail, seen, ctr)
        detail_reads += ctr["detail_reads"]
        changed += ctr["changed"]
        max_epoch = ctr["max_epoch"]

        if not feed:
            complete = True       # a legacy registry ignored the cursor: one read IS the whole list
            break
        if len(items) < CARD_LIMIT:
            complete = True       # short page = the source has nothing after this one
            break
        if str(max_epoch or "") == str(page_start_epoch or ""):
            # A FULL page whose newest row is no newer than where we started: more rows share one
            # instant than fit in a page, so the cursor cannot advance and another request returns
            # the same rows. Stop and NAME it rather than spin — and do not sweep on it.
            stalled = True
            break
        cursor = max_epoch

    gone = 0
    # §DIRPAGE — ONLY A WALK THAT REACHED THE END MAY SWEEP. `complete` means a short page ended it
    # (or a legacy registry served the whole list in one read); a stalled walk or a page that failed
    # mid-flight leaves `complete` False, and then the rows we did not reach are NOT marked gone.
    # Before this, a full pass read the newest CARD_LIMIT rows with no cursor and swept the rest —
    # so any card the incremental walk had indexed beyond one page would have been declared
    # unreachable by the next full pass.
    if full and complete:
        gone = store.sweep_source("agents", name, seen)
        store.set_registry_field(name, last_full_at=now())
    held = store.count_for_source("agents", name)
    store.set_registry_field(name, agents_indexed=held, feed_supported=1 if feed else 0,
                             **({"cards_cursor": max_epoch} if (feed and max_epoch) else {}))
    return {"mode": ("full" if full else "cursor") if feed else "legacy", "held": held, "listed": listed,
            "changed": changed, "detail_reads": detail_reads, "gone": gone, "cursor": max_epoch,
            "pages": pages, "complete": complete, "swept": bool(full and complete),
            # `more` now means what it says: the SOURCE still has rows we could not reach. It is no
            # longer "I filled my buffer", which was true on every full page and told nobody anything.
            "more": bool(stalled), "stalled": stalled, "error": None}


async def pull_listings(client: httpx.AsyncClient, store: Store, reg: Dict[str, Any]) -> Dict[str, Any]:
    """The venue half of discovery: what each registry LISTS on its own AGORA venue. The public listings feed is
    small and complete on every read, so every cycle is a full pass and may sweep — but only when the read
    succeeded (a 500 that swept would erase a venue because its database hiccuped)."""
    base, name = reg["base"], reg["name"]
    lst, err = await fetch_listings(fetch_json, client, base)   # §AGORAWORDS Phase 5: the new name first (agora_listings.py)
    if lst is None:
        return {"error": err, "held": store.count_for_source("listings", name)}
    items = (lst.get("listings") if isinstance(lst, dict) else lst) or []
    seen: List[str] = []
    for it in items:
        lid = str(it.get("id") or "")
        if not lid:
            continue
        rid = f"{name}:{lid}"
        seen.append(rid)
        st = it.get("stats") or {}
        store.upsert_listing(
            id=rid, listing_id=lid, source=name, symbol=it.get("symbol"), display_name=it.get("display_name"),
            currency=it.get("currency"), status=it.get("status"), approved=1 if it.get("approved") else 0,
            ipo_price=str(it.get("ipo_price")) if it.get("ipo_price") is not None else None,
            last_price=str(st.get("last")) if st.get("last") is not None else None,
            best_bid=str(st.get("best_bid")) if st.get("best_bid") is not None else None,
            best_ask=str(st.get("best_ask")) if st.get("best_ask") is not None else None,
            volume_24h=str(st.get("volume_24h_qty")) if st.get("volume_24h_qty") is not None else None,
            trades_24h=int(st.get("trades_24h") or 0), organization_id=it.get("organization_id"),
            treasury_agent_did=it.get("treasury_agent_did"), reachable=1, fetched_at=now(),
            listing_json=json.dumps(it)[:40000],
        )
    gone = store.sweep_source("listings", name, seen)
    held = store.count_for_source("listings", name)
    store.set_registry_field(name, listings_indexed=held)
    return {"held": held, "listed": len(items), "gone": gone, "error": None}


# §DIRFEED — ADMISSION. A row in an anchor's federation table is one of three things, and only two of them are
# an admission: a FRAME it federated with, an OPERATOR it licensed, or a name it merely DISCOVERED through
# someone else's fan-out. Hearsay is a lead, not a licence — a discovered row is admitted only if some anchor
# names it itself. And a peer is stopped here by DEACTIVATION, never deletion, so a row that is not ACTIVE must
# stop being pulled even though it is still in the table. Both facts are peer-row fields (§DIRFEED added them to
# the public profile); a registry too old to publish them is trusted as before, which is what the fallback says.
ADMITTED_TYPES = ("frame", "cloud_operator", "self")


def admits(row: Dict[str, Any]) -> Tuple[bool, str]:
    st = (row.get("peer_status") or "").strip().upper()
    ty = (row.get("peer_type") or "").strip().lower()
    if not st and not ty:
        return True, "unstated (older registry: admitted as before)"
    if st and st != "ACTIVE":
        return False, f"peer_status={st}"
    if ty and ty not in ADMITTED_TYPES:
        return False, f"peer_type={ty}"
    return True, f"{ty or '?'}/{st or '?'}"


async def discover(client: httpx.AsyncClient, anchor: str) -> List[Dict[str, Any]]:
    """The component around an anchor, from the anchor's own public topology (name, trust domain, public url, hop)."""
    out, seen = [], set()
    # (a) the anchor's federation table (public): every registry it federates with or licenses, with its url + status
    lst, _ = await fetch_json(client, f"{anchor}/api/v1/federation/registries")
    for r in (lst if isinstance(lst, list) else (lst or {}).get("registries") or (lst or {}).get("items") or []):
        # the address a client can dial: the peer's own SIGNED card first (identity.public_url, §DIRFEED), then
        # the row's base_url — which for a peer this anchor federated with or licensed is the mTLS federation
        # address (`…:8443`, the host SNI router) and is never a public API.
        url = str(r.get("public_url") or r.get("registry_url") or "").rstrip("/")
        ok, why = admits(r)
        if not ok:
            log.info("admission: %s not admitted by %s (%s)", r.get("registry_name"), anchor, why)
            continue
        if url.startswith("http") and not url.endswith(":8443") and url not in seen:
            seen.add(url); out.append({"name": r.get("registry_name"), "trust_domain": "", "public_url": url, "hop": 1, "federation_status": r.get("federation_status")})
    # (b) the anchor's topology feed (public), when it answers on this host
    lst, _ = await fetch_json(client, f"{anchor}/api/v1/agents/locations/trusted-registries")
    for e in (lst if isinstance(lst, list) else (lst or {}).get("items", []) or []):
        url = (e.get("public_url") or e.get("url") or "").rstrip("/")
        if url.startswith("http") and not url.endswith(":8443") and url not in seen:  # :8443 = the mTLS federation port, never the public API
            seen.add(url); out.append({"name": e.get("name"), "trust_domain": (e.get("trust_domain") or "").lower(), "public_url": url, "hop": int(e.get("hop") or 1)})
    return out


async def federation_status_map(client: httpx.AsyncClient, frame_base: str) -> Dict[str, str]:
    lst, _ = await fetch_json(client, f"{frame_base}/api/v1/federation/registries")
    items = lst if isinstance(lst, list) else (lst or {}).get("registries") or (lst or {}).get("items") or []
    return {str(r.get("registry_name")).lower(): str(r.get("federation_status") or "") for r in items if r.get("registry_name")}


async def sync_cycle(store: Store) -> Dict[str, Any]:
    t0 = time.time()
    # a cycle is FULL when the operator asked, when the extraction rule changed under the stored epochs, or on
    # the cadence — the three ways an incremental index is allowed to stop trusting itself
    cycle_no = int(store.get_meta("cycle_no", 0) or 0) + 1
    stored_extract = int(store.get_meta("extract_version", 0) or 0)
    extract_changed = stored_extract != EXTRACT_VERSION
    full = bool(FORCE_FULL or extract_changed or (cycle_no % max(FULL_EVERY, 1) == 1))
    summary: Dict[str, Any] = {"anchors": ANCHORS, "cycle": cycle_no, "full": full,
                               "hops_default": MAX_HOPS, "hops_by_registry": HOPS_BY_REGISTRY,
                               "extract_version": EXTRACT_VERSION, "extract_changed": extract_changed,
                               "registries": {}, "errors": []}
    _cert, _bundle = _client_identity()
    summary["client_identity"] = "svid" if _cert else "anonymous"
    if not _cert:
        log.warning("[directory] no SVID at %s — crawling ANONYMOUSLY. Every hop that asks for a "
                    "client certificate will treat this index as an unauthenticated stranger.", _CERT_DIR)
    _verify = _verify_for(ANCHORS[0] if ANCHORS else "", _bundle)
    if _cert and isinstance(_verify, str):
        # §DEPS (2026-09-27): httpx 0.28 drops `cert=` beside a CA PATH (the context it builds from the path is returned
        # before the client-certificate step), and this image is built FROM a registry image that now carries 0.28:
        # the crawl would offer no certificate to a fabric hop. The chain rides inside the context instead.
        import ssl as _ssl
        _ctx = _ssl.create_default_context(cafile=_verify)
        _ctx.load_cert_chain(*_cert)
        _verify = _ctx
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=False, cert=_cert, verify=_verify,
                                 headers={"User-Agent": "theprotocol-directory/trial"}) as client:
        seen: Dict[str, int] = {}
        todo: List[Tuple[str, int]] = [(a, 0) for a in ANCHORS]
        fed: Dict[str, str] = {}
        for a in ANCHORS:
            fed.update(await federation_status_map(client, a))
        while todo:
            base, hop = todo.pop(0)
            if base in seen:
                continue
            seen[base] = hop
            reg = await sync_registry(client, store, base, hop, None)
            if reg is None:
                summary["errors"].append(f"{base}: unreachable")
                continue
            store.set_registry_field(reg["name"], federation_status=fed.get(reg["name"].lower()) or ("anchor" if hop == 0 else None))
            if reg["verified"]:
                cards = await pull_cards(client, store, reg, full=full, force_detail=extract_changed)
                listings = await pull_listings(client, store, reg)
                board = await pull_board(client, store, reg)
                summary["registries"][reg["name"]] = {"hop": hop, "verified": True, "indexed": cards.get("held"),
                                                      "changed": cards.get("changed"), "detail_reads": cards.get("detail_reads"),
                                                      "mode": cards.get("mode"), "gone": cards.get("gone"),
                                                      "more": cards.get("more"), "error": cards.get("error"),
                                                      # §DIRPAGE — how many pages the walk took, whether it
                                                      # REACHED THE END, and whether it swept. A reader must be
                                                      # able to tell "indexed everything" from "indexed what it
                                                      # could reach", which the old `more` could not say.
                                                      "pages": cards.get("pages"), "complete": cards.get("complete"),
                                                      "swept": cards.get("swept"),
                                                      "listings": listings.get("held"), "listings_gone": listings.get("gone"),
                                                      "listings_error": listings.get("error"),
                                                      # §MEMBERSHIP phase C: the board's two reads, each in its own state
                                                      "membership": board["membership"], "commons": board["commons"],
                                                      "board_errors": board["errors"]}
                if cards.get("error"):
                    summary["errors"].append(f"{reg['name']}: cards {cards['error']}")
            else:
                summary["registries"][reg["name"]] = {"hop": hop, "verified": False, "reason": (store.get_registry(reg["name"]) or {}).get("reason")}
            budget = hop_budget(reg["name"], base)
            store.set_registry_field(reg["name"], hop_depth=budget)
            if hop < budget:
                for e in await discover(client, base):
                    if e["public_url"] not in seen:
                        todo.append((e["public_url"], hop + 1))
    summary["duration_s"] = round(time.time() - t0, 2)
    summary["at"] = now()
    summary["detail_reads"] = sum(int(r.get("detail_reads") or 0) for r in summary["registries"].values())
    store.set_meta("last_cycle", summary)
    store.set_meta("cycle_no", cycle_no)
    # only stamp the extraction version once a cycle has actually re-read everything under it
    if extract_changed and not summary["errors"]:
        store.set_meta("extract_version", EXTRACT_VERSION)
    return summary


async def run_forever(store: Store) -> None:
    """The cycle loop, with ATTEMPT and SUCCESS on separate clocks.

    §FDLEAK-2 (2026-09-07, agentvault2-eb's second finding): before this, a failed cycle logged and
    moved on, and `last_cycle` was written only on SUCCESS — so the GraphQL surface kept answering from
    stale data with a `lastCycleAt` from whenever the index last worked. Their Directory had been dead
    for 90 minutes (out of file descriptors) and a gates run looked like it was hanging, because **a
    Directory that has stopped indexing is indistinguishable from one with nothing new to index.** That
    is §VITALS's rule one layer out: a worker that stamps only its successes cannot be told from a quiet
    one, so the failure needs its own clock and its own counter.
    """
    consecutive = 0
    while True:
        try:
            s = await sync_cycle(store)
            consecutive = 0
            store.set_meta("last_cycle_error", None)
            log.info("cycle %s (%s) done in %ss, %s detail reads: %s", s.get("cycle"), "FULL" if s.get("full") else "cursor",
                     s.get("duration_s"), s.get("detail_reads"),
                     {k: f"{v.get('mode')} held={v.get('indexed')} chg={v.get('changed')} det={v.get('detail_reads')} gone={v.get('gone')} lst={v.get('listings')}"
                      for k, v in s.get("registries", {}).items()})
        except Exception as e:  # noqa: BLE001
            consecutive += 1
            # the store may be the thing that is broken — never let recording a failure mask it
            try:
                store.set_meta("last_cycle_error", {
                    "at": time.time(), "error": f"{type(e).__name__}: {e}"[:300], "consecutive": consecutive,
                })
            except Exception:  # noqa: BLE001
                log.exception("could not record the cycle failure (the store itself may be the fault)")
            log.exception("cycle failed (%s consecutive): %s", consecutive, e)
        await asyncio.sleep(SYNC_SECONDS)
