"""V0663, the Directory read path, step 1 (order gwo_0936844934f713153ede256c; PLAN_2026-11-13_DIRECTORY_REGISTRY_CARDS.md):
a registry asks the federated index which registries it knows, for peers and not only for agents, and verifies every
card itself.

The index is untrusted by construction: it can omit a card, never vouch for one.
  - Each card's signature is checked here (services/registry_card_verify, the federation sync's checks as one function).
  - The key is fetched from the origin the card names in its SIGNED identity.public_url, at
    /.well-known/registry-jwks.json: never from the unsigned signature.jwks_url and never from the address the index
    lists. An index that pairs a card it made with a key it controls gets an unverified row, because the key comes from
    the real registry's own origin.
  - That fetch goes through the outbound guard (site registry_jwks), is size-bounded and cached per origin in Redis.
  - Only a verified card names a registry: an unverified row carries the index's words under `index` and nothing else.
  - The database is only read: each verified registry is marked self, peer (an ACTIVE peer row), known (a row in another
    state) or candidate (no row, what an admin may invite). An index answer never creates a peer row.
  - A large answer is read up to MAX_REGISTRIES and says so (`truncated`).
The fan-out is not touched: this is the read path beside it (step 2 waits for the network plan's numbers).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from typing import Any, Awaitable, Callable, Dict, List, Optional
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger(__name__)

SITE = "registry_jwks"
JWKS_PATH = "/.well-known/registry-jwks.json"
JWKS_MAX_BYTES = 64 * 1024
JWKS_TIMEOUT_SEC = 6.0
JWKS_CACHE_SEC = 600
JWKS_FAIL_CACHE_SEC = 120
MAX_REGISTRIES = 300
CONCURRENCY = 8
RESULT_CACHE_SEC = 120
INDEX_TIMEOUT_SEC = 20.0
_JWKS_KEY = "registry:dirjwks:v1:"
RESULT_KEY = "registry:dirregistries:v1"

_FIELDS = "name trustDomain tier publicUrl reachable verified cardEpoch lastSyncAt"
INDEX_QUERY = "{ registries { " + _FIELDS + " card } }"
INDEX_QUERY_NO_CARD = "{ registries { " + _FIELDS + " } }"


class JwksUnavailable(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class IndexUnavailable(Exception):
    """The index could not answer; the message is what the route reports (never an empty list)."""


# --- where a card's key lives ------------------------------------------------------------------------------------

def jwks_origin(card: Any) -> Optional[str]:
    """https://host[:port] from the card's signed identity.public_url, or None when it names no https origin."""
    ident = card.get("identity") if isinstance(card, dict) and isinstance(card.get("identity"), dict) else {}
    url = ident.get("public_url")
    if not isinstance(url, str) or not url.strip():
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme.lower() != "https" or not parts.hostname:
        return None
    return f"https://{parts.netloc.lower()}"


def _origin_of(url: Any) -> Optional[str]:
    if not isinstance(url, str) or not url.strip():
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if not parts.scheme or not parts.hostname:
        return None
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}"


async def fetch_jwks(origin: str, *, inner: Optional[httpx.AsyncBaseTransport] = None) -> Dict[str, Any]:
    """The key set at <origin>/.well-known/registry-jwks.json, through the outbound guard; JwksUnavailable otherwise.
    No redirect is followed: the key set lives at the origin the card names, or nowhere."""
    from ..core.outbound_guard import OutboundRefused, guarded_client
    try:
        async with guarded_client(SITE, inner=inner, timeout=JWKS_TIMEOUT_SEC, verify=True) as client:
            request = client.build_request("GET", origin.rstrip("/") + JWKS_PATH, headers={"Accept": "application/json"})
            response = await client.send(request, stream=True)
            try:
                if response.status_code != 200:
                    raise JwksUnavailable(f"http_{response.status_code}")
                declared = response.headers.get("content-length", "")
                if declared.isdigit() and int(declared) > JWKS_MAX_BYTES:
                    raise JwksUnavailable("too_large")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body += chunk
                    if len(body) > JWKS_MAX_BYTES:
                        raise JwksUnavailable("too_large")
            finally:
                await response.aclose()
    except JwksUnavailable:
        raise
    except OutboundRefused as e:
        raise JwksUnavailable(f"refused_{e.reason}")
    except httpx.TimeoutException:
        raise JwksUnavailable("timeout")
    except httpx.HTTPError:
        raise JwksUnavailable("unreachable")
    try:
        jwks = json.loads(bytes(body))
    except ValueError:
        raise JwksUnavailable("not_a_key_set")
    if not isinstance(jwks, dict) or not isinstance(jwks.get("keys"), list):
        raise JwksUnavailable("not_a_key_set")
    return jwks


