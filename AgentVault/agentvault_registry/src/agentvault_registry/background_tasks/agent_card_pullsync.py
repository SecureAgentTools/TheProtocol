"""Option C Phase 3 — agent_card_pullsync worker (§pass36).

Pulls each native agent's `/.well-known/agent-card.json` and reconciles it
with the registry's stored `card_data`. Agent owns identity/transport/auth/
marketing; registry owns federation_metadata + flare. Agent-canonical fields
overwrite from the pull; registry-canonical fields are preserved.

Per A2A v1.0 §4.1.2:
  GET https://<agent-host>/.well-known/agent-card.json
  with If-None-Match: <last-etag> if known.

Cadence: 6h (env `AGENT_CARD_PULLSYNC_INTERVAL_SEC`, default 21600).
Master kill: env `AGENT_CARD_PULLSYNC_ENABLED` (default true).

Scope (per plan §12.6):
  - Only native cards (agent_did IS NOT NULL AND federation_metadata.source_registry IS NULL).
  - Skip URLs pointing to localhost / docker-internal / IP literals (plan §12.8).
  - One worker per registry; leader-elected via Redis (BackgroundWorker base).

On 304: update last_pulled_at only.
On 200 + drift: merge (agent fields overwrite, registry fields preserved) +
                emit `AgentCardPulled` with `{drift: true, fields: [...]}`.
On 200 + no drift: update last_pulled_at + last_pulled_etag only.
On 4xx/5xx/timeout: log + increment Prom counter; never replace stored card.
"""
import asyncio
import datetime
import hashlib
import ipaddress
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

import httpx
from sqlalchemy import func, select, update
from sqlalchemy import text as _text
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models
from ..database import get_db_context
from ..event_emitter import get_event_emitter
from ..services.a2a_v1.compat import canonicalize_card_data
from ._worker_base import BackgroundWorker

logger = logging.getLogger(__name__)


# ─── Prometheus metrics (lazy, best-effort) ──────────────────────────────────
try:
    from prometheus_client import Counter as _PCounter, Gauge as _PGauge

    PULLSYNC_CYCLE_TOTAL = _PCounter(
        "agent_card_pullsync_cycle_total",
        "agent_card_pullsync cycles run (leader only)",
        labelnames=["registry_id"],
    )
    PULLSYNC_PULLS_TOTAL = _PCounter(
        "agent_card_pullsync_pulls_total",
        "Pull attempts by HTTP outcome",
        labelnames=["registry_id", "outcome"],  # outcome: 200 | 304 | 4xx | 5xx | timeout | skipped
    )
    PULLSYNC_DRIFT_DETECTED_TOTAL = _PCounter(
        "agent_card_pullsync_drift_detected_total",
        "Drift detected — per agent-canonical field whose value changed",
        labelnames=["registry_id", "field"],
    )
    PULLSYNC_LAST_CYCLE_DURATION_MS = _PGauge(
        "agent_card_pullsync_last_cycle_duration_ms",
        "Duration of the most recent pull-sync cycle in ms",
        labelnames=["registry_id"],
        multiprocess_mode="max",
    )
    PULLSYNC_PENDING_AGENTS = _PGauge(
        "agent_card_pullsync_pending_agents",
        "Native agents that are eligible for pull-sync (computed on each cycle)",
        labelnames=["registry_id"],
        multiprocess_mode="max",
    )
    # §CARDPULLTICK (2026-08-29): the HONEST liveness signal. The cycle counter
    # is structurally blind twice over — increase() cannot see a counter that
    # reboots to the same value (roll weeks park it at 1 -> gap -> 1), and a
    # winner process whose emission is lost leaves only the losers' side of the
    # race on the graph (measured: a full night of not_acquired with zero
    # acquired while op logs later proved the ticks run to the second). A
    # max-mode unixtime gauge answers the only question the alert ever asked:
    # WHEN did a cycle last complete anywhere.
    PULLSYNC_LAST_CYCLE_UNIXTIME = _PGauge(
        "agent_card_pullsync_last_cycle_unixtime",
        "Unix time of the most recent completed pull-sync cycle (leader only)",
        labelnames=["registry_id"],
        multiprocess_mode="max",
    )
except Exception:  # pragma: no cover
    PULLSYNC_CYCLE_TOTAL = None
    PULLSYNC_PULLS_TOTAL = None
    PULLSYNC_DRIFT_DETECTED_TOTAL = None
    PULLSYNC_LAST_CYCLE_DURATION_MS = None
    PULLSYNC_PENDING_AGENTS = None
    PULLSYNC_LAST_CYCLE_UNIXTIME = None


_REGISTRY_ID_LABEL = os.getenv("REGISTRY_NAME", "registry-a")
_INTERVAL_SEC = int(os.environ.get("AGENT_CARD_PULLSYNC_INTERVAL_SEC", "21600"))
_FETCH_TIMEOUT_SEC = float(os.environ.get("AGENT_CARD_PULLSYNC_FETCH_TIMEOUT_SEC", "10.0"))
_PER_CYCLE_LIMIT = int(os.environ.get("AGENT_CARD_PULLSYNC_PER_CYCLE_LIMIT", "100"))
# §FEDSYNCTRUTH (2026-09-03) — the cursor. Parallel fetches per cycle (each fetch is one HTTP GET with
# a 10 s ceiling; 8 in flight keeps a 100-card cycle under ~2 min even when every host is dead).
_CONCURRENCY = max(1, int(os.environ.get("AGENT_CARD_PULLSYNC_CONCURRENCY", "8")))
# Retry backoff for a card whose last attempt failed: interval × 2^failures, capped at a week. A live
# card (200/304) resets to 0 and is asked every cycle; a dead hostname is asked weekly, not every 6 h.
_BACKOFF_CAP_SEC = int(os.environ.get("AGENT_CARD_PULLSYNC_BACKOFF_CAP_SEC", str(7 * 24 * 3600)))
# The SQL twin of `_is_skippable_host` for the candidate query: hosts the registry can never reach
# (loopback, RFC1918, bare IPv4, single-label docker names) are not candidates at all, so they cost
# nothing and never occupy a slot. `_is_skippable_host` stays the authority for what slips through.
# Special-use TLDs (RFC 6761 / 6762) never resolve on any public DNS: `.local` is mDNS; `.invalid`,
# `.test`, `.example`, `.localhost` are reserved. Every spawned sim child carries `sub-<uuid>.agents.local`
# (3,915 of registry-a's 4,094 candidates on 2026-09-03) and asking one is a guaranteed DNS error.
_RESERVED_TLDS = frozenset({"local", "invalid", "test", "example", "localhost"})
_LOOPBACK_SQL_ALT = r"localhost|127\.|0\.0\.0\.0|\[::1\]|host\.docker\.internal"
_PRIVATE_SQL_ALT = (
    r"10\.|172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.|"
    r"[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+|"
    r"[a-z0-9_-]+(:[0-9]+)?(/|$)"
)
_RESERVED_TLD_SQL_ALT = r"[a-z0-9._-]+\.(local|invalid|test|example|localhost)(:[0-9]+)?(/|$)"
_INTERNAL_URL_SQL_REGEX = "://(" + "|".join([_LOOPBACK_SQL_ALT, _PRIVATE_SQL_ALT, _RESERVED_TLD_SQL_ALT]) + ")"
_SANDBOX_INTERNAL_URL_SQL_REGEX = "://(" + "|".join([_LOOPBACK_SQL_ALT, _RESERVED_TLD_SQL_ALT]) + ")"


