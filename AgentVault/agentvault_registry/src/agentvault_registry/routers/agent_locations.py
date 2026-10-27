"""
Agent Locations Router — AgentWorld geolocation API.

Provides lat/lng data for the 3D Earth globe visualization at /agentworld.
GET  /api/v1/agents/locations      — public, no auth required
PUT  /api/v1/agents/locations/me   — developer auth required

OWL Implementation — 2026-03-08
"""
import asyncio
import ipaddress
import logging
import os
import socket
from typing import Optional
from urllib.parse import urlparse as _urlparse
from fastapi import APIRouter, Depends, HTTPException, Query, Response, Security
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select

from agentvault_registry import models, database
from agentvault_registry.security import get_current_developer

logger = logging.getLogger(__name__)
router = APIRouter()


# Browsers apply heuristic HTTP caching to endpoints without explicit Cache-Control
# headers (RFC 7234 §4.2.2 — typical 10% of Last-Modified-age). That was causing
# the Cesium globe to stick on stale lat/lng for minutes after an operator's
# location was updated. These endpoints read from in-process caches (10 min
# operator, 30 min trusted-registries) that are already fast, so we explicitly
# tell the browser not to layer its own cache on top.
_NO_BROWSER_CACHE = {"Cache-Control": "no-store, must-revalidate", "Pragma": "no-cache"}

# §WORLDFIND — how many search matches may be merged into the sample per book
# (locals and federated each get this cap). Bounded so a one-character-ish query
# cannot drag the whole population onto the globe.
_SEARCH_CAP = 200

# --- Docker DNS bypass for federation probes ---
# When operator domains have Docker network aliases (for cross-TEG mTLS routing),
# Docker DNS resolves them to internal container IPs where port 443 doesn't exist.
# This helper detects that case and connects directly to the host's public IP
# with a Host header — probing through host nginx like a real external client.
# For genuinely external operators (different servers), requests go normally.
_HOST_PUBLIC_IP: str = ""

def _get_host_public_ip() -> str:
    global _HOST_PUBLIC_IP
    if _HOST_PUBLIC_IP:
        return _HOST_PUBLIC_IP
    ip = os.environ.get("PUBLIC_IP", "")
    if not ip:
        try:
            hostname = os.environ.get("PUBLIC_HOSTNAME", "api.theprotocol.cloud")
            ip = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)[0][4][0]
        except Exception:
            ip = ""
    _HOST_PUBLIC_IP = ip
    return ip

def _needs_dns_bypass(hostname: str) -> bool:
    """Check if a hostname resolves to a private IP range (Docker, NAT) or our own host IP.
    If so, Docker DNS has hijacked the domain and we need to bypass it.

    2026-05-05 audit Tier 1D: switched from `resolved.startswith("172.")` (which
    missed 10.x and 192.168.x and wrongly caught the public 172.0–172.15 block)
    to `ipaddress.ip_address.is_private` — RFC 1918 + RFC 4193 + link-local.
    The legacy substring caused today's Bavaria-stacking incident."""
    host_ip = _get_host_public_ip()
    if not host_ip:
        return False
    try:
        resolved = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)[0][4][0]
        if resolved == host_ip:
            return True
        try:
            return ipaddress.ip_address(resolved).is_private
        except ValueError:
            return False
    except Exception:
        return False


def _crawl_client(timeout: float):
    """CB-499: the HTTP client for crawling peers' federation listings (the trusted-registries map here, the topology
    map in main.py, the peer fallback of cross-registry receiver resolution). Peers' answers feed peer rows and transfer
    routing, so the TLS certificate is verified with this registry's own trust (the SPIRE bundle and the public roots,
    es_ssl_helper.get_httpx_verify) and a redirect is not followed: a peer answers at its own address or not at all."""
    import httpx as _httpx
    from agentvault_registry.es_ssl_helper import get_httpx_verify
    return _httpx.AsyncClient(timeout=timeout, verify=get_httpx_verify(), follow_redirects=False)


async def _crawl_get(client, base_url: str, path: str):
    """GET `<base_url><path>` with a client from _crawl_client. When the peer's name resolves to this host (Docker DNS
    or the host's own address, _needs_dns_bypass), the request goes to the host's public address on 443 with the name
    in the Host header, and the certificate is verified for that NAME (the sni_hostname extension), not the address."""
    parsed = _urlparse(base_url)
    host_ip = _get_host_public_ip()
    if host_ip and parsed.hostname and _needs_dns_bypass(parsed.hostname):
        return await client.get(f"https://{host_ip}{path}", headers={"Host": parsed.hostname},
                                extensions={"sni_hostname": parsed.hostname})
    return await client.get(f"{(base_url or '').rstrip('/')}{path}")


# ── §GLOBEPOP 2026-08-11 — fair per-registry population for the globe views ──
# The old selection served the top-2000 locals by reputation plus the first
# 2000 federated DIDs BY ALPHABET (DISTINCT ON forces ORDER BY agent_did), so
# whether a small registry appeared at all was DID-spelling luck (measured:
# op-doha 21 of 111 shown, 15% of the 10,530-card federation visible).
# Selection now: every registry is guaranteed min(min_per_registry, population)
# points, the remaining budget is split proportionally to TRUE populations,
# ranked inside each registry (locals by reputation; federated by sync recency —
# synced cards carry no reputation field, verified 0 of 10,530). The response
# adds per-registry aggregates so the frontends label TRUE populations
# regardless of how many points are drawn.

# §RENAMEFIX (2026-08-19) — a slug-rewrite map used to live here, mapping the
# CURRENT operator names back onto their RETIRED ones (op-newyork -> op-tokyo,
# op-losangeles -> op-singapore, op-houston -> op-seoul, op-chicago -> op-sydney).
# Its premise ("the cards keep their ORIGINAL slug") was FALSE: measured on
# registry-a, the mirrored cards carry op-newyork 140 / op-houston 137 /
# op-chicago 137, i.e. the CURRENT names. The map therefore rewrote correct
# origins into names no peer row carries any more, so the globe grouped agents
# under registries that do not exist (no agents around op-newyork) and labelled
# the Los Angeles node "op-singapore". The one genuinely stale set (137 cards on
# registry-a stamped op-singapore, sticky per crud/agent_card.py) was re-stamped
# in data, and the retired identity was retired as `rename_debris` on all 16
# nodes. Group by the PUBLISHED origin; never translate names here again.
_ORIGIN_CASE_SQL = "coalesce(raw_origin, '(unknown)')"