async def _jwks_for(origin: str, *, redis: Any, fetch: Callable[[str], Awaitable[Dict[str, Any]]],
                    memo: Dict[str, Any]) -> Dict[str, Any]:
    """The key set for `origin`, asked once per read (memo) and kept in Redis; a failure is kept for less."""
    if origin in memo:
        got = await memo[origin]
    else:
        memo[origin] = asyncio.ensure_future(_jwks_cached(origin, redis=redis, fetch=fetch))
        got = await memo[origin]
    if "fail" in got:
        raise JwksUnavailable(got["fail"])
    return got["jwks"]


async def _jwks_cached(origin: str, *, redis: Any, fetch: Callable[[str], Awaitable[Dict[str, Any]]]) -> Dict[str, Any]:
    key = _JWKS_KEY + hashlib.sha256(origin.encode()).hexdigest()
    if redis is not None:
        try:
            raw = await redis.get(key)
            if raw is not None:
                return json.loads(raw.decode() if isinstance(raw, (bytes, bytearray)) else raw)
        except Exception:  # noqa: BLE001 — a cache that cannot answer: ask the origin
            pass
    try:
        entry: Dict[str, Any] = {"jwks": await fetch(origin)}
        ttl = JWKS_CACHE_SEC
    except JwksUnavailable as e:
        entry, ttl = {"fail": e.reason}, JWKS_FAIL_CACHE_SEC
    if redis is not None:
        try:
            await redis.set(key, json.dumps(entry), ex=ttl)
        except Exception:  # noqa: BLE001
            pass
    return entry


# --- the peer rows: only read ---------------------------------------------------------------------------------------

def peers_stmt():
    from sqlalchemy import select
    from .. import models
    P = models.PeerRegistry
    return select(P.name, P.base_url, P.status)


async def load_peers(db: Any) -> List[Dict[str, Any]]:
    rows = (await db.execute(peers_stmt())).all()
    return [{"name": r[0], "base_url": r[1], "status": r[2]} for r in rows]


def _host(url: Any) -> Optional[str]:
    try:
        return (urlsplit(url).hostname or None) if isinstance(url, str) and url.strip() else None
    except ValueError:
        return None


def _relation(ident: Dict[str, Any], origin: Optional[str], peers: List[Dict[str, Any]],
              own_public_url: Optional[str]) -> str:
    own = _origin_of(own_public_url)
    if own and origin and own == origin:
        return "self"
    # by the registry's name or by the host it is reached at, never by trust domain: an operator carries its frame's
    # (measured on the sandbox: sandbox-b's operators all read sandbox-b.theprotocol.cloud, so a trust-domain match made
    # each of them "peer" because Sandbox Beta is one)
    name = str(ident.get("registry_name") or "")
    host = _host(ident.get("public_url"))
    rows = [p for p in peers if (name and p.get("name") == name) or (host and _host(p.get("base_url")) == host)]
    if any(str(p.get("status") or "").upper() == "ACTIVE" for p in rows):
        return "peer"
    return "known" if rows else "candidate"


# --- the read --------------------------------------------------------------------------------------------------------

def _index_part(row: Dict[str, Any]) -> Dict[str, Any]:
    return {"name": row.get("name"), "public_url": row.get("publicUrl"), "trust_domain": row.get("trustDomain"),
            "reachable": bool(row.get("reachable")), "verified": bool(row.get("verified")),
            "card_epoch": row.get("cardEpoch"), "last_sync_at": row.get("lastSyncAt")}


def _unverified(row: Dict[str, Any], reason: str) -> Dict[str, Any]:
    return {"name": None, "trust_domain": None, "tier": None, "public_url": None, "location": None, "currency": None,
            "card_etag": None, "verified": False, "reason": reason, "relation": "unverified", "address_agrees": None,
            "index": _index_part(row)}