def _internal_url_sql_regex() -> str:
    """The SQL twin of `_is_skippable_host`, chosen at query time and mode-aware like it: in sandbox
    mode IPv4 literals and single-label docker names are reachable (§pass47 B8) and stay candidates."""
    return _SANDBOX_INTERNAL_URL_SQL_REGEX if _is_sandbox_mode() else _INTERNAL_URL_SQL_REGEX


# §ALERTFIX (2026-10-07, his word "yes fix"): the registry's OWN hosts are not candidates. A card whose interface URL
# sits on this registry's public host is a card the registry hosts itself (canaries, the treasury agent, service and
# showcase agents served under paths). `_well_known_url_for` keeps only scheme+host, so every one of them resolved to
# ONE root document that cannot describe any one of them (EU: 26 cards, one 404 at
# https://eu.theprotocol.cloud/.well-known/agent-card.json), each sat in the weekly backoff, and every retry was a 4xx
# the pull alerts counted. The registry is the source of truth for those cards; asking itself is noise. Own hosts =
# the hosts of its URL settings, plus AGENT_CARD_PULLSYNC_OWN_HOSTS (comma-separated) for any further alias.
_OWN_HOST_ENV_KEYS = ("PUBLIC_URL", "BASE_URL", "PUBLIC_UI_URL", "PUBLIC_BASE_URL", "FEDERATION_BASE_URL")
_HOSTNAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")


def _own_hosts() -> frozenset:
    """The public hostnames this registry answers on, read per call (the env is fixed for the process; tests patch
    it). Anything that is not a dotted hostname is dropped, so the SQL twin can splice the names into a regex."""
    hosts = set()
    for key in _OWN_HOST_ENV_KEYS:
        try:
            host = (urlparse(os.environ.get(key) or "").hostname or "").lower()
        except Exception:
            host = ""
        if host:
            hosts.add(host)
    for host in (os.environ.get("AGENT_CARD_PULLSYNC_OWN_HOSTS") or "").split(","):
        if host.strip():
            hosts.add(host.strip().lower())
    return frozenset(h for h in hosts if _HOSTNAME_RE.match(h))


def _own_host_sql_regex() -> Optional[str]:
    """The SQL twin of the own-host half of `_is_skippable_host`; None (no filter) when no host is known."""
    hosts = sorted(_own_hosts())
    if not hosts:
        return None
    return r"^[a-z][a-z0-9+.-]*://(" + "|".join(h.replace(".", r"\.") for h in hosts) + r")(:[0-9]+)?([/?#]|$)"
# The candidate URL is the SAME field `_well_known_url_for` reads — supportedInterfaces[0].url and
# nothing else (a legacy `card_data.url` is never pulled by this worker; measured on frame-c 2026-09-03:
# 125 url-only natives, every one an `.invalid` probe fixture or a canary card). A row is a candidate
# only when that field carries a scheme and a host, so an interface-less card never occupies a slot —
# bake 1 handed 97 of 100 slots to such cards, which the Python rule could only stamp `skipped`.
_CANDIDATE_URL_SQL_EXPR = "coalesce(card_data->'supportedInterfaces'->0->>'url', '')"
_SCHEME_HOST_SQL_REGEX = r"^[a-z][a-z0-9+.-]*://[^/?#]+"


def _backoff_seconds(failures: int) -> int:
    """Seconds to wait after `failures` consecutive failed attempts (interval × 2^n, capped)."""
    n = max(0, int(failures or 0))
    try:
        return int(min(_INTERVAL_SEC * (2 ** n), _BACKOFF_CAP_SEC))
    except OverflowError:  # pragma: no cover
        return _BACKOFF_CAP_SEC