def _allocate_quotas(populations: dict, budget: int, min_per: int) -> dict:
    """Split `budget` points across registries: minimums first, the remainder
    proportional to population, never exceeding a registry's population.
    budget <= 0 means no cap (everything). Pure function — unit-tested in
    tests/test_globepop_allocator.py."""
    if budget <= 0:
        return dict(populations)
    quotas = {o: min(p, min_per) for o, p in populations.items()}
    leftover = budget - sum(quotas.values())
    if leftover <= 0:
        return quotas  # minimums outrank the budget: every registry stays visible
    remaining = {o: populations[o] - quotas[o]
                 for o in populations if populations[o] > quotas[o]}
    total_rem = sum(remaining.values())
    if total_rem <= 0:
        return quotas
    shares = {o: leftover * r / total_rem for o, r in remaining.items()}
    for o, share in shares.items():
        quotas[o] += min(int(share), remaining[o])
    left = budget - sum(quotas.values())
    # the last few points go by largest fractional remainder
    for o in sorted(shares, key=lambda k: shares[k] - int(shares[k]), reverse=True):
        if left <= 0:
            break
        if quotas[o] < populations[o]:
            quotas[o] += 1
            left -= 1
    return quotas


@router.get(
    "/",
    summary="Get agent locations for globe visualization",
    description="Public endpoint returning agent lat/lng coordinates for AgentWorld. "
                "Every registry is guaranteed min_per_registry points; the remaining "
                "budget is split proportionally to true populations (budget=0 = no "
                "cap). Per-registry TRUE totals ride in `registries`.",
    # §pass56 PR-5: tags= dropped; main.py:include_router supplies "AgentWorld"
)
async def get_agent_locations(
    response: Response,
    budget: int = Query(6000, ge=0, le=50000),
    min_per_registry: int = Query(50, ge=0, le=1000),
    q: Optional[str] = Query(
        None, min_length=2, max_length=120,
        description="Search the FULL population by name or DID. Matches are merged into "
                    "the sample even when they fall outside the per-registry quota, so an "
                    "agent that was never drawn can still be found.",
    ),
    db: AsyncSession = Depends(database.get_db),
):
    """
    Returns a fair per-registry sample of active agents with coordinates,
    plus true per-registry totals. Used by AgentWorld / Universe / GalacticMap.

    Locals come from the agents table (the single authority for our own
    population — mirrored self-cards are excluded, including strays whose
    local row is gone). Federated cards dedup by DISTINCT ON (agent_did),
    newest sync wins; retired-slug origins are mapped to current names.
    """
    for k, v in _NO_BROWSER_CACHE.items():
        response.headers[k] = v
    from sqlalchemy import text as _sqltext

    own_td = os.environ.get("SPIRE_TRUST_DOMAIN", "agentvault.com").lower()
    own_name = os.getenv("REGISTRY_NAME", "Local Registry")

    # -- 1. True populations --------------------------------------------------
    # §DARKSYNC (2026-09-22): a dark (unlisted) service agent is not on the globe, native or mirror
    _dark_dids = select(models.AgentCard.agent_did).where(models.AgentCard.unlisted.is_(True), models.AgentCard.agent_did.isnot(None))
    local_pop = (await db.execute(
        select(func.count()).select_from(models.Agent)
        .where(models.Agent.status == "active", ~models.Agent.did.in_(_dark_dids))
    )).scalar() or 0

    fed_pop_sql = _sqltext(f"""
        WITH latest AS (
            SELECT DISTINCT ON (agent_did) agent_did,
                   card_data->'federation_metadata'->>'origin_registry_name' AS raw_origin
            FROM agent_cards
            WHERE is_active AND agent_did IS NOT NULL AND NOT unlisted  -- §DARKSYNC
            ORDER BY agent_did, updated_at DESC
        ),
        mapped AS (
            SELECT agent_did, {_ORIGIN_CASE_SQL} AS origin
            FROM latest
            WHERE agent_did NOT IN (SELECT did FROM agents)
        )
        SELECT origin, count(*) AS pop
        FROM mapped
        WHERE origin <> :own_name
        GROUP BY origin
    """)
    fed_pops = {r.origin: int(r.pop)
                for r in (await db.execute(fed_pop_sql, {"own_name": own_name})).all()}

    populations = dict(fed_pops)
    populations[own_name] = local_pop

    # -- 2. Quotas ------------------------------------------------------------
    quotas = _allocate_quotas(populations, budget, min_per_registry)

    # -- 3. Locals, ranked by reputation --------------------------------------
    rows = []
    local_quota = quotas.get(own_name, 0)
    if local_quota > 0:
        stmt = (
            select(
                models.Agent.did,
                models.Agent.status,
                models.Agent.reputation_score,
                models.Agent.latitude,
                models.Agent.longitude,
                models.Agent.location_label,
                models.AgentCard.name.label("agent_name"),
            )
            .outerjoin(models.AgentCard, models.AgentCard.agent_did == models.Agent.did)
            .where(models.Agent.status == "active", ~models.Agent.did.in_(_dark_dids))
            .order_by(models.Agent.reputation_score.desc())
            .limit(local_quota)
        )
        rows = (await db.execute(stmt)).all()

    # Local agents — they live on this registry, so trust_domain = our own
    # SPIRE_TRUST_DOMAIN (audit Theme #1: the frontend must not derive frame
    # from URL substrings).
    locations_list = [
        {
            "did": row.did,
            "name": row.agent_name,
            "status": row.status,
            "reputation": row.reputation_score,
            "lat": row.latitude,
            "lng": row.longitude,
            "label": row.location_label,
            "trust_domain": own_td,
        }
        for row in rows
    ]

    # Federated trust_domain resolution — peer_registries.name is the
    # authoritative source, SPIFFE stamp the fallback (W2 lesson: legacy
    # `agentvault.com` stamps on Frame-B-native cards lie; the peer row wins).
    from agentvault_registry.services.spiffe_canonical import (
        extract_canonical, _normalize_name as _norm_name,
    )

    peer_td_by_name: dict = {}
    try:
        peer_rows = (await db.execute(
            select(models.PeerRegistry.name, models.PeerRegistry.trust_domain)
            .where(models.PeerRegistry.trust_domain.isnot(None))
        )).all()
        for pr in peer_rows:
            if pr.name and pr.trust_domain:
                peer_td_by_name[_norm_name(pr.name)] = pr.trust_domain.lower()
    except Exception as _td_lookup_exc:
        logger.debug(f"[agent-locations] peer trust_domain lookup failed: {_td_lookup_exc}")

    # -- 4. Federated sample: per-origin quotas in ONE window query -----------
    # DISTINCT ON (agent_did) dedups the insert-not-upsert sync rows (newest
    # copy wins — most likely to carry the correct origin). DID-less cards are
    # a bug, filtered. DIDs present in the agents table are OUR agents (soft
    # deletes keep the row), so mirrored self-cards never count as federated.
    fed_quotas = {o: q for o, q in quotas.items() if o != own_name and q > 0}
    fed_rows = []
    if fed_quotas:
        vals_sql = ", ".join(f"(:o{i}, :q{i})" for i in range(len(fed_quotas)))
        params: dict = {"own_name": own_name}
        # ⚠ NOT named `q`: a `for … (o, q)` here rebinds the SEARCH parameter to
        # a quota int for the rest of the function (Python loop vars outlive the
        # loop), which 500'd every call to this endpoint. Same class as the
        # §MCPTEST loop variable that ate the skip list.
        for i, (o, quota) in enumerate(fed_quotas.items()):
            params[f"o{i}"] = o
            # asyncpg infers the VALUES columns as text (measured: binding int
            # raises DataError "expected str, got int"); the SQL casts ::int.
            params[f"q{i}"] = str(int(quota))
        fetch_sql = _sqltext(f"""
            WITH latest AS (
                SELECT DISTINCT ON (agent_did) agent_did, name, updated_at,
                       card_data->'federation_metadata'->>'origin_registry_name' AS raw_origin,
                       card_data->'federation_metadata'->'origin_registry_location'->>'latitude'  AS reg_lat,
                       card_data->'federation_metadata'->'origin_registry_location'->>'longitude' AS reg_lng,
                       card_data->'federation_metadata'->'origin_registry_location'->>'label'     AS reg_label,
                       card_data->'location'->>'latitude'  AS agent_lat,
                       card_data->'location'->>'longitude' AS agent_lng,
                       card_data->'location'->>'label'     AS agent_label,
                       coalesce(card_data->'federation_metadata'->>'source_registry',
                                card_data->'federation_metadata'->>'first_synced_from', '') AS source_spiffe
                FROM agent_cards
                WHERE is_active AND agent_did IS NOT NULL AND NOT unlisted  -- §DARKSYNC
                ORDER BY agent_did, updated_at DESC
            ),
            mapped AS (
                SELECT *, {_ORIGIN_CASE_SQL} AS origin
                FROM latest
                WHERE agent_did NOT IN (SELECT did FROM agents)
            ),
            ranked AS (
                SELECT *, row_number() OVER (PARTITION BY origin
                                             ORDER BY updated_at DESC, agent_did) AS rn
                FROM mapped
                WHERE origin <> :own_name
            )
            SELECT r.agent_did, r.name, r.origin, r.reg_lat, r.reg_lng, r.reg_label,
                   r.agent_lat, r.agent_lng, r.agent_label, r.source_spiffe
            FROM ranked r
            JOIN (VALUES {vals_sql}) AS q(origin, quota) ON r.origin = q.origin
            WHERE r.rn <= q.quota::int
        """)
        fed_rows = (await db.execute(fetch_sql, params)).all()

    def _coord(primary, fallback):
        # JSON ->> extracts are text; 0.0 is a legal coordinate, so no `or`.
        for v in (primary, fallback):
            if v not in (None, ""):
                try:
                    return float(v)
                except (TypeError, ValueError):
                    continue
        return None

    shown_by_origin: dict = {}
    for r in fed_rows:
        canonical = extract_canonical(r.source_spiffe) if r.source_spiffe else None
        fed_td = None
        if canonical and canonical[1]:
            fed_td = peer_td_by_name.get(_norm_name(canonical[1]))
        if not fed_td and canonical and canonical[0]:
            fed_td = canonical[0].lower()
        if not fed_td:
            fed_td = peer_td_by_name.get(_norm_name(r.origin))

        # Always emit even with null lat/lng — the frontend orbits the origin
        # registry's coords when absent. Registry location beats the card
        # creator's personal coords (agents from Tokyo appear at Tokyo).
        entry = {
            "did": r.agent_did,
            "name": r.name,
            "status": "active",
            "reputation": 0.0,
            "lat": _coord(r.reg_lat, r.agent_lat),
            "lng": _coord(r.reg_lng, r.agent_lng),
            "label": r.reg_label or r.agent_label or "",
            "origin_registry": r.origin,
        }
        if fed_td:
            entry["trust_domain"] = fed_td
        locations_list.append(entry)
        shown_by_origin[r.origin] = shown_by_origin.get(r.origin, 0) + 1

    # -- 4b. SEARCH (§WORLDFIND) — the sample is a VIEW, not the population ---
    # The globe's own filter can only match dots the client was given, so an
    # agent outside its registry's quota was unfindable no matter what you
    # typed (measured 2026-08-16: op-doha 114 agents, 80 drawn — the FX canary
    # tx-doha was one of the 34 missing, and searching for it returned nothing).
    # A search therefore has to ask the SERVER, which can see everyone. Matches
    # are merged into the sample and deduped, so search ADDS reach and never
    # removes what is already on the globe.
    # Captured defensively as a string: this handler is long, and a later loop
    # variable named `q` has already shadowed the parameter once (see above).
    search_term = str(q).strip() if q is not None and not isinstance(q, int) else ""
    search_matched = 0
    if search_term:
        needle = f"%{search_term.lower()}%"
        seen_dids = {e["did"] for e in locations_list if e.get("did")}

        local_hits = (await db.execute(
            select(
                models.Agent.did, models.Agent.status, models.Agent.reputation_score,
                models.Agent.latitude, models.Agent.longitude, models.Agent.location_label,
                models.AgentCard.name.label("agent_name"),
            )
            .outerjoin(models.AgentCard, models.AgentCard.agent_did == models.Agent.did)
            .where(
                models.Agent.status == "active",
                ~models.Agent.did.in_(_dark_dids),   # §DARKSYNC
                func.lower(func.coalesce(models.AgentCard.name, "")).like(needle)
                | func.lower(models.Agent.did).like(needle),
            )
            .order_by(models.Agent.reputation_score.desc())
            .limit(_SEARCH_CAP)
        )).all()
        for row in local_hits:
            if row.did in seen_dids:
                continue
            seen_dids.add(row.did)
            locations_list.append({
                "did": row.did, "name": row.agent_name, "status": row.status,
                "reputation": row.reputation_score, "lat": row.latitude,
                "lng": row.longitude, "label": row.location_label,
                "trust_domain": own_td, "matched_search": True,
            })
            search_matched += 1

        # Same projection as the sampled federated query above (source_spiffe is
        # DERIVED from card_data, not a column) so a searched-in dot carries the
        # identical trust-domain + coordinate inputs as a sampled one.
        fed_hits = (await db.execute(_sqltext(f"""
            WITH latest AS (
                SELECT DISTINCT ON (agent_did) agent_did, name,
                       card_data->'federation_metadata'->>'origin_registry_name' AS raw_origin,
                       card_data->'federation_metadata'->'origin_registry_location'->>'latitude'  AS reg_lat,
                       card_data->'federation_metadata'->'origin_registry_location'->>'longitude' AS reg_lng,
                       card_data->'federation_metadata'->'origin_registry_location'->>'label'     AS reg_label,
                       card_data->'location'->>'latitude'  AS agent_lat,
                       card_data->'location'->>'longitude' AS agent_lng,
                       card_data->'location'->>'label'     AS agent_label,
                       coalesce(card_data->'federation_metadata'->>'source_registry',
                                card_data->'federation_metadata'->>'first_synced_from', '') AS source_spiffe
                FROM agent_cards
                WHERE is_active AND agent_did IS NOT NULL AND NOT unlisted  -- §DARKSYNC
                  AND (lower(coalesce(name, '')) LIKE :needle OR lower(agent_did) LIKE :needle)
                ORDER BY agent_did, updated_at DESC
            )
            SELECT agent_did, name, source_spiffe, reg_lat, reg_lng, reg_label,
                   agent_lat, agent_lng, agent_label, {_ORIGIN_CASE_SQL} AS origin
            FROM latest
            WHERE agent_did NOT IN (SELECT did FROM agents)
            LIMIT :cap
        """), {"needle": needle, "cap": _SEARCH_CAP})).all()
        for r in fed_hits:
            if r.agent_did in seen_dids or r.origin == own_name:
                continue
            seen_dids.add(r.agent_did)
            canonical = extract_canonical(r.source_spiffe) if r.source_spiffe else None
            fed_td = None
            if canonical and canonical[1]:
                fed_td = peer_td_by_name.get(_norm_name(canonical[1]))
            if not fed_td and canonical and canonical[0]:
                fed_td = canonical[0].lower()
            if not fed_td:
                fed_td = peer_td_by_name.get(_norm_name(r.origin))
            entry = {
                "did": r.agent_did, "name": r.name, "status": "active",
                "reputation": 0.0,
                "lat": _coord(r.reg_lat, r.agent_lat),
                "lng": _coord(r.reg_lng, r.agent_lng),
                "label": r.reg_label or r.agent_label or "",
                "origin_registry": r.origin, "matched_search": True,
            }
            if fed_td:
                entry["trust_domain"] = fed_td
            locations_list.append(entry)
            search_matched += 1

    # -- 4c. Proven work for the hover card (ONE grouped pass, no N+1) -------
    # Same aggregation the Discovery Proven-work band and the ranking use, so
    # the globe can never disagree with the marketplace about who did the work.
    # track_record_summaries returns ONLY history-bearing DIDs — the guild books
    # are tiny, so this is a couple of grouped scans, not a per-dot lookup.
    try:
        from agentvault_registry.services.track_record import track_record_summaries
        tr = await track_record_summaries(db, [e["did"] for e in locations_list if e.get("did")])
        for e in locations_list:
            s = tr.get(e.get("did") or "")
            if not s:
                continue
            d = s.get("disputes") or {}
            ot = s.get("on_time") or {}
            vol = (s.get("volume") or [{}])[0]
            # ⚠ These key names are the CANONICAL compact contract, the same one
            # /agent-cards/discover emits and the FE's TrackRecordCompact +
            # earnedMarks() read. An earlier cut of this endpoint spelled them
            # `jobs_verified` / `cross_registry_jobs`, and the globe silently
            # showed no earned mark at all for weeks of a session: earnedMarks()
            # reads `tr.jobs`, got undefined, and returned "no tier" while the
            # hover's Proven band (reading the other spelling) rendered fine, so
            # the data looked present and the mark looked broken. One fact, one
            # name — do not re-spell these per endpoint.
            e["track_record"] = {
                "jobs": s.get("jobs_verified") or 0,
                "stars": s.get("avg_stars"),
                "cross_registry": s.get("cross_registry_jobs") or 0,
                "traveled": s.get("traveled_jobs") or 0,
                "five_star": s.get("five_star") or 0,
                "disputes": (d.get("total") or 0),
                "open_disputes": d.get("open") or 0,
                "lost_disputes": d.get("lost") or 0,
                # enough for the hover label to be worth reading, still one
                # grouped pass: no extra query pays for any of these.
                "on_time_met": ot.get("met") or 0,
                "on_time_of": ot.get("of") or 0,
                "volume_total": vol.get("total"),
                "volume_currency": vol.get("currency"),
                "distinct_posters": s.get("distinct_posters") or 0,
                "last_verified_at": s.get("last_verified_at"),
            }
    except Exception as _tr_exc:  # noqa: BLE001 — cosmetic enrichment, never fatal
        logger.debug(f"[agent-locations] track-record enrichment skipped: {_tr_exc}")

    # -- 5. Per-registry TRUE totals (the part that stops the counts lying) ---
    # `shown` is counted from what we actually EMIT (sample + any search
    # matches), so the globe's per-registry label never over- or under-states
    # the dots the client received.
    shown_by_origin = {}
    local_shown = 0
    for e in locations_list:
        o = e.get("origin_registry")
        if o:
            shown_by_origin[o] = shown_by_origin.get(o, 0) + 1
        else:
            local_shown += 1

    registries = []
    for origin, pop in sorted(populations.items(), key=lambda kv: -kv[1]):
        if origin == own_name:
            td, shown = own_td, local_shown
        else:
            td = peer_td_by_name.get(_norm_name(origin))
            shown = shown_by_origin.get(origin, 0)
        registries.append({"name": origin, "trust_domain": td,
                           "total": pop, "shown": shown})

    return {
        "locations": locations_list,
        "total": len(locations_list),
        "registries": registries,
        "sampling": {"budget": budget, "min_per_registry": min_per_registry},
        "search": {"q": search_term, "matched": search_matched} if search_term else None,
    }