async def read_registries(rows: List[Dict[str, Any]], *, peers: List[Dict[str, Any]], own_public_url: Optional[str],
                          redis: Any, fetch_jwks: Optional[Callable[[str], Awaitable[Dict[str, Any]]]] = None
                          ) -> Dict[str, Any]:
    """Every row the index gave (up to MAX_REGISTRIES), each verified here against the key at its card's own origin."""
    from .registry_card_verify import verify_registry_card
    fetch = fetch_jwks or globals()["fetch_jwks"]
    rows = [r for r in rows if isinstance(r, dict)]
    read = rows[:MAX_REGISTRIES]
    memo: Dict[str, Any] = {}
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(row: Dict[str, Any]) -> Dict[str, Any]:
        card = row.get("card") if isinstance(row.get("card"), dict) else None
        if card is None:
            if row.get("_index_serves_cards") is False:
                return _unverified(row, "the index serves no cards (an older Directory)")
            return _unverified(row, "the index holds no whole card")
        origin = jwks_origin(card)
        if origin is None:
            return _unverified(row, "the card names no https origin")
        try:
            async with sem:
                jwks = await _jwks_for(origin, redis=redis, fetch=fetch, memo=memo)
        except JwksUnavailable as e:
            return _unverified(row, f"jwks unavailable ({e.reason})")
        ok, reason = verify_registry_card(card, jwks)
        if not ok:
            return _unverified(row, reason)
        ident = card.get("identity") or {}
        oper = card.get("operator") if isinstance(card.get("operator"), dict) else {}
        fees = card.get("fees") if isinstance(card.get("fees"), dict) else {}
        life = card.get("lifecycle") if isinstance(card.get("lifecycle"), dict) else {}
        return {"name": ident.get("registry_name"), "trust_domain": ident.get("trust_domain"), "tier": ident.get("tier"),
                "public_url": ident.get("public_url"), "location": oper.get("location_label"),
                "currency": fees.get("settlement_currency"), "card_etag": life.get("card_etag"),
                "verified": True, "reason": "ok", "relation": _relation(ident, origin, peers, own_public_url),
                "address_agrees": _origin_of(row.get("publicUrl")) == origin, "index": _index_part(row)}

    out = list(await asyncio.gather(*(one(r) for r in read)))
    verified = sum(1 for r in out if r["verified"])
    return {"registries": out, "truncated": len(rows) > len(read),
            "counts": {"index": len(rows), "read": len(read), "verified": verified, "unverified": len(out) - verified}}


# --- the index -------------------------------------------------------------------------------------------------------

async def _ask_index(query: str) -> Dict[str, Any]:
    from ..routers.public_directory import _client_kwargs, _upstream
    up = _upstream()
    kwargs = _client_kwargs(up)
    kwargs["timeout"] = INDEX_TIMEOUT_SEC
    try:
        async with httpx.AsyncClient(**kwargs) as client:
            r = await client.post(f"{up}/graphql", json={"query": query})
    except Exception as e:  # noqa: BLE001
        logger.warning("[directory] registries: index unreachable at %s: %s", up, e)
        raise IndexUnavailable("the federated index is unreachable")
    try:
        body = r.json()
    except ValueError:
        raise IndexUnavailable(f"the federated index answered {r.status_code} with no GraphQL body")
    if not isinstance(body, dict):
        raise IndexUnavailable("the federated index answered something other than a GraphQL body")
    return body


async def index_registries() -> List[Dict[str, Any]]:
    """The registries the index knows, each with its stored signed card. An index that serves no cards yet (an older
    Directory) is asked again without them: its rows come back, each unverified, and the route says why."""
    body = await _ask_index(INDEX_QUERY)
    errors = body.get("errors") or []
    if errors and any("field 'card'" in str((e or {}).get("message", "")) for e in errors if isinstance(e, dict)):
        body = await _ask_index(INDEX_QUERY_NO_CARD)
        errors = body.get("errors") or []
        rows = ((body.get("data") or {}).get("registries")) if not errors else None
        if isinstance(rows, list):
            return [{**r, "card": None, "_index_serves_cards": False} for r in rows if isinstance(r, dict)]
    if errors:
        first = errors[0].get("message") if isinstance(errors[0], dict) else str(errors[0])
        raise IndexUnavailable(f"the federated index refused the query: {first}")
    rows = (body.get("data") or {}).get("registries")
    if not isinstance(rows, list):
        raise IndexUnavailable("the federated index answered no registries list")
    return rows


async def redis_handle() -> Any:
    try:
        from ..background_tasks.leader import get_redis
        return await get_redis()
    except Exception:  # noqa: BLE001
        return None


def configured() -> bool:
    return bool((os.getenv("DIRECTORY_MTLS_URL", "") or "").strip())