def _stamp_attempt(row: Any, status: str, ok: bool, now: Optional[datetime.datetime] = None) -> None:
    """Record an attempt on the row — every outcome moves the cursor; only success resets the backoff."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    row.last_pull_attempt_at = now
    row.last_pull_status = str(status)[:16]
    row.pull_failures = 0 if ok else int(getattr(row, "pull_failures", 0) or 0) + 1

# Fields the agent owns (replaced from the well-known card).
# ⚠ This constant is DOCUMENTATION, not the rule: `_merge_pulled_card` never reads it,
# and its previous comment claimed the opposite of what the code does — anything not in
# `_REGISTRY_OWNED_FIELDS` is DROPPED when the agent stops publishing it, not preserved.
# The two sets that actually bind are `_REGISTRY_OWNED_FIELDS` and `_OWNER_SET_FIELDS`.
_AGENT_OWNED_FIELDS = frozenset({
    "protocolVersion",
    "schemaVersion",  # v0.3 alias — kept until 6-mo dual-shape window closes
    "humanReadableId",
    "agentVersion",
    "name",
    "description",
    "url",
    "preferredTransport",
    "authSchemes",
    "supportedInterfaces",
    "securitySchemes",
    "security",
    "extensions",
    "provider",
    "capabilities",
    "skills",
    "tags",
    "privacyPolicyUrl",
    "termsOfServiceUrl",
    "iconUrl",
    "lastUpdated",
    "signatures",  # JWS (Phase 9)
})

# Fields the registry owns — MUST survive a pull-sync merge intact.
_REGISTRY_OWNED_FIELDS = frozenset({
    "federation_metadata",
    "flare",
    "last_pulled_at",
    "last_pulled_etag",
})

# ─── §MARKSURFACES (2026-09-10) — fields the OWNER sets through the console ──────────
#
# 🔴 THIS IS WHAT KEEPS THE AGENT LOGO, and it is the agent-side twin of
# `merge_operator_card_patch`'s block of the same name on the registry-card side.
#
# His report: *"make so the set logo never gets lost on saving an upgraded agentcard
# when updating the agentcard. this is a bug i noticed on agents same as registry cards
# had."* Reproduced 2026-09-10 in the running V0301 image against a real stored card:
# `card_data.iconUrl` was set through the console (MyAgents.vue -> PUT /agent-cards/{did}),
# the agent shipped an upgraded well-known card that — like every agent card — did not
# carry that key, and the merge below classified it `iconUrl:removed` and dropped it.
# `flare` survived (registry-owned); the logo did not. Measured on registry-a the same
# day: 0 of 15,571 cards hold a non-null icon, which is what a field that cannot survive
# its own worker looks like from the outside.
#
# The rule, and why it is not simply "registry-owned": `iconUrl` is a legitimate A2A
# field an agent MAY publish, so the agent's value must still win when the agent
# actually publishes one. What is wrong is reading SILENCE as deletion. An owner-set
# field is therefore:
#     agent publishes a value      -> the agent's value wins (it is the agent's card)
#     agent publishes nothing      -> the stored owner-set value is CARRIED FORWARD
#     agent publishes null/""      -> treated as silence, the stored value survives;
#                                     clearing an icon is done through the console,
#                                     which sends an explicit null the CRUD honours
# and it is never reported as `:removed`, because nobody removed it.
_OWNER_SET_FIELDS = frozenset({
    "iconUrl",
    # Defensive: `canonicalize_card_data` normalises to camelCase, but a card written
    # before that ran can still hold the snake_case spelling. A rule that protects one
    # spelling of a two-spelling field protects nothing (§DISCREFINE's "two legal places").
    "icon_url",
})


def _is_blank(v: Any) -> bool:
    """Absent, null, or an empty/whitespace string — all of them mean 'said nothing'."""
    return v is None or (isinstance(v, str) and not v.strip())


# ─── Helpers ────────────────────────────────────────────────────────────────


def _is_sandbox_mode() -> bool:
    """§pass47 B8 — true when running on the sandbox stack.

    Honored signals (any true → sandbox):
      - explicit override:  SANDBOX_MODE=true / 1 / yes
      - environment label:  CC_TARGET_ENVIRONMENT=sandbox
    """
    if (os.getenv("SANDBOX_MODE") or "").lower() in ("1", "true", "yes"):
        return True
    if (os.getenv("CC_TARGET_ENVIRONMENT") or "").lower() == "sandbox":
        return True
    return False


def reserved_tld_of(url: str) -> Optional[str]:
    """The special-use TLD (RFC 6761 / 6762) a URL's host ends in, or None. One rule for the pull-sync's skip and for
    create_agent's refusal (V0650 (e)): the registry never asks such a host for a card, so it never builds a placeholder
    card that waits on one either."""
    try:
        host = (urlparse(str(url)).hostname or "").lower()
    except Exception:
        return None
    if not host:
        return None
    tld = host.rsplit(".", 1)[-1]
    return tld if tld in _RESERVED_TLDS else None


def _is_skippable_host(url: str) -> bool:
    """Skip URLs we can't reach from inside the registry container (plan §12.8).

    §pass47 B8 — in sandbox mode, allow IPv4 literals and single-label container
    hostnames so bootstrap E2E tests can register throwaway HTTP servers attached
    to the docker network (e.g. `temp-test-agent:8080`). Loopback addresses stay
    skipped even in sandbox — they would never be reachable from the registry
    container.
    """
    try:
        p = urlparse(url)
        host = (p.hostname or "").lower()
    except Exception:
        return True
    if not host:
        return True
    if host in ("localhost", "127.0.0.1", "::1", "host.docker.internal"):
        return True
    # A special-use TLD cannot resolve in ANY mode (RFC 6761 / 6762) — see _RESERVED_TLDS.
    if reserved_tld_of(url):
        return True
    # §ALERTFIX: a card on this registry's own host is a card it hosts itself (see _own_hosts)
    if host in _own_hosts():
        return True
    sandbox = _is_sandbox_mode()
    # IPv4 literal (single-host docker network endpoints — almost certainly
    # internal). Public agents must use a DNS name.
    if re.match(r"^\d{1,3}(?:\.\d{1,3}){3}$", host):
        return not sandbox
    # Single-label container names (no dots). These are docker DNS aliases —
    # reachable inside the network but never resolvable to a public well-known.
    if "." not in host:
        return not sandbox
    return False


# --- §SSRFGUARD (2026-09-16, his word "1-3 approved") ---------------------------------------------------------
# `_is_skippable_host` asks about the url a card NAMES. Both fetch sites used to build their client with
# `follow_redirects=True`, so a host the registry was pointed at could answer 302 and send the fetch to a loopback or
# private address, and `_merge_pulled_card` put that body into a publicly readable card (measured on the image the
# fleet runs, httpx 0.27.0, in an isolated container). The redirects are ours now: every hop is asked, the chain is
# bounded, a body has to look like a card before it is merged, and a refusal is an outcome with a name. Reported by a
# researcher on 2026-09-12; the redirect half is the half that reaches inside. tests/test_card_fetch_ssrf_guard.py.
_MAX_REDIRECTS = int(os.environ.get("AGENT_CARD_PULLSYNC_MAX_REDIRECTS", "3"))
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class FetchRefused(Exception):
    """A hop the fetcher will not follow (an internal target), or more hops than the cap allows."""


def _redirect_hop_ok(url: str) -> bool:
    """A redirect hop is judged more strictly than the url a card names: an address literal that is loopback, private,
    link-local, reserved, multicast or unspecified is refused in EVERY mode, sandbox included, because no agent's
    public well-known lives there. `_is_skippable_host` decides the rest (names, single labels, reserved TLDs)."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    if not host:
        return False
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        addr = None
    if addr is not None and (addr.is_loopback or addr.is_private or addr.is_link_local
                             or addr.is_reserved or addr.is_multicast or addr.is_unspecified):
        return False
    return not _is_skippable_host(url)