@router.get(
    "/operator",
    summary="Get registry operator location",
    description="Returns the registry operator's (first admin) lat/lng. "
                "Used by AgentWorld to position the registry node on the globe.",
    # §pass56 PR-5: tags= dropped; main.py:include_router supplies "AgentWorld"
)
async def get_operator_location(
    response: Response,
    db: AsyncSession = Depends(database.get_db),
):
    """Returns the registry operator's location for registry node positioning.
    Queries the first admin account (by id) as the canonical operator.
    Result cached per worker for 10 minutes — the value only changes when the
    admin edits their profile, but this endpoint is polled by every peer in the
    federation during BFS crawls (observed 300+ hits/min on Registry A)."""
    for k, v in _NO_BROWSER_CACHE.items():
        response.headers[k] = v
    global _operator_location_cache
    now = _time.time()
    if now - _operator_location_cache["ts"] < _OPERATOR_LOCATION_TTL and _operator_location_cache["data"] is not None:
        return _operator_location_cache["data"]
    # 2026-07-29 — "first admin by id" is a fragile proxy for "the operator".
    # A registry stood up from the frame-test template carries leftover template
    # admins (admin@test.sandbox id=2, tutorial-admin id=4) that sort BEFORE the
    # real operator account, so this returned NULL coordinates and the globe had
    # nowhere to place the registry — even though the operator had set their
    # location and the signed registry card carried it. Prefer the lowest-id admin
    # that actually HAS coordinates; fall back to the old behaviour when none do,
    # so a registry whose operator has not set a location is unchanged.
    stmt = (
        select(
            models.Developer.latitude,
            models.Developer.longitude,
            models.Developer.location_label,
        )
        .where(models.Developer.is_admin == True)  # noqa: E712
        .where(models.Developer.latitude.isnot(None))
        .where(models.Developer.longitude.isnot(None))
        .order_by(models.Developer.id.asc())
        .limit(1)
    )
    result = await db.execute(stmt)
    row = result.first()
    if row is None:
        result = await db.execute(
            select(
                models.Developer.latitude,
                models.Developer.longitude,
                models.Developer.location_label,
            )
            .where(models.Developer.is_admin == True)  # noqa: E712
            .order_by(models.Developer.id.asc())
            .limit(1)
        )
        row = result.first()
    if row and row.latitude is not None and row.longitude is not None:
        data = {
            "lat": row.latitude,
            "lng": row.longitude,
            "label": row.location_label,
        }
    else:
        data = {"lat": None, "lng": None, "label": None}
    _operator_location_cache = {"data": data, "ts": now}
    return data


@router.get(
    "/emission-policies",
    summary="Get event emission policies (internal; no auth)",
    description="Returns emission policy flags for all event types. "
                "Used by TEG and EventStore to determine emission authorization. "
                "No sensitive data exposed.",
    tags=["Internal"],
)
async def get_emission_policies_internal(
    db: AsyncSession = Depends(database.get_db),
):
    """Public endpoint for internal services to fetch emission policies."""
    stmt = select(models.EventEmissionPolicy).order_by(models.EventEmissionPolicy.event_type)
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return {
        "policies": [
            {
                "event_type": r.event_type,
                "emit_from_teg": r.emit_from_teg,
                "emit_from_registry": r.emit_from_registry,
                "skip_in_projection": r.skip_in_projection,
            }
            for r in rows
        ],
    }


# ── BFS Trusted Registry Discovery (cached) ─────────────────────────────
import json as _json
import time as _time
from urllib.parse import urlparse as _urlparse

_trusted_cache: dict = {"registries": [], "ts": 0}
# Topology rarely changes; 30 min keeps workers warm and cuts the 9-hop crawl
# cost significantly. With 40 workers on Registry A at the old 5-min TTL, a
# worker cold-started a BFS every ~7.5s.
_TRUSTED_TTL = 1800  # 30 min cache
# Background-refresh window: when a request hits the cache and the cache is
# older than this, we kick off a non-blocking BFS that union-grows the cache.
# This makes the cache self-heal from partial BFS results without waiting
# the full TTL.
_TRUSTED_REFRESH_INTERVAL = 60
_TRUSTED_REDIS_KEY = "registry:topology:trusted"
# Per-process single-flight guard — only one background BFS at a time per
# worker. Prevents a thundering herd when many requests see a stale cache.
# 2026-05-05 audit Tier 1C: replaced bool flag with Task ref. The bool
# version had a race: two concurrent requests could both see False, both
# set True, both schedule BFS. With a Task ref we check `done()` which is
# atomic in single-threaded asyncio, and concurrent requests share one task.
_trusted_refresh_task: Optional[asyncio.Task] = None