async def fetch_agent_card(client: httpx.AsyncClient, url: str, headers: Dict[str, str]) -> httpx.Response:
    """GET an agent's well-known, following redirects ourselves so every hop is asked. Raises FetchRefused."""
    current = url
    for _ in range(_MAX_REDIRECTS + 1):
        resp = await client.get(current, headers=headers, follow_redirects=False)
        if resp.status_code not in _REDIRECT_STATUSES:
            return resp
        location = resp.headers.get("location")
        if not location:
            return resp
        nxt = str(resp.url.join(location))
        if not _redirect_hop_ok(nxt):
            raise FetchRefused(f"redirect to a host the fetcher does not follow: {urlparse(nxt).hostname}")
        current = nxt
    raise FetchRefused(f"more than {_MAX_REDIRECTS} redirects from {urlparse(url).hostname}")


def _looks_like_agent_card(fresh: Any) -> bool:
    """A fetched document is merged only when it looks like an agent card: an object with a string `name` that also
    declares an endpoint or a version. An internal service's JSON answers none of that, so it never reaches a card."""
    if not isinstance(fresh, dict) or not isinstance(fresh.get("name"), str):
        return False
    return any(k in fresh for k in ("supportedInterfaces", "url", "protocolVersion", "schemaVersion"))


def _well_known_url_for(card_data: Dict[str, Any]) -> Optional[str]:
    """Derive the agent's well-known URL from its card_data.

    Uses supportedInterfaces[0].url's scheme+host, then appends the canonical
    `/.well-known/agent-card.json` path. The interface URL itself usually
    points to an a2a endpoint like https://veridian.theprotocol.cloud/api/witness;
    we want https://veridian.theprotocol.cloud/.well-known/agent-card.json.
    """
    try:
        iface = (card_data.get("supportedInterfaces") or [])
        if not iface or not isinstance(iface[0], dict):
            return None
        url = iface[0].get("url")
        if not isinstance(url, str):
            return None
        p = urlparse(url)
        if not p.scheme or not p.hostname:
            return None
        if _is_skippable_host(url):
            return None
        port_suffix = f":{p.port}" if p.port else ""
        return f"{p.scheme}://{p.hostname}{port_suffix}/.well-known/agent-card.json"
    except Exception:
        return None


def _merge_pulled_card(
    stored: Dict[str, Any], fresh: Dict[str, Any]
) -> Tuple[Dict[str, Any], List[str]]:
    """Merge agent's fresh well-known card into the stored card_data.

    Per plan §3.1 ownership split + §12.5 preservation contract:
      - Agent-owned fields: overwrite from `fresh`.
      - Registry-owned fields (`federation_metadata`, `flare`, `last_pulled_*`):
        always preserved from `stored`.
      - Owner-set fields (`_OWNER_SET_FIELDS`, today the logo): the agent's value wins
        when the agent publishes one; the stored value is CARRIED FORWARD when it does
        not, because silence from an agent about a field the console writes is not
        evidence the owner deleted it (§MARKSURFACES).
      - Any other field in `stored` but absent from `fresh`:
        DROPPED — the agent removed them, that's the canonical state.

      - The home extensions (bond, enforcement, listing): dropped from `fresh` before
        anything is compared. An SDK agent republishes the card-export, which states them,
        and a copy stored here would outlive the state it described (§TWOAGENT #10).

    Returns: (merged_card_data, drifted_field_names)
    """
    from ..services.home_extensions import strip_home_extensions
    fresh = strip_home_extensions(fresh)
    merged: Dict[str, Any] = {}
    drifted: List[str] = []

    # 1. Take every agent-owned field from `fresh`.
    for key, fresh_val in fresh.items():
        if key in _REGISTRY_OWNED_FIELDS:
            # Defensive: agent should NEVER emit these; if it does, ignore.
            continue
        merged[key] = fresh_val
        stored_val = stored.get(key)
        if stored_val != fresh_val:
            drifted.append(key)

    # 2. Preserve registry-owned fields exactly from `stored`.
    for key in _REGISTRY_OWNED_FIELDS:
        if key in stored:
            merged[key] = stored[key]

    # 2b. §MARKSURFACES — carry an owner-set field forward when the agent said nothing
    #     about it. This is the whole fix for "the set logo gets lost on an upgrade":
    #     the agent's own value still wins whenever it publishes one, so this only ever
    #     restores what the console put there and the agent never had an opinion on.
    preserved_owner_set: List[str] = []
    for key in _OWNER_SET_FIELDS:
        if _is_blank(merged.get(key)) and not _is_blank(stored.get(key)):
            merged[key] = stored[key]
            preserved_owner_set.append(key)

    # 3. Detect fields that were in `stored` but the agent no longer publishes.
    #    Treat them as drifted ("removed"), don't carry them forward (unless
    #    registry-owned or owner-set, handled above). A field we deliberately kept is
    #    NOT a removal, and saying so would train a reader to ignore the drift feed
    #    (§DRIFTSKIP: a deliberate skip its alarm does not know about is noise).
    for key in stored:
        if key in _REGISTRY_OWNED_FIELDS or key in preserved_owner_set:
            continue
        if key not in fresh:
            drifted.append(f"{key}:removed")

    return merged, drifted


# The row's `name` and `description` are copies of the card (models.AgentCard: "extracted fields for easier
# querying"), and they are what discovery lists, searches and filters on. Measured 2026-10-25 on EU: all eleven
# sovereign agents listed the role line the onboarding script minted them with (Greedy Gregory "Autonomous yield
# optimizer."), while the pulls had long since written each agent's own text into card_data; an agent onboarded
# through the stub keeps "Awaiting first pull-sync ..." as its listed text the same way (agentvault2-66).
# Both columns carry a btree index, whose entries cannot exceed about 2.7 KB, and a cycle commits all its rows at
# once, so a copy is bounded: one long card must not fail every other card's pull.
_LISTED_TEXT_MAX_BYTES = 2000