# Operator-location endpoint cache — the value only changes when an admin edits
# their profile, but every peer in the federation polls this during BFS (300+
# hits/min observed). Per-worker cache is enough.
_operator_location_cache: dict = {"data": None, "ts": 0}
_OPERATOR_LOCATION_TTL = 600  # 10 min


def _get_public_url(base_url: str) -> str:
    """Extract public HTTPS URL from a mTLS federation URL. Strip non-standard ports."""
    try:
        u = _urlparse(base_url)
        if not u.hostname or "." not in u.hostname:
            return ""
        return f"https://{u.hostname}"
    except Exception:
        return ""


def _union_registries(existing: list, fresh: list) -> list:
    """Union two registry lists by name. Fresh values replace existing when present
    (so updated coords propagate), but entries that only appear in `existing` are
    preserved — the cache never shrinks. Returns a deduped list, stable-ordered
    by (hop, name). Each entry is expected to carry name/url/public_url/hop and
    optionally lat/lng.
    """
    merged: dict = {}
    for r in existing or []:
        n = (r.get("name") or "").strip()
        if n:
            merged[n] = dict(r)
    for r in fresh or []:
        n = (r.get("name") or "").strip()
        if not n:
            continue
        prev = merged.get(n)
        if prev is None:
            merged[n] = dict(r)
        else:
            # Prefer fresh fields when non-None, else keep existing (so a BFS
            # run that didn't manage to fetch coords doesn't wipe them).
            combined = dict(prev)
            for k, v in r.items():
                if v is not None and v != "":
                    combined[k] = v
            # Always take the shortest hop we've ever seen (topology may have
            # learned a more direct path via a newer edge).
            if prev.get("hop") is not None and r.get("hop") is not None:
                combined["hop"] = min(prev["hop"], r["hop"])
            merged[n] = combined
    out = list(merged.values())
    out.sort(key=lambda x: (x.get("hop") or 99, x.get("name") or ""))
    return out


async def _load_trusted_cache_from_redis() -> tuple[list, float]:
    """Return (registries, ts) from Redis, or (in-memory-fallback, ts). Never raises."""
    try:
        from agentvault_registry.background_tasks.leader import get_redis
        r = await get_redis()
        if r is None:
            return list(_trusted_cache.get("registries") or []), float(_trusted_cache.get("ts") or 0)
        raw = await r.get(_TRUSTED_REDIS_KEY)
        if raw:
            data = _json.loads(raw)
            regs = data.get("registries") or []
            ts = float(data.get("ts") or 0)
            # §2026-07-26 — mirror every successful Redis read into the process-local
            # dict. Redis is authoritative, but `_trusted_cache` is the ONLY thing a
            # SYNC caller can read (it cannot await). Previously the mirror was written
            # solely by _save_trusted_cache_to_redis — i.e. only inside whichever worker
            # happened to run a BFS — so sync readers in every other worker of a 38-worker
            # gunicorn saw an EMPTY list and silently failed to resolve. That is what made
            # cross-registry receiver-balance sync fail ~23% of the time with
            # "[CROSS-REG] Could not resolve target registry URL". Warming the mirror on
            # every read makes the fallback correct in all workers and keeps it usable
            # through a Redis blip.
            _trusted_cache["registries"] = list(regs)
            _trusted_cache["ts"] = ts
            return regs, ts
    except Exception as e:
        logger.debug(f"[trusted-registries] Redis read failed, falling back to in-memory: {e}")
    return list(_trusted_cache.get("registries") or []), float(_trusted_cache.get("ts") or 0)