def _listed_text(val: Any) -> Optional[str]:
    """The card's value as a listed column holds it: None for a blank or non-string value (a card that says nothing
    leaves the column alone), else the text, cut at a character boundary to _LISTED_TEXT_MAX_BYTES with an ellipsis."""
    if not isinstance(val, str) or not val.strip():
        return None
    raw = val.encode("utf-8")
    if len(raw) <= _LISTED_TEXT_MAX_BYTES:
        return val
    return raw[: _LISTED_TEXT_MAX_BYTES - 3].decode("utf-8", "ignore").rstrip() + "\u2026"


def _sync_listed_columns(row: Any, card: Any) -> List[str]:
    """Carry the card's name and description into the row's listed columns. Returns the columns it changed."""
    changed: List[str] = []
    if not isinstance(card, dict):
        return changed
    for col in ("name", "description"):
        want = _listed_text(card.get(col))
        if want is not None and getattr(row, col, None) != want:
            setattr(row, col, want)
            changed.append(col)
    return changed


async def _emit_drift_event(
    agent_did: str,
    drifted_fields: List[str],
    new_etag: Optional[str],
) -> None:
    """Audit-trail emit. Skipped in projection per migration 0062 policy."""
    try:
        emitter = get_event_emitter()
        if emitter is None:
            return
        await emitter.emit(
            event_type="AgentCardPulled",
            aggregate_id=agent_did,
            aggregate_type="AgentCard",
            data={
                "agent_did": agent_did,
                "registry_id": _REGISTRY_ID_LABEL,
                "drift": True,
                "drifted_fields": drifted_fields,
                "new_etag": new_etag,
                "detected_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            },
        )
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[AgentCardPullSync] emit AgentCardPulled failed: {e}")


def _is_native_card(card_data: Optional[Dict[str, Any]]) -> bool:
    """Native = no `federation_metadata.source_registry` (synced cards have one)."""
    if not card_data or not isinstance(card_data, dict):
        return True
    fed = card_data.get("federation_metadata")
    if not isinstance(fed, dict):
        return True
    return not bool(fed.get("source_registry"))


# ─── In-memory cycle stats (consumed by /admin/.../status) ───────────────────


_LAST_STATS: Dict[str, Any] = {
    "candidates": 0,
    "fetched_200": 0,
    "fetched_304": 0,
    "fetched_4xx": 0,
    "fetched_5xx": 0,
    "fetched_timeout": 0,
    "skipped_internal": 0,
    "refused": 0,  # §SSRFGUARD: a hop we would not follow, or a body that is no card
    "drift_agents": 0,
    "drift_field_counts": {},  # field name -> int
    "listed_synced": 0,  # rows whose listed name/description were carried from their card
    "errors": 0,
    "last_pull_per_agent": {},  # agent_did -> {url, status, etag, ts}
}


def _bump_outcome(stats: Dict[str, Any], outcome: str) -> None:
    key = f"fetched_{outcome}" if outcome.isdigit() or outcome == "timeout" else f"fetched_{outcome}"
    stats[key] = stats.get(key, 0) + 1


# ─── Worker class ────────────────────────────────────────────────────────────


def _candidate_stmt():
    """The candidate query (§FEDSYNCTRUTH), built here so a test can compile and pin its SHAPE without a
    database: the ONE candidate field, the scheme+host and internal-host filters, the backoff window
    and the priority. `_fetch_candidates` only executes it."""
    _url_expr = _CANDIDATE_URL_SQL_EXPR
    stmt = (
        select(models.AgentCard)
        .where(models.AgentCard.is_active.is_(True))
        .where(models.AgentCard.agent_did.is_not(None))
        .where(_text(
            "(card_data->'federation_metadata'->>'source_registry') IS NULL"
        ))
        .where(_text(f"{_url_expr} ~* :scheme_re").bindparams(scheme_re=_SCHEME_HOST_SQL_REGEX))
        .where(_text(f"{_url_expr} !~* :internal_re").bindparams(internal_re=_internal_url_sql_regex()))
        .where(_text(
            "(last_pull_attempt_at IS NULL OR last_pull_attempt_at < now() - make_interval(secs => "
            "least(:interval_sec * power(2, coalesce(pull_failures, 0)), :cap_sec)))"
        ).bindparams(interval_sec=float(_INTERVAL_SEC), cap_sec=float(_BACKOFF_CAP_SEC)))
        # Tiebreaker on `created_at, id` so consecutive cycles cover the
        # whole never-attempted set deterministically (not random).
        .order_by(
            # never-attempted and LIVE cards (pull_failures = 0) outrank cards in backoff, so a dead
            # population whose weekly retries exceed the slot budget can never starve the live one
            # (registry-a 2026-09-03: ~4,100 dead sim hostnames vs ~30 live cards, 100 slots a cycle)
            func.coalesce(models.AgentCard.pull_failures, 0).asc(),
            models.AgentCard.last_pull_attempt_at.asc().nullsfirst(),
            models.AgentCard.last_pulled_at.asc().nullsfirst(),
            models.AgentCard.created_at.asc(),
            models.AgentCard.id.asc(),
        )
        .limit(_PER_CYCLE_LIMIT)
    )
    own_re = _own_host_sql_regex()
    if own_re:   # §ALERTFIX: the registry's own hosts never take a slot (the Python rule stays the authority)
        stmt = stmt.where(_text(f"{_url_expr} !~* :own_re").bindparams(own_re=own_re))
    return stmt


class AgentCardPullSync(BackgroundWorker):
    """Periodic pull-sync of native agents' well-known cards (§pass36 Phase 3).

    Runs on every registry (registry-a + frame-b-registry + each cloud-op).
    Leader-elected via Redis (BackgroundWorker base).
    Master kill: env `AGENT_CARD_PULLSYNC_ENABLED=false`.
    """

    worker_id = "agent_card_pullsync"
    leader_key = "agent_card_pullsync"
    interval_sec = _INTERVAL_SEC
    cold_start_delay_sec = 30  # let registry-a's other workers settle first

    def _should_run(self) -> bool:
        return os.environ.get("AGENT_CARD_PULLSYNC_ENABLED", "true").lower() == "true"

    async def _cycle_once(self) -> None:
        t0 = time.time()

        if PULLSYNC_CYCLE_TOTAL is not None:
            try:
                PULLSYNC_CYCLE_TOTAL.labels(registry_id=_REGISTRY_ID_LABEL).inc()
            except Exception:
                pass
        if PULLSYNC_LAST_CYCLE_UNIXTIME is not None:
            try:
                PULLSYNC_LAST_CYCLE_UNIXTIME.labels(
                    registry_id=_REGISTRY_ID_LABEL
                ).set(time.time())
            except Exception:
                pass

        # Reset per-cycle counters (lifetime totals stay in Prom counters).
        stats: Dict[str, Any] = {
            "candidates": 0,
            "fetched_200": 0,
            "fetched_304": 0,
            "fetched_4xx": 0,
            "fetched_5xx": 0,
            "fetched_timeout": 0,
            "skipped_internal": 0,
            "refused": 0,
            "drift_agents": 0,
            "drift_field_counts": {},
            "listed_synced": 0,
            "errors": 0,
            "last_pull_per_agent": {},
        }

        try:
            async with get_db_context() as db:
                rows = await self._fetch_candidates(db)
                stats["candidates"] = len(rows)
                if PULLSYNC_PENDING_AGENTS is not None:
                    try:
                        PULLSYNC_PENDING_AGENTS.labels(
                            registry_id=_REGISTRY_ID_LABEL
                        ).set(len(rows))
                    except Exception:
                        pass

                # §FEDSYNCTRUTH — fetches run `_CONCURRENCY` at a time; every row mutation
                # (the stamp, the merge) happens on the task that fetched it, with no session
                # I/O of its own, and the single commit below writes them all.
                async with httpx.AsyncClient(
                    timeout=_FETCH_TIMEOUT_SEC,
                    verify=True,  # public agent well-known; system CA only.
                    follow_redirects=False,  # §SSRFGUARD: fetch_agent_card follows them, asking about every hop.
                ) as client:
                    sem = asyncio.Semaphore(_CONCURRENCY)

                    async def _guarded(row: models.AgentCard) -> None:
                        async with sem:
                            try:
                                await self._pull_one(db, client, row, stats)
                            except Exception as e:  # noqa: BLE001
                                stats["errors"] += 1
                                try:
                                    _stamp_attempt(row, "error", False)
                                except Exception:  # noqa: BLE001
                                    pass
                                logger.warning(
                                    f"[AgentCardPullSync] {row.agent_did} pull errored: {e}"
                                )

                    await asyncio.gather(*[_guarded(r) for r in rows])

                await db.commit()
        except Exception as e:
            logger.error(f"[AgentCardPullSync] cycle error: {e}", exc_info=True)
            stats["errors"] += 1

        self._stats = stats
        # Mirror into module-level for legacy callers / debugging.
        _LAST_STATS.clear()
        _LAST_STATS.update(stats)

        dur_ms = int((time.time() - t0) * 1000)
        if PULLSYNC_LAST_CYCLE_DURATION_MS is not None:
            try:
                PULLSYNC_LAST_CYCLE_DURATION_MS.labels(
                    registry_id=_REGISTRY_ID_LABEL
                ).set(dur_ms)
            except Exception:
                pass
        logger.info(
            f"[AgentCardPullSync] cycle done in {dur_ms}ms — "
            f"candidates={stats['candidates']} "
            f"200={stats['fetched_200']} 304={stats['fetched_304']} "
            f"4xx={stats['fetched_4xx']} 5xx={stats['fetched_5xx']} "
            f"timeout={stats['fetched_timeout']} errors={stats['errors']} "
            f"skipped={stats['skipped_internal']} drift={stats['drift_agents']} "
            f"listed={stats.get('listed_synced', 0)}"
        )

    async def _fetch_candidates(
        self, db: AsyncSession
    ) -> List[models.AgentCard]:
        """Pick the up-to N stalest native cards with a well-known-resolvable URL.

        Native = no `card_data->federation_metadata->source_registry`. Pushing
        that filter into PostgreSQL (instead of a Python over-fetch) keeps the
        cycle cheap when synced-from-peer cards outnumber natives 50:1, as on
        registries with active federation peers.

        Order by last_pulled_at NULLS FIRST so never-pulled cards go first.
        """

        # §FEDSYNCTRUTH — three changes to the old query, each one measured:
        #   (1) the cursor is `last_pull_attempt_at`, not `last_pulled_at`: a failed attempt used to
        #       leave the row exactly where it was, so the same 100 dead cards were handed to every
        #       cycle and nothing behind them was ever asked (4,137 of 4,149 never pulled on rega);
        #   (2) a card in backoff (interval × 2^failures, capped at a week) is not a candidate;
        #   (3) hosts the registry can never reach are not candidates at all (the SQL twin of
        #       `_is_skippable_host`), so they never occupy one of the per-cycle slots — and neither
        #       is a card whose supportedInterfaces[0].url is missing or has no scheme+host, the
        #       only field `_well_known_url_for` reads (bake 1: 97 of 100 slots went to those).
        stmt = _candidate_stmt()
        res = await db.execute(stmt)
        return list(res.scalars().all())

    async def _pull_one(
        self,
        db: AsyncSession,
        client: httpx.AsyncClient,
        row: models.AgentCard,
        stats: Dict[str, Any],
    ) -> None:
        """One agent's pull cycle. Mutates `stats` and `row` in place."""
        if not isinstance(row.card_data, dict):
            return

        well_known = _well_known_url_for(row.card_data)
        if not well_known:
            stats["skipped_internal"] += 1
            _stamp_attempt(row, "skipped", False)
            if PULLSYNC_PULLS_TOTAL is not None:
                try:
                    PULLSYNC_PULLS_TOTAL.labels(
                        registry_id=_REGISTRY_ID_LABEL, outcome="skipped"
                    ).inc()
                except Exception:
                    pass
            return

        headers: Dict[str, str] = {}
        if row.last_pulled_etag:
            headers["If-None-Match"] = row.last_pulled_etag

        try:
            resp = await fetch_agent_card(client, well_known, headers)
        except FetchRefused as e:
            # §SSRFGUARD: a hop we do not follow, or too many hops. The stored card keeps what it had.
            stats["refused"] += 1
            _stamp_attempt(row, "refused", False)
            logger.warning(f"[AgentCardPullSync] {row.agent_did} refused: {e}")
            stats["last_pull_per_agent"][row.agent_did] = {
                "url": well_known, "status": "refused",
                "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            if PULLSYNC_PULLS_TOTAL is not None:
                try:
                    PULLSYNC_PULLS_TOTAL.labels(
                        registry_id=_REGISTRY_ID_LABEL, outcome="refused"
                    ).inc()
                except Exception:
                    pass
            return
        except (httpx.TimeoutException, asyncio.TimeoutError):
            stats["fetched_timeout"] += 1
            _stamp_attempt(row, "timeout", False)
            stats["last_pull_per_agent"][row.agent_did] = {
                "url": well_known, "status": "timeout",
                "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            if PULLSYNC_PULLS_TOTAL is not None:
                try:
                    PULLSYNC_PULLS_TOTAL.labels(
                        registry_id=_REGISTRY_ID_LABEL, outcome="timeout"
                    ).inc()
                except Exception:
                    pass
            return
        except Exception as e:
            # A dead hostname lands here (DNS / connect refused) — the outcome that used to leave
            # the cursor exactly where it was, forever. It is an attempt like any other.
            stats["errors"] += 1
            _stamp_attempt(row, "error", False)
            logger.debug(f"[AgentCardPullSync] {row.agent_did} fetch error: {e}")
            return

        status = resp.status_code
        new_etag = resp.headers.get("etag")
        now = datetime.datetime.now(datetime.timezone.utc)

        if status == 304:
            stats["fetched_304"] += 1
            row.last_pulled_at = now
            _stamp_attempt(row, "304", True, now)
            # the stored card is the agent's current one (the etag matched the 200 that wrote it)
            if _sync_listed_columns(row, row.card_data):
                stats["listed_synced"] = stats.get("listed_synced", 0) + 1
            stats["last_pull_per_agent"][row.agent_did] = {
                "url": well_known, "status": 304, "etag": row.last_pulled_etag,
                "ts": now.isoformat(),
            }
            if PULLSYNC_PULLS_TOTAL is not None:
                try:
                    PULLSYNC_PULLS_TOTAL.labels(
                        registry_id=_REGISTRY_ID_LABEL, outcome="304"
                    ).inc()
                except Exception:
                    pass
            return

        if status >= 500:
            stats["fetched_5xx"] += 1
            _stamp_attempt(row, "5xx", False, now)
            stats["last_pull_per_agent"][row.agent_did] = {
                "url": well_known, "status": status,
                "ts": now.isoformat(),
            }
            if PULLSYNC_PULLS_TOTAL is not None:
                try:
                    PULLSYNC_PULLS_TOTAL.labels(
                        registry_id=_REGISTRY_ID_LABEL, outcome="5xx"
                    ).inc()
                except Exception:
                    pass
            return

        if status >= 400:
            stats["fetched_4xx"] += 1
            _stamp_attempt(row, "4xx", False, now)
            stats["last_pull_per_agent"][row.agent_did] = {
                "url": well_known, "status": status,
                "ts": now.isoformat(),
            }
            if PULLSYNC_PULLS_TOTAL is not None:
                try:
                    PULLSYNC_PULLS_TOTAL.labels(
                        registry_id=_REGISTRY_ID_LABEL, outcome="4xx"
                    ).inc()
                except Exception:
                    pass
            return

        if status != 200:
            stats["errors"] += 1
            _stamp_attempt(row, "error", False, now)
            return

        # 200 — parse, merge, write back.
        try:
            fresh = resp.json()
        except Exception:
            stats["errors"] += 1
            _stamp_attempt(row, "error", False, now)
            return
        if not isinstance(fresh, dict) or not _looks_like_agent_card(fresh):
            # §SSRFGUARD: only a document that looks like an agent card is merged into a public card.
            stats["refused"] += 1
            _stamp_attempt(row, "not_a_card", False, now)
            logger.warning(f"[AgentCardPullSync] {row.agent_did}: {well_known} answered something that is not a card")
            return

        stats["fetched_200"] += 1
        if PULLSYNC_PULLS_TOTAL is not None:
            try:
                PULLSYNC_PULLS_TOTAL.labels(
                    registry_id=_REGISTRY_ID_LABEL, outcome="200"
                ).inc()
            except Exception:
                pass

        # §pass36 Phase 9.a — JWS signature verification in shadow mode.
        # When JWS_VERIFY_ENABLED=false (the default), this is a no-op.
        # When JWS_ENFORCE=true, invalid sigs reject this pull (else just log).
        try:
            from ..services.a2a_v1.jws_verifier import (
                verify_card_signature, jws_verify_enabled, jws_enforce,
            )
            if jws_verify_enabled():
                jws_valid, jws_reason = await verify_card_signature(
                    fresh, db, source="pullsync",
                )
                if not jws_valid:
                    logger.warning(
                        f"[AgentCardPullSync] JWS verify FAILED for {row.agent_did}: "
                        f"reason={jws_reason} enforce={jws_enforce()}"
                    )
                    # §pass47 A6 — emit audit event so the throttle reactor
                    # (`reactor_jws_verify_failed_throttle`) can count failures
                    # per agent across the 1h sliding window.
                    try:
                        from ..event_emitter import get_event_emitter
                        await get_event_emitter().emit(
                            event_type="AgentCardJWSVerifyFailed",
                            aggregate_id=row.agent_did,
                            data={
                                "agent_did": row.agent_did,
                                "reason": jws_reason,
                                "source": "pullsync",
                                "enforced": jws_enforce(),
                            },
                        )
                    except Exception as e:  # noqa: BLE001
                        logger.debug(f"[AgentCardPullSync] JWS event emit skipped: {e}")
                    if jws_enforce():
                        # Reject this pull; counter already incremented by verifier.
                        _stamp_attempt(row, "error", False, now)
                        return
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[AgentCardPullSync] JWS verify skipped (non-fatal): {e}")

        # Canonicalize defensively (idempotent if already v1.0).
        try:
            fresh = canonicalize_card_data(fresh)
        except Exception:
            pass

        merged, drifted = _merge_pulled_card(row.card_data, fresh)
        if _sync_listed_columns(row, merged):
            stats["listed_synced"] = stats.get("listed_synced", 0) + 1

        # Only write if something actually changed — saves vacuum + WAL.
        if drifted:
            row.card_data = merged
            row.last_pulled_at = now
            row.last_pulled_etag = new_etag
            _stamp_attempt(row, "200", True, now)
            stats["drift_agents"] += 1
            # Per-field rollup (de-dup the `:removed` suffix for counter labels).
            for f in drifted:
                base = f.split(":", 1)[0]
                stats["drift_field_counts"][base] = (
                    stats["drift_field_counts"].get(base, 0) + 1
                )
                if PULLSYNC_DRIFT_DETECTED_TOTAL is not None:
                    try:
                        PULLSYNC_DRIFT_DETECTED_TOTAL.labels(
                            registry_id=_REGISTRY_ID_LABEL, field=base
                        ).inc()
                    except Exception:
                        pass
            await _emit_drift_event(row.agent_did or "?", drifted, new_etag)
            stats["last_pull_per_agent"][row.agent_did] = {
                "url": well_known, "status": 200, "etag": new_etag,
                "drift_fields": drifted, "ts": now.isoformat(),
            }
        else:
            # No drift — just bump watermark + etag.
            row.last_pulled_at = now
            row.last_pulled_etag = new_etag
            _stamp_attempt(row, "200", True, now)
            stats["last_pull_per_agent"][row.agent_did] = {
                "url": well_known, "status": 200, "etag": new_etag,
                "drift_fields": [], "ts": now.isoformat(),
            }


# Singleton instance for the FastAPI lifespan.
_INSTANCE: Optional[AgentCardPullSync] = None


async def start_agent_card_pullsync() -> None:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = AgentCardPullSync()
    await _INSTANCE.start()


async def stop_agent_card_pullsync() -> None:
    global _INSTANCE
    if _INSTANCE is not None:
        await _INSTANCE.stop()
        _INSTANCE = None


def get_snapshot() -> Optional[Dict[str, Any]]:
    """For admin router — returns None if worker not yet started."""
    if _INSTANCE is None:
        return None
    return _INSTANCE.snapshot()


async def trigger_pull_for_did(agent_did: str) -> Dict[str, Any]:
    """§pass36 Option C Phase 5a + Phase 6 — one-shot pull for a single agent.

    Bypasses the 6h scheduler. Used by:
      - `/onboard/create_agent` (Option C path) to fetch the agent's card
        shortly after registration.
      - `/admin/agent-card-drift/{did}/accept` to force an immediate re-pull.

    Returns a dict describing the outcome:
        {"status": "ok"|"skipped"|"timeout"|"error"|"not_found"|"4xx"|"5xx",
         "etag": "...", "drifted_fields": [...], "reason": "..."}
    """
    outcome: Dict[str, Any] = {"status": "error", "reason": "uninitialized"}
    try:
        async with get_db_context() as db:
            res = await db.execute(
                select(models.AgentCard).where(models.AgentCard.agent_did == agent_did)
            )
            row = res.scalar_one_or_none()
            if not row:
                return {"status": "not_found", "reason": f"no card for {agent_did}"}
            if not isinstance(row.card_data, dict):
                return {"status": "error", "reason": "card_data not a dict"}

            well_known = _well_known_url_for(row.card_data)
            if not well_known:
                return {
                    "status": "skipped",
                    "reason": "non-public hostname",
                    "url": (row.card_data.get("supportedInterfaces") or [{}])[0].get("url"),
                }

            headers: Dict[str, str] = {}
            if row.last_pulled_etag:
                headers["If-None-Match"] = row.last_pulled_etag

            async with httpx.AsyncClient(
                timeout=_FETCH_TIMEOUT_SEC, verify=True, follow_redirects=False  # §SSRFGUARD: hops are asked below
            ) as client:
                try:
                    resp = await fetch_agent_card(client, well_known, headers)
                except FetchRefused as e:
                    return {"status": "refused", "reason": str(e), "url": well_known}
                except (httpx.TimeoutException, asyncio.TimeoutError):
                    return {"status": "timeout", "url": well_known}
                except Exception as e:
                    return {"status": "error", "reason": f"fetch: {e}", "url": well_known}

            now = datetime.datetime.now(datetime.timezone.utc)
            if resp.status_code == 304:
                row.last_pulled_at = now
                listed = _sync_listed_columns(row, row.card_data)
                await db.commit()
                return {
                    "status": "ok",
                    "url": well_known,
                    "http": 304,
                    "etag": row.last_pulled_etag,
                    "drifted_fields": [],
                    "listed_columns": listed,
                }
            if resp.status_code != 200:
                bucket = (
                    "5xx" if resp.status_code >= 500 else "4xx"
                )
                return {"status": bucket, "url": well_known, "http": resp.status_code}

            try:
                fresh = resp.json()
            except Exception:
                return {"status": "error", "reason": "non-json body", "url": well_known}
            if not isinstance(fresh, dict):
                return {"status": "error", "reason": "non-object json", "url": well_known}
            if not _looks_like_agent_card(fresh):
                # §SSRFGUARD: an internal service's JSON is not a card and never reaches a public one.
                return {"status": "not_a_card", "url": well_known}

            try:
                fresh = canonicalize_card_data(fresh)
            except Exception:
                pass

            merged, drifted = _merge_pulled_card(row.card_data, fresh)
            new_etag = resp.headers.get("etag")
            listed = _sync_listed_columns(row, merged)

            if drifted:
                row.card_data = merged
            row.last_pulled_at = now
            row.last_pulled_etag = new_etag
            await db.commit()

            if drifted:
                await _emit_drift_event(agent_did, drifted, new_etag)

            return {
                "status": "ok",
                "url": well_known,
                "http": 200,
                "etag": new_etag,
                "drifted_fields": drifted,
                "listed_columns": listed,
            }
    except Exception as e:  # noqa: BLE001
        logger.warning(
            f"[AgentCardPullSync] trigger_pull_for_did({agent_did}) errored: {e}",
            exc_info=False,
        )
        return {"status": "error", "reason": str(e)}