async def _save_trusted_cache_to_redis(registries: list, ts: float) -> None:
    """Persist the cache entry to Redis (TTL=_TRUSTED_TTL) and mirror in process memory."""
    _trusted_cache["registries"] = list(registries)
    _trusted_cache["ts"] = ts
    try:
        from agentvault_registry.background_tasks.leader import get_redis
        r = await get_redis()
        if r is None:
            return
        payload = _json.dumps({"registries": registries, "ts": ts})
        await r.set(_TRUSTED_REDIS_KEY, payload, ex=_TRUSTED_TTL)
    except Exception as e:
        logger.debug(f"[trusted-registries] Redis write failed (non-fatal): {e}")


async def _run_bfs_and_union(db: AsyncSession) -> list:
    """Run the full federation BFS and union the result into the shared cache.
    Returns the final (possibly unioned) registry list. Safe to call concurrently
    — the cache write is union-grow only, never regresses."""
    import asyncio

    now = _time.time()
    cached_regs, _ = await _load_trusted_cache_from_redis()

    # Start with direct peers from DB (hop 1)
    stmt = select(models.PeerRegistry).where(
        models.PeerRegistry.status == "ACTIVE"
    ).order_by(models.PeerRegistry.name)
    result = await db.execute(stmt)
    direct_peers = result.scalars().all()

    registries = []
    visited: set = set()
    queue: list = []

    for p in direct_peers:
        pub = _get_public_url(p.base_url)
        registries.append({"name": p.name, "url": p.base_url, "public_url": pub, "hop": 1,
                           "peer_type": getattr(p, "peer_type", None)})
        # BFS crawl target must preserve the federation port — Frame B and
        # some operator nginxes only listen on :8443, not 443. Use the raw
        # base_url for crawling; pub (port-stripped) is kept only for display.
        crawl_url = (p.base_url or "").rstrip('/')
        if crawl_url and crawl_url not in visited:
            queue.append({"url": crawl_url, "hop": 1})
            visited.add(crawl_url)

    # BFS: crawl each peer's /federation/peers/ to discover hop-2+ registries
    max_hops = 8  # covers deepest path: Seoul→Tokyo→Registry-A→SaoPaulo→BuenosAires→Santiago (hop 6+)
    try:
        async with _crawl_client(8) as client:   # CB-499: verified TLS, no redirects
            while queue:
                level = queue[:]
                queue.clear()
                to_fetch = [i for i in level if i["hop"] < max_hops]

                async def _crawl(item: dict):
                    for attempt in range(2):  # initial + 1 retry
                        try:
                            resp = await _crawl_get(client, item['url'], "/api/v1/federation/peers/")
                            if resp.status_code == 200:
                                data = resp.json()
                                return item, data.get("items") or (data if isinstance(data, list) else [])
                        except Exception:
                            if attempt == 0:
                                await asyncio.sleep(0.3)
                                continue
                    return item, []

                results = await asyncio.gather(*[_crawl(i) for i in to_fetch], return_exceptions=True)

                for res in results:
                    if isinstance(res, Exception):
                        continue
                    source, peers = res
                    for peer in peers:
                        raw_url = (peer.get("base_url", "") or "").rstrip('/')
                        pub = _get_public_url(raw_url)
                        # Key visited set + crawl queue on the RAW url (with
                        # port) so we can actually reach nginxes that don't
                        # listen on 443 (Frame-B, some operators).
                        if raw_url and raw_url not in visited:
                            visited.add(raw_url)
                            name = peer.get("name", "")
                            registries.append({
                                "name": name,
                                "url": raw_url,
                                "public_url": pub,
                                "hop": source["hop"] + 1,
                                "peer_type": peer.get("peer_type") or peer.get("type"),
                            })
                            queue.append({"url": raw_url, "hop": source["hop"] + 1})
    except Exception as e:
        logger.warning(f"[trusted-registries] BFS crawl error: {e}")

    # Resolve operator coordinates for each discovered registry (server-side, avoids browser SSL cert issues)
    async def _fetch_op_coords(item: dict, cl):
        pub = item.get("public_url", "")
        if not pub:
            return
        for attempt in range(2):  # initial + 1 retry
            try:
                resp = await _crawl_get(cl, pub, "/api/v1/agents/locations/operator")
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("lat") is not None and data.get("lng") is not None:
                        item["lat"] = data["lat"]
                        item["lng"] = data["lng"]
                return
            except Exception:
                if attempt == 0:
                    await asyncio.sleep(0.3)
                    continue

    try:
        async with _crawl_client(6) as coord_client:   # CB-499
            await asyncio.gather(*[_fetch_op_coords(r, coord_client) for r in registries])
    except Exception as e:
        logger.warning(f"[trusted-registries] coord fetch error: {e}")

    # 2026-05-02: also resolve each peer's SPIRE trust_domain via /federation/info.
    # Required so cross-registry-transfer can correctly set target_frame on
    # async cross-frame transfers when the local peer_registries doesn't have
    # a "frame"-type entry for the target operator's frame (the common case
    # for operator-to-operator calls). Without this, target_frame defaulted
    # to local_trust_domain and the receiver-frame reactor filtered the event
    # out, causing 100% saga refund.
    async def _fetch_trust_domain(item: dict, cl):
        pub = item.get("public_url", "")
        if not pub:
            return
        for attempt in range(2):
            try:
                resp = await _crawl_get(cl, pub, "/api/v1/federation/info")
                if resp.status_code == 200:
                    data = resp.json()
                    td = data.get("spiffe_trust_domain")
                    if td:
                        item["trust_domain"] = td
                return
            except Exception:
                if attempt == 0:
                    await asyncio.sleep(0.3)
                    continue

    try:
        async with _crawl_client(6) as info_client:   # CB-499
            await asyncio.gather(*[_fetch_trust_domain(r, info_client) for r in registries])
    except Exception as e:
        logger.warning(f"[trusted-registries] trust_domain fetch error: {e}")

    # Dedupe by name: the same peer can appear both from the local peer_registries
    # table (base_url with port 8443) and from a peer's /federation/peers/ listing
    # (with a different host-mapped port). The URLs differ, the visited set
    # correctly treats them as distinct nodes, but by the time we reach the
    # resolver they're the same registry. Keep the first occurrence (lowest hop).
    seen_names: set = set()
    deduped: list = []
    for r in registries:
        n = r.get("name") or ""
        if n and n in seen_names:
            continue
        seen_names.add(n)
        deduped.append(r)
    fresh_registries = deduped

    # 2026-05-30 — AUTHORITATIVE coord source: each peer's federation-synced
    # registry card (operator.latitude/longitude). Runs AFTER dedupe (names are
    # canonical here) and AFTER the live fetch, so it OVERRIDES the
    # unreachable/SNI-fallthrough live result for internal/sandbox hosts (the
    # live /agents/locations/operator fetch is empty for non-dotted hosts and
    # SNI-falls-through to the genesis frame, stacking every sandbox cloud-op on
    # Frame A's Freilassing). The card sync is the one channel that reliably
    # reaches the RIGHT peer. No-op on prod: once cards carry coords the value ==
    # the operator location == the live-fetch value; before that rollout, prod
    # cards lack coords so this is skipped and the live-fetch value stands.
    try:
        from sqlalchemy import select as _sel_cc
        _cc_rows = (await db.execute(
            _sel_cc(models.PeerRegistry.name, models.PeerRegistry.cached_registry_card)
            .where(models.PeerRegistry.status == "ACTIVE")
        )).all()
        _cc: dict = {}
        for _nm, _card in _cc_rows:
            if isinstance(_card, dict):
                _op = _card.get("operator") or {}
                if _op.get("latitude") is not None and _op.get("longitude") is not None:
                    _cc[(_nm or "").strip().lower()] = (_op["latitude"], _op["longitude"])
        if _cc:
            for _it in fresh_registries:
                _c = _cc.get((_it.get("name") or "").strip().lower())
                if _c:
                    _it["lat"], _it["lng"] = _c[0], _c[1]
    except Exception as _ce:
        logger.debug(f"[trusted-registries] card-coord override skipped: {_ce}")

    # Union with whatever is cached (shared via Redis). This ensures a partial
    # BFS can only ever add information, never remove it. If this run regressed
    # (lost nodes due to transient failures), we keep the previous richer view.
    unioned = _union_registries(cached_regs, fresh_registries)
    if len(unioned) >= len(cached_regs):
        await _save_trusted_cache_to_redis(unioned, now)
        out = unioned
    else:
        logger.warning(
            f"[trusted-registries] BFS regressed "
            f"({len(cached_regs)} → {len(fresh_registries)} fresh, "
            f"{len(unioned)} unioned), keeping previous cache"
        )
        out = cached_regs

    logger.info(
        f"[trusted-registries] Discovered {len(fresh_registries)} fresh "
        f"({len(direct_peers)} direct + {len(fresh_registries) - len(direct_peers)} via BFS); "
        f"served {len(out)} after union with cache"
    )
    return out


async def _compute_trusted_registries(db: AsyncSession) -> list:
    """Return the cached trusted-registry list, kicking off a non-blocking
    union-grow BFS refresh if the cache is older than _TRUSTED_REFRESH_INTERVAL.

    Caching strategy (2026-04-18 hardening):
      1. Cache is shared via Redis (`registry:topology:trusted`), mirrored in
         process memory. All uvicorn workers see the same topology, so one
         worker's complete BFS benefits every other.
      2. Cache entries union-grow: a fresh BFS run is merged with the existing
         cache — the cache never shrinks. A partial BFS cannot regress a
         previously complete topology.
      3. Requests don't block on BFS. The cached value is returned immediately;
         a background refresh fires asynchronously when the cache is stale,
         guarded by a per-process single-flight flag so we don't stampede
         federation peers under load.
      4. On empty-cache cold start, we do wait for BFS (no cached fallback
         available) — but subsequent requests return instantly.
    """
    import asyncio
    from agentvault_registry.core.peer_group import collapse_twins as _collapse_twins  # E11 (2026-09-13); function-level:
    # tests/test_globepop_allocator.py loads this module standalone, where a module-level relative import has no parent

    now = _time.time()
    cached_regs, cached_ts = await _load_trusted_cache_from_redis()
    cache_age = now - cached_ts

    # Cold start: nothing cached, synchronously run BFS so we have something to serve.
    if not cached_regs:
        cached_regs = await _run_bfs_and_union(db)
        return _collapse_twins(await _filter_locally_inactive_peers(db, cached_regs))

    # Cache is hot but stale-ish — return what we have, refresh in background.
    if cache_age > _TRUSTED_REFRESH_INTERVAL:
        global _trusted_refresh_task
        if _trusted_refresh_task is None or _trusted_refresh_task.done():
            async def _bg_refresh():
                try:
                    # Background task needs its own DB session — the request's
                    # session is closed as soon as the response returns.
                    from agentvault_registry.database import AsyncSessionLocal
                    async with AsyncSessionLocal() as bg_db:
                        await _run_bfs_and_union(bg_db)
                except Exception as e:
                    logger.debug(f"[trusted-registries] Background refresh failed: {e}")
            try:
                _trusted_refresh_task = asyncio.create_task(_bg_refresh())
            except RuntimeError:
                # No running event loop — skip background refresh
                _trusted_refresh_task = None

    # §pass66.2 (2026-05-23) — stale-peer filter. The Redis BFS cache union-grows
    # forever (never forgets a peer once discovered) but teardown only marks the
    # local peer_registries.status='INACTIVE'. Without this filter, torn-down
    # cloud-ops linger in the landing page + Mission Control + AgentWorld panel
    # forever, with a stale green/red probe state that confuses the aggregate
    # health UI. DB is authoritative; cache is a hint.
    # E11 (2026-09-13): one entry per registry identity. The cache union never regresses, so the fan-out's untyped
    # card-name ghost ("ASIA" beside the peer row "asia") outlived every roll and stack-health grouped the frame by it.
    return _collapse_twins(await _filter_locally_inactive_peers(db, cached_regs))


async def _filter_locally_inactive_peers(db: AsyncSession, regs: list) -> list:
    """§pass66.2 — drop cache entries that don't match an ACTIVE local peer_registries row.

    Handles BOTH stale-state classes:
      (a) explicit INACTIVE (peer_registries row exists with status='INACTIVE')
      (b) DELETED-but-cached (peer was hard-deleted from peer_registries but
          still lives in the in-memory `_trusted_cache` dict — Redis purge
          can't clear in-memory module state of running workers; only a
          process restart does)

    The (b) class was the residual leak that made `/stack-health` keep
    showing torn-down qatests on cloud-ops until container restart.

    Cheap one-query filter (single column SELECT, indexed on name). Returns
    the input list unchanged on DB failure (fail-open — don't blank the UI
    on a transient query error).

    Own-name protection: the local registry's REGISTRY_NAME / REGISTRY_FEDERATION_NAME
    / 'Local Registry' aliases are passed through unconditionally, because the
    local registry has no peer_registries row pointing at itself.
    """
    if not regs:
        return regs
    try:
        import os as _os_fp
        from sqlalchemy import select as _sel
        from .. import models as _models
        rows = (await db.execute(
            _sel(_models.PeerRegistry.name).where(_models.PeerRegistry.status == "ACTIVE")
        )).all()
        active_names = {(r[0] or "").strip().lower() for r in rows}
        # Always pass through our OWN identity (no peer_registries row for self).
        for env_key in ("REGISTRY_NAME", "REGISTRY_FEDERATION_NAME", "REGISTRY_DISPLAY_NAME"):
            v = (_os_fp.environ.get(env_key) or "").strip().lower()
            if v:
                active_names.add(v)
        active_names.add("local registry")  # backend's local-pseudo-peer key
        if not active_names:
            return regs
        filtered = [
            r for r in regs
            if (r.get("name") or "").strip().lower() in active_names
        ]
        dropped = len(regs) - len(filtered)
        if dropped > 0:
            dropped_names = [
                (r.get("name") or "?") for r in regs
                if (r.get("name") or "").strip().lower() not in active_names
            ]
            logger.info(
                f"[trusted-registries] filtered {dropped} stale peer(s) from cache view: {dropped_names}"
            )
        return filtered
    except Exception as e:
        logger.debug(f"[trusted-registries] stale-peer filter failed (non-fatal): {e}")
        return regs


@router.get(
    "/trusted-registries",
    summary="Get trusted federated registry URLs (internal; no auth)",
    description="Returns URLs of all reachable federated registries via BFS topology discovery. "
                "Direct peers (hop 1) come from the peer_registries table. Hop-2+ registries "
                "are discovered by crawling each peer's /federation/peers/ endpoint. "
                "Service agents call this on startup for cross-registry A2A payment trust.",
    tags=["Internal"],
)
async def get_trusted_registries(
    response: Response,
    db: AsyncSession = Depends(database.get_db),
):
    """
    Returns URLs of all reachable federation registries for cross-registry payment trust.
    Uses BFS topology discovery: direct peers + their peers + their peers (up to 3 hops).
    Cached for 5 minutes. Decentralized — no need to add every operator to peer_registries.
    """
    for k, v in _NO_BROWSER_CACHE.items():
        response.headers[k] = v
    import os

    registries = await _compute_trusted_registries(db)

    # Also include direct HTTP URLs from env vars (AV_PEER_REGISTRY_*_URL)
    env_peers = {}
    for key, val in os.environ.items():
        if key.startswith("AV_PEER_REGISTRY_") and key.endswith("_URL"):
            env_peers[val.rstrip("/")] = True

    # Build result — include hop + public_url + coords + trust_domain for
    # frontend topology views. trust_domain (added 2026-05-05 audit Theme #1)
    # is the authoritative frame identifier; lets the frontend stop deriving
    # frame from URL substring (the bug class behind today's Bavaria stacking
    # / dedup / wrong-color iterations).
    result_list = []
    for r in registries:
        entry = {
            "name": r["name"],
            "url": r["url"],
            "public_url": r.get("public_url", ""),
            "hop": r.get("hop", 1),
            # §RESIDUES C1 (2026-09-13): the tile grouping needs to know a FRAME from an operator
            "peer_type": r.get("peer_type"),
        }
        if r.get("lat") is not None:
            entry["lat"] = r["lat"]
        if r.get("lng") is not None:
            entry["lng"] = r["lng"]
        if r.get("trust_domain"):
            entry["trust_domain"] = r["trust_domain"]
        result_list.append(entry)
    known_urls = {r["url"].rstrip("/") for r in result_list}
    for url in env_peers:
        if url not in known_urls:
            # Only add env-var peers that have a resolvable public URL
            pub = _get_public_url(url)
            if pub:
                result_list.append({"name": "peer", "url": url, "public_url": pub, "hop": 0})

    return {"registries": result_list}


@router.put(
    "/me",
    summary="Update authenticated developer's location",
    description="Set the developer's location. Optionally propagates to all their "
                "agents that do not already have explicit coordinates.",
    # §pass56 PR-5: tags= dropped; main.py:include_router supplies "AgentWorld"
)
async def update_my_location(
    location_data: dict,
    db: AsyncSession = Depends(database.get_db),
    current_developer: models.Developer = Security(get_current_developer),
):
    """
    Update lat/lng for the authenticated developer.

    Body: {
      "latitude": 50.11,
      "longitude": 8.68,
      "location_label": "Frankfurt, DE",
      "update_agents": true       <- optional, default true
    }
    """
    lat = location_data.get("latitude")
    lng = location_data.get("longitude")
    label = location_data.get("location_label", "")
    update_agents = location_data.get("update_agents", True)

    if lat is None or lng is None:
        raise HTTPException(status_code=422, detail="latitude and longitude are required")

    if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
        raise HTTPException(status_code=422, detail="Invalid coordinate range")

    # Phase E.2 (2026-05-26): split into two commits to fix the silent NO-OP
    # class. Previously a single commit at the end meant slow agent
    # propagation (5834 rows on the sandbox commander) blew past the
    # client-side HTTPX_TIMEOUT_MUTATE=30s in the MCP wrapper; the resulting
    # cancellation rolled back the WHOLE transaction including the developer
    # row. Now we commit the developer's own location first (fast,
    # essential) and propagate to agents in a separate best-effort block.
    # Agent propagation failure no longer loses the developer's update.
    current_developer.latitude = lat
    current_developer.longitude = lng
    current_developer.location_label = label
    await db.commit()

    agents_updated = 0
    if update_agents:
        try:
            stmt = (
                select(models.Agent)
                .where(
                    models.Agent.creator_developer_id == current_developer.id,
                    models.Agent.latitude == None,  # noqa: E711
                )
            )
            result = await db.execute(stmt)
            agents = result.scalars().all()
            for agent in agents:
                agent.latitude = lat
                agent.longitude = lng
                agent.location_label = label
            agents_updated = len(agents)
            await db.commit()
            logger.info(
                f"[AgentWorld] Updated location for developer {current_developer.id} "
                f"and {agents_updated} agents"
            )
        except Exception as e:
            # Best-effort: developer location is already committed; agent
            # propagation can be retried later by the operator. Surface the
            # error in logs but do NOT fail the request.
            logger.warning(
                f"[AgentWorld] developer={current_developer.id} agent "
                f"propagation failed after dev commit: {e!r}"
            )
            try:
                await db.rollback()
            except Exception:
                pass

    return {"success": True, "updated_agents": agents_updated}
