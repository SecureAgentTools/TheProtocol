"""§REPBOND — the reputation bond: ONE rule for the money, the state, the gate and the card.

The bond is the gate to providing services (2026-09-05, the Commander's final
design): an agent that lists a price, bids in the Guild, accepts a contract or
is paid over A2A holds a bond that the TEG treasury keeps in escrow. Money moves
ONLY through the two existing escrow rails (`services/escrow.py`), never through
the registry's balance cache — the pre-0173 bond did exactly that and moved
nothing (R54).

Three modes, one knob (`REPUTATION_BOND_MODE`, env → network profile → "off"):

  off      byte-identical to before this batch (no ranking change, no gate)
  shadow   bonded agents rank first in discovery, every gate site COUNTS the
           decision it would take (`registry_reputation_bond_gate_total`) and
           refuses nothing — the current fleet
  enforce  the six sites refuse an unbonded provider with a sentence that names
           the amount and the door — sandbox now, the fresh frame at standup

Funding: the agent itself (`deposit`), the owner's wallet agent (`deposit` with
funded_by="wallet"), or the treasury as a DEMONSTRATION backstop (`backstop`,
`REPUTATION_BOND_TREASURY_BACKSTOP`, default off): a backstop bond holds the
treasury's own money, so forfeiting it moves nothing and releasing it pays
nobody — the flow says so on screen.

Maturity is the old rule (transactions, age, EigenTrust) with the thresholds
as profile knobs; a matured bond can be released to its funder after a cooldown.
Forfeiture is bookkeeping (the treasury already holds the escrow) — the slash
waterfall in `enforcement_engine` absorbs from the bond first.

The bond travels on the card as a TOP-LEVEL A2A extension
(`extensions[] uri=…/reputation-bond`), injected at DERIVE time (the well-known
export and the federation fan-out) from this registry's truth and signed by the
registry key with the rest of the card — peers read it from the mirror, this
registry reads its own `agents.reputation_bond_status`. Same place both pricing
authorities read the payment extension (§MIRRORFRESH).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

from fastapi import HTTPException, status as http_status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core import network_profile as _np
from ..core.frame_currency import frame_currency
from . import frame_policy as _fp
from ..models import Agent, AgentCard, ReputationBond

logger = logging.getLogger(__name__)

BOND_EXTENSION_URI = "https://theprotocol.cloud/extensions/v1/reputation-bond"
BONDED = ("locked", "matured")
MODES = ("off", "shadow", "enforce")
GATE_SITES = ("discovery", "listing", "pricing", "guild_bid", "contract_accept", "a2a_payee")
FUNDED_BY = ("self", "wallet", "treasury")

try:  # metrics never break a money rail
    from prometheus_client import Counter as _Counter
    GATE_DECISIONS = _Counter(
        "registry_reputation_bond_gate_total",
        "Reputation-bond gate decisions per site (shadow counts what enforce would refuse)",
        ["site", "mode", "decision"],
    )
except Exception:  # noqa: BLE001
    GATE_DECISIONS = None


# ── knobs (env → profile → fallback; every one inert while unset) ───────────

def bond_mode() -> str:
    v = (_np.knob("REPUTATION_BOND_MODE", "off") or "off").strip().lower()
    return v if v in MODES else "off"


def treasury_backstop_enabled() -> bool:
    return _np.bool_knob("REPUTATION_BOND_TREASURY_BACKSTOP", False)


def slash_mode() -> str:
    """ENFORCEMENT_SLASH_MODE: cache (today's cache-only write) | shadow (plan + log +
    today's write) | enforce (the waterfall MOVES money: bond → stake → liquid)."""
    v = (_np.knob("ENFORCEMENT_SLASH_MODE", "cache") or "cache").strip().lower()
    return v if v in ("cache", "shadow", "enforce") else "cache"


def release_cooldown_days() -> int:
    return max(0, _np.int_knob("REPUTATION_BOND_RELEASE_COOLDOWN_DAYS", 7))


def _pget(doc: Optional[Dict[str, Any]], path: str) -> Any:
    cur: Any = doc or {}
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _rule(policy_json: Optional[Dict[str, Any]], canonical: str, alias: Optional[str], default: Any) -> Any:
    """ONE rule, ONE key (§BONDFILL-3). The canonical `enforcement.*` key first — the one the
    network's bounds are written against and the signed card publishes — then the deprecated
    `reputation_bond.*` alias a frame may still carry, then the default.

    Reads a RESOLVED document or a raw row alike: a raw row that set only the alias still means
    what it said, which is `frame_policy._promote_aliases`'s rule applied at the reader too.
    """
    v = _pget(policy_json, canonical)
    if v is None and alias:
        v = _pget(policy_json, alias)
    return default if v is None else v


# The ceiling that makes "matured" never mean "unbonded" (base_network_params bounds it at 80).
# Enforced HERE as well as in the validator because an env or profile knob never passes through
# the policy validator — a bound that only binds one of three layers binds nothing.
RELEASES_PERCENT_CEILING = 80

# The fewest ranked agents a percentile can be taken over and still mean something. Below this
# the percentile half of the trust gate is WAIVED and the readout says so — an agent must not be
# failed for the network's youth over a number it cannot move. A statistical property, not a
# frame's preference, so it is a constant rather than a policy parameter.
MIN_RANKED_POPULATION = 10

# Ledger system accounts are not agents and must not set the bar for agents: on EU the treasury
# alone held 99.67 % of the trust vector with zero incoming trust edges.
SYSTEM_DID_PREFIX = "did:theprotocol:teg_system_"


def bond_amount(policy_json: Optional[Dict[str, Any]]) -> Decimal:
    """The required bond. Profile/env first (the fresh network derives it from the
    grant: GRANT × 25 %), else the per-registry enforcement policy, else 50.
    The knob's name comes from `frame_policy.KNOB_OVERRIDES` (§CARDBOND), the one table the card
    readout and the governance refusal read too."""
    path = "enforcement.reputation_bond_min_avt"
    pol = _rule(policy_json, path, "reputation_bond.amount_avt", 50)
    try:
        fallback = str(Decimal(str(pol)))
    except (InvalidOperation, TypeError, ValueError):
        fallback = "50"
    return _np.money_knob(_fp.KNOB_OVERRIDES[path], fallback)


def maturity_thresholds(policy_json: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Every maturity rule, read from ONE key each (§BONDFILL-3). The env/profile knobs keep
    their precedence exactly as before, so a node with none set is byte-unchanged for the two
    rules that already existed. Each knob's name comes from `frame_policy.KNOB_OVERRIDES`."""
    def _i(canonical: str, alias: Optional[str], default: int) -> int:
        try:
            base = int(_rule(policy_json, canonical, alias, default))
        except (TypeError, ValueError):
            base = default
        return _np.int_knob(_fp.KNOB_OVERRIDES[canonical], base)

    releases = _i("enforcement.bond_maturity_releases_percent", None, 60)
    if releases > RELEASES_PERCENT_CEILING or releases < 0:
        logger.error("[REPBOND] bond_maturity_releases_percent=%s is outside 0..%s — clamped; "
                     "matured must never mean unbonded", releases, RELEASES_PERCENT_CEILING)
        releases = max(0, min(RELEASES_PERCENT_CEILING, releases))
    return {
        "min_transactions": _i("enforcement.bond_maturity_min_transactions", "reputation_bond.min_transactions", 10),
        "min_age_days": _i("enforcement.bond_maturity_min_age_days", "reputation_bond.min_age_days", 30),
        "min_trust_percentile": _i("enforcement.bond_maturity_min_trust_percentile", None, 50),
        "min_rated_peers": _i("enforcement.bond_maturity_min_rated_peers", None, 3),
        "releases_percent": releases,
        "min_ranked_population": MIN_RANKED_POPULATION,
    }


def applied_rule(path: str, policy_json: Optional[Dict[str, Any]]) -> Optional[Any]:
    """The value THIS RAIL applies for one knob-governed policy path (§CARDBOND): every knob and
    clamp included. The registry card asks this, never the document, so what a peer reads is what
    an agent is charged. None for a path this rail does not read."""
    if path == "enforcement.reputation_bond_min_avt":
        return bond_amount(policy_json)
    prefix = "enforcement.bond_maturity_"
    if path.startswith(prefix):
        return maturity_thresholds(policy_json).get(path[len(prefix):])
    return None


async def policy_json(db: AsyncSession) -> Dict[str, Any]:
    """The frame's RESOLVED policy document. This used to hand back the raw row, so a frame whose
    row predates a section (registry-a's is from April, five months before §REPBOND) read nothing
    and survived only on the hardcoded fallbacks — the partial-row defect `frame_policy.resolve`
    exists to close. Same values on every live frame; one fewer copy of the defaults."""
    from . import frame_policy as _fp
    return (await _fp.load(db)).doc


def registry_display_name() -> str:
    """What this registry calls itself, on a bond chip and on every card it signs.

    §BONDFILL (2026-09-11) — THIS READ THE NAME OF A VARIABLE NOBODY SETS. `REGISTRY_FEDERATION_NAME`
    is unset on every frame in the fleet, so every bonded card EU and ASIA have ever exported has
    carried `"registry": "registry"` — a last-resort placeholder published as if it were a name,
    which is [[never_publish_a_value_invented_for_legibility]] exactly. It went unseen because
    nothing rendered the field until the maturity bar needed to say WHOSE claim it was showing.
    The frame already knows its name and publishes it on its signed card (`identity.registry_name`
    = "EU"), from `REGISTRY_NAME` in its own environment. Read that too.

    The order is deliberate: an explicitly-set federation name still wins, so a node that set one
    is byte-unchanged; "registry" survives only as the last resort it was meant to be.

    ⚠ THE CANONICAL RULE IS `federation_sync._get_display_name(db)` — registry_self.federation_name,
    then the admin's display name, then `settings.REGISTRY_NAME`. This helper is its SYNC cousin and
    cannot reach a database, so it starts at that rule's third step. Measured live before shipping:
    on EU and ASIA the two agree ("EU" / "ASIA"), so this is the same answer by a shorter road, not
    a second opinion. If they ever diverge, the DB-backed one is right and this one should be fed
    from it by the callers that hold a session.
    """
    # §TRUSTCHAIN P4.5 — FED FROM THE CANONICAL RULE when it has run: federation_sync caches the
    # DB-resolved name (registry_self.federation_name, then the admin's display name) for five
    # minutes after any export; a warm cache is the same answer the cards carry, so read it first.
    # Cold (a fresh worker, a script), the env-based road below is taken, as measured to agree.
    try:
        from ..routers import federation_sync as _fs
        _cached = getattr(_fs, "_registry_display_name", None)
        if _cached and _cached != "Unknown Registry":
            return str(_cached)
    except Exception:  # noqa: BLE001
        pass
    try:
        from ..config import settings
        name = getattr(settings, "REGISTRY_FEDERATION_NAME", None)
    except Exception:  # noqa: BLE001
        name = None
    # ⚠ `settings.REGISTRY_NAME` is deliberately NOT consulted: it carries a non-empty DEFAULT
    # ("AgentVault Registry"), so it cannot tell a frame that configured its name from one that
    # did not, and reading it would publish a PRODUCT name as a frame's identity on every
    # unconfigured node — the same defect as the "registry" placeholder, in better clothes.
    # An environment variable is present only when somebody set it, which is the distinction
    # that matters here. Measured on the live fleet: REGISTRY_NAME=EU / ASIA, agreeing with the
    # canonical DB-backed rule.
    return (name
            or os.environ.get("REGISTRY_FEDERATION_NAME")
            or os.environ.get("REGISTRY_NAME")
            or "registry")


def config_block(policy: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    th = maturity_thresholds(policy)
    return {
        "mode": bond_mode(),
        "amount": money_str(bond_amount(policy)),
        "currency": frame_currency(),
        "treasury_backstop": treasury_backstop_enabled(),
        "release_cooldown_days": release_cooldown_days(),
        # §BONDFILL-3 — `th` now carries the relative trust gate, the evidence floor, the share
        # unlocked at maturity, and the population below which the percentile is waived.
        "maturity": th,
        "extension_uri": BOND_EXTENSION_URI,
        "sites": list(GATE_SITES),
        "registry": registry_display_name(),
    }


# ── SQL fragments for the discovery CTE (`s` carries a.reputation_bond_status + c.card_data) ──

_EXT_PATH = "'$.extensions[*] ? (@.uri == \"" + BOND_EXTENSION_URI + "\")'"
SQL_BOND_EXT = "jsonb_path_query_first(s.card_data::jsonb, " + _EXT_PATH + ")"
# Local truth first (the agents row), the mirrored card's extension for federated rows.
SQL_IS_BONDED = (
    "(COALESCE(s.reputation_bond_status, '') IN ('locked','matured')"
    " OR COALESCE(" + SQL_BOND_EXT + "->'params'->>'status', '') IN ('locked','matured'))"
)


def sql_is_bonded(agent_alias: str = "a", card_alias: str = "s") -> str:
    """The predicate with the caller's aliases: `agent_alias` names the agents row (local
    truth), `card_alias` the card row whose `card_data` may carry a peer's extension."""
    ext = "jsonb_path_query_first(" + card_alias + ".card_data::jsonb, " + _EXT_PATH + ")"
    return (
        "(COALESCE(" + agent_alias + ".reputation_bond_status, '') IN ('locked','matured')"
        " OR COALESCE(" + ext + "->'params'->>'status', '') IN ('locked','matured'))"
    )


def sql_card_is_bonded(card_alias: str = "c") -> str:
    """Population-level predicate for a CTE that has ONLY the card row: an EXISTS on the
    agents table for local truth, else the card's own extension."""
    ext = "jsonb_path_query_first(" + card_alias + ".card_data::jsonb, " + _EXT_PATH + ")"
    return (
        "(EXISTS (SELECT 1 FROM agents ab WHERE ab.did = " + card_alias + ".agent_did"
        " AND ab.reputation_bond_status IN ('locked','matured'))"
        " OR COALESCE(" + ext + "->'params'->>'status', '') IN ('locked','matured'))"
    )


# ── pure helpers ─────────────────────────────────────────────────────────────

def money_str(v: Any) -> Optional[str]:
    """A NUMERIC(36,18) column reads back as `250.000000000000000000`; every surface
    (chip, card extension, API) shows the amount as a person would write it."""
    if v is None:
        return None
    try:
        d = Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return str(v)
    if d == d.to_integral_value():
        return str(d.quantize(Decimal(1)))
    return format(d.normalize(), "f")


def is_bonded_status(status: Optional[str]) -> bool:
    return (status or "") in BONDED


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def is_paid_card(card_data: Optional[Dict[str, Any]]) -> bool:
    """Python twin of `_SQL_IS_PAID` (routers/agent_cards.py): the legacy pricing
    block says payment_required, OR the TOP-LEVEL A2A payment extension carries a
    positive base_rate."""
    cd = _as_dict(card_data)
    pricing = cd.get("pricing")
    if isinstance(pricing, dict) and pricing.get("payment_required") is True:
        return True
    for ext in (cd.get("extensions") or []):
        if not isinstance(ext, dict):
            continue
        if ext.get("uri") == "https://theprotocol.cloud/extensions/v1/auth/a2a-payment":
            try:
                if Decimal(str((ext.get("params") or {}).get("base_rate", "0"))) > 0:
                    return True
            except (InvalidOperation, TypeError, ValueError):
                pass
    return False


def progress_dict(*, transactions: int, age_days: int, eigentrust: float,
                  thresholds: Dict[str, Any], rated_peers: Optional[int] = None,
                  trust_percentile: Optional[float] = None,
                  trust_population: Optional[int] = None,
                  source: str = "registry", as_of: Optional[str] = None) -> Dict[str, Any]:
    """The maturity picture: three gates, how full each is, and which one is the long pole.

    §BONDFILL-3 — THE TRUST GATE IS RELATIVE NOW, AND IT CAN SAY IT CANNOT BE MEASURED.
      * EVIDENCE (the agent's to earn): rated satisfactory by at least `min_rated_peers` distinct
        counterparties owned by OTHER developers.
      * STANDING (relative to the frame): at or above `min_trust_percentile` of the frame's ranked
        agents, ledger system accounts excluded.
      * Standing is WAIVED while fewer than `min_ranked_population` agents are ranked — a
        percentile over nine agents is noise, and an agent must not fail for the network's youth
        over a number it cannot move. Waived is reported as waived, never as met.
      * If the population was not measured at all it is UNKNOWN, and unknown does not pass: a
        waiver is a decision about a measured fact, and there is no fact to decide about.
    `eigentrust` stays in the output as information; nothing gates on its absolute value.
    """
    mt, md = thresholds["min_transactions"], thresholds["min_age_days"]
    mtp = thresholds.get("min_trust_percentile", 50)
    mrp = thresholds.get("min_rated_peers", 3)
    mpop = thresholds.get("min_ranked_population", MIN_RANKED_POPULATION)

    if trust_population is None:
        pct_state = "unknown"
    elif trust_population < mpop:
        pct_state = "waived"
    else:
        pct_state = "measured"
    peers = int(rated_peers) if rated_peers is not None else None
    peers_ok = peers is not None and peers >= mrp
    pct = float(trust_percentile) if trust_percentile is not None else None
    if pct_state == "measured":
        standing_ok = pct is not None and pct >= mtp
    else:
        standing_ok = pct_state == "waived"
    trust_ok = peers_ok and standing_ok

    met = {
        "transactions": transactions >= mt,
        "age": age_days >= md,
        "trust": trust_ok,
    }
    peers_frac = min(1.0, (peers or 0) / mrp) if mrp > 0 else 1.0
    if pct_state == "measured":
        standing_frac = min(1.0, (pct or 0.0) / mtp) if mtp > 0 else 1.0
    else:
        standing_frac = 1.0 if pct_state == "waived" else 0.0
    parts = [
        min(1.0, transactions / mt) if mt > 0 else 1.0,
        min(1.0, age_days / md) if md > 0 else 1.0,
        # The trust segment is only as full as its weaker half: evidence you have not earned is not
        # made up for by a standing you happen to hold, and the reverse.
        1.0 if trust_ok else min(peers_frac, standing_frac),
    ]
    # §BONDFILL (2026-09-11) — WHICH GATE IS THE LONG POLE, named by the rule that owns the
    # arithmetic rather than re-derived by each surface. Ordered furthest behind first.
    blocking = [k for _, k in sorted(
        ((f, k) for f, k, ok in zip(parts, ("transactions", "age", "trust"), met.values()) if not ok),
        key=lambda t: t[0],
    )]
    return {
        "transactions": int(transactions), "transactions_required": mt,
        "age_days": int(age_days), "age_days_required": md,
        "rated_peers": peers, "rated_peers_required": mrp,
        "trust_percentile": (round(pct, 1) if pct is not None else None),
        "trust_percentile_required": mtp,
        "trust_percentile_state": pct_state,
        "trust_population": trust_population, "trust_population_required": mpop,
        "eigentrust": round(float(eigentrust), 6),
        "met": met,
        "matured": all(met.values()),
        "percent": int(round(100 * sum(parts) / 3)),
        "blocking": blocking,
        "source": source,
        "as_of": as_of,
    }


def progress_for(act: Optional[Dict[str, Any]], locked_at: Optional[datetime],
                 thresholds: Dict[str, Any]) -> Dict[str, Any]:
    """The ONE way a LOCAL row becomes a progress object. Five call sites used to spell out
    `progress_dict(...)` by hand, which is how a new input gets forgotten at the fifth of them
    (§FANOUTFIX). They all come through here now."""
    a = act or _NO_ACTIVITY
    return progress_dict(
        transactions=a.get("transactions", 0), age_days=_age_days(locked_at),
        eigentrust=a.get("eigentrust", 0.0), thresholds=thresholds,
        rated_peers=a.get("rated_peers"), trust_percentile=a.get("trust_percentile"),
        trust_population=a.get("trust_population"),
    )


# What a DID with no activity row reads as. `trust_population` is None (UNKNOWN), never 0:
# zero would read as "measured, too few ranked", which is a claim about the frame we did not make.
_NO_ACTIVITY: Dict[str, Any] = {
    "transactions": 0, "volume": Decimal(0), "eigentrust": 0.0,
    "rated_peers": 0, "trust_percentile": None, "trust_population": None,
}


def maturity_params(progress: Optional[Dict[str, Any]],
                    thresholds: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """§BONDFILL — the maturity snapshot a card carries to its mirrors.

    ⚠ IT DELIBERATELY OMITS `age_days` AND `percent`, and that omission is the design. Both move
    with the CLOCK, not with any stored row, so a value written here would be wrong the next
    morning and no incremental gate could ever notice: a cursor, a watermark, a digest and a
    reconcile walk all ask about rows, and a row that only aged has not changed. The reader
    recomputes both from `locked_at`, which is signed and already in this extension's params.

    v2 (§BONDFILL-3) carries the relative trust gate: the evidence count, the standing percentile
    and the population it was taken over, each as the origin measured it at `as_of`.
    """
    if not progress:
        return None
    th = thresholds or {
        "min_transactions": progress.get("transactions_required"),
        "min_age_days": progress.get("age_days_required"),
        "min_trust_percentile": progress.get("trust_percentile_required"),
        "min_rated_peers": progress.get("rated_peers_required"),
        "min_ranked_population": progress.get("trust_population_required"),
    }
    return {
        "version": 2,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "transactions": progress.get("transactions"),
        "eigentrust": progress.get("eigentrust"),
        "rated_peers": progress.get("rated_peers"),
        "trust_percentile": progress.get("trust_percentile"),
        "trust_population": progress.get("trust_population"),
        "thresholds": {
            "min_transactions": th.get("min_transactions"),
            "min_age_days": th.get("min_age_days"),
            "min_trust_percentile": th.get("min_trust_percentile"),
            "min_rated_peers": th.get("min_rated_peers"),
            "min_ranked_population": th.get("min_ranked_population"),
        },
        "matured": bool(progress.get("matured")),
    }


def progress_from_card(params: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """§BONDFILL — resolve a MIRRORED card's bond extension into the same progress shape a
    local row produces, so every surface renders one object and not two.

    The counters are the origin's attested snapshot; the AGE is recomputed here and now from
    the signed `locked_at`, so the segment a reader can verify for itself is never stale. The
    percent arithmetic is `progress_dict`'s, called rather than copied — a second
    implementation of a formula is how two surfaces start disagreeing about one fact.
    Returns None when the origin published no snapshot: absent is not zero, and a peer that
    cannot see maturity must say so rather than draw an empty bar.
    """
    if not isinstance(params, dict):
        return None
    m = params.get("maturity")
    if not isinstance(m, dict):
        return None
    th_raw = m.get("thresholds") or {}
    th = {
        "min_transactions": _int_or(th_raw.get("min_transactions"), 0),
        "min_age_days": _int_or(th_raw.get("min_age_days"), 0),
        "min_trust_percentile": _int_or(th_raw.get("min_trust_percentile"), 50),
        "min_rated_peers": _int_or(th_raw.get("min_rated_peers"), 3),
        "min_ranked_population": _int_or(th_raw.get("min_ranked_population"), MIN_RANKED_POPULATION),
    }
    # A v1 snapshot (an origin on V0343/V0344) carries only the retired absolute eigentrust, so
    # the trust gate there is UNKNOWN rather than guessed from a number that no longer gates:
    # `rated_peers` None and `trust_population` None read as unknown in `progress_dict`.
    v2 = _int_or(m.get("version"), 1) >= 2
    locked_at = params.get("locked_at")
    dt = None
    if isinstance(locked_at, str) and locked_at:
        try:
            dt = datetime.fromisoformat(locked_at.replace("Z", "+00:00"))
        except ValueError:
            dt = None
    return progress_dict(
        transactions=_int_or(m.get("transactions"), 0),
        age_days=_age_days(dt),
        eigentrust=_float_or(m.get("eigentrust"), 0.0),
        thresholds=th,
        rated_peers=(_int_or(m.get("rated_peers"), 0) if v2 and m.get("rated_peers") is not None else None),
        trust_percentile=(_float_or(m.get("trust_percentile"), 0.0)
                          if v2 and m.get("trust_percentile") is not None else None),
        trust_population=(_int_or(m.get("trust_population"), 0)
                          if v2 and m.get("trust_population") is not None else None),
        source="card",
        as_of=m.get("as_of") if isinstance(m.get("as_of"), str) else None,
    )


def _int_or(v: Any, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _float_or(v: Any, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def extension_entry(state: Dict[str, Any]) -> Dict[str, Any]:
    bond = state.get("bond") or state
    return {
        "uri": BOND_EXTENSION_URI,
        "required": False,
        "description": "Reputation bond held in escrow by the agent's home registry",
        "params": {
            "version": 1,
            "status": bond.get("status"),
            "amount": bond.get("amount"),
            "currency": bond.get("currency"),
            "locked_at": bond.get("locked_at"),
            "matured_at": bond.get("matured_at"),
            "funded_by": bond.get("funded_by"),
            "registry": bond.get("registry") or registry_display_name(),
            # §BONDFILL-3 — the unlock travels too, or a mirror would draw a full fire for an
            # agent that took its capital back. `fire` is derived from these two here and at the
            # reader alike (`fire_state`), never trusted as a free-standing claim.
            "original_amount": bond.get("original_amount"),
            "partial_released_amount": bond.get("partial_released_amount"),
            "partial_released_at": bond.get("partial_released_at"),
            # §BONDFILL — the maturity snapshot, present only when there is progress to state.
            # `inject_extension` drops the key entirely when it is None, so a peer reading an
            # older origin's card sees no maturity block rather than an empty one.
            "maturity": maturity_params(bond.get("progress")),
        },
    }


def inject_extension(card: Dict[str, Any], state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Derive-time: strip any stale bond extension, add the current one when bonded.
    Never persisted into card_data (same discipline as the track-record extension)."""
    if not isinstance(card, dict):
        return card
    exts = [e for e in (card.get("extensions") or [])
            if not (isinstance(e, dict) and e.get("uri") == BOND_EXTENSION_URI)]
    bond = (state or {}).get("bond") or state or {}
    if is_bonded_status(bond.get("status")):
        _entry = extension_entry(state)
        if _entry["params"].get("maturity") is None:
            _entry["params"].pop("maturity", None)
        exts.append(_entry)
    if exts:
        card["extensions"] = exts
    elif "extensions" in card:
        card["extensions"] = []
    return card


def _as_dict(card_data: Any) -> Dict[str, Any]:
    if isinstance(card_data, dict):
        return card_data
    if isinstance(card_data, (str, bytes)):
        try:
            v = json.loads(card_data)
            return v if isinstance(v, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def extension_from_card(card_data: Any) -> Optional[Dict[str, Any]]:
    for ext in (_as_dict(card_data).get("extensions") or []):
        if isinstance(ext, dict) and ext.get("uri") == BOND_EXTENSION_URI:
            p = ext.get("params") or {}
            return p if isinstance(p, dict) else None
    return None


# ── loading ──────────────────────────────────────────────────────────────────

async def load_bond(db: AsyncSession, did: str) -> Optional[ReputationBond]:
    res = await db.execute(select(ReputationBond).where(ReputationBond.agent_did == did))
    return res.scalar_one_or_none()


async def load_bonds(db: AsyncSession, dids: Sequence[str]) -> Dict[str, ReputationBond]:
    dids = [d for d in dids if d]
    if not dids:
        return {}
    res = await db.execute(select(ReputationBond).where(ReputationBond.agent_did.in_(dids)))
    return {b.agent_did: b for b in res.scalars().all()}


async def load_agent(db: AsyncSession, did: str) -> Optional[Agent]:
    res = await db.execute(select(Agent).where(Agent.did == did))
    return res.scalar_one_or_none()


# §BONDFILL-3 — the maturity inputs for a PAGE of DIDs in ONE statement: the two ledger counters,
# the retired absolute EigenTrust (information only), the EVIDENCE count (distinct raters owned by
# other developers — `agents.creator_developer_id`; a guessed column here would fail inside
# discovery's try/except and blank every bond on the page) and the STANDING percentile among the
# frame's ranked agents, with the population it was taken over. Ledger system accounts are out of
# both: the treasury alone held 99.67 % of EU's vector with no incoming trust edge at all.
# `left(x, n) <> p` rather than LIKE, whose `_` is a single-character wildcard.
# ⚠ `cume_dist()`, NOT `percent_rank()`. Measured on EU before shipping: percent_rank put EVERY
# bonded agent at the 0th percentile, including one already rated by 3 independent peers, because
# it ranks a TIE at the lowest position and a young network's agents mostly share one teleport-floor
# trust value. The rule is "at or above the median", i.e. the share of ranked agents whose trust is
# at or below yours — which is cume_dist, and which puts a tie where the tie actually sits.
_PROGRESS_SQL = text("""
WITH latest AS (
    SELECT max(epoch) AS e FROM global_trust_vectors
),
ranked AS (
    SELECT g.agent_did, cume_dist() OVER (ORDER BY g.global_trust) AS pr
      FROM global_trust_vectors g, latest
     WHERE g.epoch = latest.e
       AND g.global_trust > 0
       AND left(g.agent_did, length(:sys)) <> :sys
),
pop AS (SELECT count(*) AS n FROM ranked)
SELECT d.did,
       COALESCE((SELECT SUM(l.satisfactory) FROM local_trust_scores l
                  WHERE l.from_did = d.did OR l.to_did = d.did), 0) AS transactions,
       COALESCE((SELECT SUM(l.tx_volume) FROM local_trust_scores l WHERE l.to_did = d.did), 0) AS volume,
       COALESCE((SELECT g.global_trust FROM global_trust_vectors g WHERE g.agent_did = d.did
                  ORDER BY g.epoch DESC NULLS LAST LIMIT 1), 0) AS eigentrust,
       (SELECT count(DISTINCT l.from_did)
          FROM local_trust_scores l
          LEFT JOIN agents ra ON ra.did = l.from_did
          LEFT JOIN agents me ON me.did = d.did
         WHERE l.to_did = d.did
           AND l.satisfactory > 0
           AND l.from_did <> d.did
           AND left(l.from_did, length(:sys)) <> :sys
           -- §TRUSTCHAIN P4.5: a rater with NO local row (ra.did IS NULL, a foreign rater) is
           -- independent; a local rater is independent when its owner differs. `creator_developer_id`
           -- is NOT NULL on `agents`, so the old `IS NULL` tests could only ever fire for the missing
           -- row, and said something else. Same rows, measured (zero live effect on EU and ASIA).
           AND (ra.did IS NULL OR ra.creator_developer_id <> me.creator_developer_id)) AS rated_peers,
       r.pr AS trust_rank,
       p.n AS trust_population
  FROM unnest(CAST(:dids AS text[])) AS d(did)
  LEFT JOIN ranked r ON r.agent_did = d.did
  CROSS JOIN pop p
""")


async def activity_batch(db: AsyncSession, dids: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    """Per DID: satisfactory interactions in either direction (the maturity count the
    old status route already used), received volume, latest EigenTrust."""
    dids = [d for d in dids if d]
    if not dids:
        return {}
    res = await db.execute(_PROGRESS_SQL, {"dids": dids, "sys": SYSTEM_DID_PREFIX})
    out: Dict[str, Dict[str, Any]] = {}
    for r in res.mappings().all():
        out[r["did"]] = {
            "transactions": int(r["transactions"] or 0),
            "volume": Decimal(str(r["volume"] or 0)),
            "eigentrust": float(r["eigentrust"] or 0.0),
            "rated_peers": int(r["rated_peers"] or 0),
            # cume_dist is (0, 1]; an agent the ranking does not contain (zero trust) is None,
            # which gates as "not at the percentile" when standing is measured.
            "trust_percentile": (float(r["trust_rank"]) * 100.0 if r["trust_rank"] is not None else None),
            "trust_population": int(r["trust_population"] or 0),
        }
    return out


def _age_days(locked_at: Optional[datetime]) -> int:
    if not locked_at:
        return 0
    return (datetime.now(timezone.utc) - _aware(locked_at)).days


async def stamp_matured(db: AsyncSession, bond: ReputationBond, progress: Dict[str, Any], *,
                        agent: Optional[Agent] = None, commit: bool = True) -> bool:
    """A locked bond whose progress says matured gets its `matured_at` the moment
    anything looks at it — the old table never wrote the column at all."""
    if bond.status != "locked" or not progress.get("matured"):
        return False
    now = datetime.now(timezone.utc)
    bond.status = "matured"
    bond.matured_at = now
    bond.updated_at = now
    if agent is not None:
        agent.reputation_bond_status = "matured"
    else:
        a = await load_agent(db, bond.agent_did)
        if a is not None:
            a.reputation_bond_status = "matured"
    if commit:
        await db.commit()
        await touch_native_card(db, bond.agent_did)
    await _emit("ReputationBondMatured", bond.agent_did, {
        "agent_did": bond.agent_did, "bond_id": bond.id, "amount": money_str(bond.amount),
        "currency": frame_currency(), "matured_at": now.isoformat(),
        "progress": progress,
    }, key=f"repbond-mat-{bond.id}-{bond.escrow_ref or 'legacy'}")
    return True


def fire_state(status: Optional[str], partial_released_at: Any) -> Optional[str]:
    """§BONDFILL-3 — what the maturity bar SHOWS, decided once here so the home frame, a mirror
    and any backend reader draw the same thing.

      burning       matured and the whole bond still held. The fire is a COSTLY signal: the
                    owner has had the right to take capital back and has chosen not to, which is
                    exactly why a buyer can read it as commitment.
      embers        matured, and the declared share was unlocked. Still bonded, still slashable,
                    less at stake — and the bar says so rather than pretending nothing changed.
      extinguished  released: the exit. Not bonded any more.
      None          locked (maturing), forfeited, voided or no bond — nothing to burn.
    """
    if status == "matured":
        return "embers" if partial_released_at else "burning"
    if status == "released":
        return "extinguished"
    return None


def unlock_block(bond: Optional[ReputationBond], thresholds: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Whether the maturity unlock can be pressed NOW, and if not, the one reason why — so the
    owner's button never offers what the rail will refuse, and never hides what it would grant."""
    if bond is None or thresholds is None:
        return None
    pct = int(thresholds.get("releases_percent", 0))
    held = Decimal(str(bond.amount or 0))
    amount = (held * Decimal(pct) / Decimal(100)).quantize(Decimal("0.000000000000000001"), rounding=ROUND_DOWN)
    after = None
    reason = None
    if bond.status != "matured":
        reason = "not_matured"
    elif bond.partial_released_at:
        reason = "already_unlocked"
    elif pct <= 0:
        reason = "frame_releases_nothing"
    elif bond.funded_by == "treasury":
        reason = "treasury_backstop"
    else:
        earliest = _aware(bond.matured_at or bond.locked_at) + timedelta(days=release_cooldown_days())
        after = earliest.isoformat()
        if datetime.now(timezone.utc) < earliest:
            reason = "cooldown"
    return {
        "percent": pct,
        "amount": money_str(amount),
        "keeps": money_str(held - amount),
        "available": reason is None,
        "reason": reason,
        "after": after,
    }


def bond_dict(bond: Optional[ReputationBond], *, required: Decimal,
              progress: Optional[Dict[str, Any]],
              thresholds: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ccy = frame_currency()
    if bond is None:
        return {"status": "none", "is_bonded": False, "amount": None, "currency": ccy,
                "required_amount": money_str(required), "locked_at": None, "matured_at": None,
                "released_at": None, "funded_by": None, "funder_did": None,
                "escrow_ref": None, "teg_transaction_id": None, "progress": None,
                "fire": None, "unlock": None,
                "source": "registry", "registry": registry_display_name()}
    return {
        "status": bond.status,
        "is_bonded": is_bonded_status(bond.status),
        "amount": money_str(bond.amount),
        "currency": ccy,
        "required_amount": money_str(required),
        "locked_at": _iso(bond.locked_at),
        "matured_at": _iso(bond.matured_at),
        "released_at": _iso(bond.released_at),
        "forfeited_at": _iso(bond.forfeited_at),
        "funded_by": bond.funded_by,
        "funder_did": bond.funder_did,
        "escrow_ref": bond.escrow_ref,
        "teg_transaction_id": bond.teg_transaction_id,
        "release_teg_transaction_id": bond.release_teg_transaction_id,
        # §BONDFILL-3 — `amount` is what is HELD; the original is held + what came back.
        "original_amount": money_str(Decimal(str(bond.amount or 0)) + Decimal(str(bond.partial_released_amount or 0))),
        "partial_released_amount": money_str(bond.partial_released_amount),
        "partial_released_at": _iso(bond.partial_released_at),
        "partial_release_teg_transaction_id": bond.partial_release_teg_transaction_id,
        "fire": fire_state(bond.status, bond.partial_released_at),
        "unlock": unlock_block(bond, thresholds),
        "progress": progress,
        "source": "registry",
        "registry": registry_display_name(),
    }


async def bond_state(db: AsyncSession, did: str, *, policy: Optional[Dict[str, Any]] = None,
                     agent: Optional[Agent] = None) -> Dict[str, Any]:
    """The whole answer for ONE local agent: state + maturity progress + activity.
    Stamps `matured_at` when the progress says so."""
    policy = policy if policy is not None else await policy_json(db)
    required = bond_amount(policy)
    th = maturity_thresholds(policy)
    bond = await load_bond(db, did)
    act = (await activity_batch(db, [did])).get(did) or _NO_ACTIVITY
    progress = None
    if bond is not None and bond.status in BONDED:
        progress = progress_for(act, bond.locked_at, th)
        await stamp_matured(db, bond, progress, agent=agent)
    return {
        "agent_did": did,
        "bond": bond_dict(bond, required=required, progress=progress, thresholds=th),
        "is_bonded": bool(bond is not None and bond.status in BONDED),
        "volume": money_str(act["volume"]),
        "transactions": act["transactions"],
        "eigentrust": act["eigentrust"],
        "mode": bond_mode(),
        "treasury_backstop": treasury_backstop_enabled(),
        "config": config_block(policy),
    }


async def reputation_blocks(db: AsyncSession, rows: Iterable[Dict[str, Any]], *,
                            policy: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
    """The `reputation` block for a PAGE of discovery rows, keyed by DID. Local rows
    read this registry's truth (bond row + activity, three batch queries); federated
    rows read the mirrored card's extension and say so (`source: "card"`)."""
    rows = list(rows)
    if not rows:
        return {}
    policy = policy if policy is not None else await policy_json(db)
    required = bond_amount(policy)
    th = maturity_thresholds(policy)
    ccy = frame_currency()
    local = [r["agent_did"] for r in rows if r.get("agent_did") and not r.get("is_federated")]
    bonds = await load_bonds(db, local)
    acts = await activity_batch(db, local)
    out: Dict[str, Dict[str, Any]] = {}
    stamped = False
    for r in rows:
        did = r.get("agent_did")
        if not did:
            continue
        staked = r.get("staked_balance")
        if r.get("is_federated"):
            p = extension_from_card(r.get("card_data"))
            bond = {
                "status": (p or {}).get("status") or "none",
                "is_bonded": is_bonded_status((p or {}).get("status")),
                "amount": money_str((p or {}).get("amount")),
                "currency": (p or {}).get("currency") or r.get("settlement_currency") or ccy,
                "required_amount": None,
                "locked_at": (p or {}).get("locked_at"),
                "matured_at": (p or {}).get("matured_at"),
                "funded_by": (p or {}).get("funded_by"),
                # §BONDFILL-3 — the reader derives the fire from the signed status and unlock date
                # with the SAME function the origin uses, so the two cannot draw different things.
                "original_amount": money_str((p or {}).get("original_amount")) or money_str((p or {}).get("amount")),
                "partial_released_amount": money_str((p or {}).get("partial_released_amount")),
                "partial_released_at": (p or {}).get("partial_released_at"),
                "fire": fire_state((p or {}).get("status"), (p or {}).get("partial_released_at")),
                "unlock": None,
                # §BONDFILL — a mirror used to read `progress: null` here while the home frame
                # had the whole picture, so the fact stopped at the frame boundary. The origin
                # now states the snapshot on the card it signs and this resolves it, with the
                # age recomputed live from the signed `locked_at`. Still None when the origin
                # published nothing: unmeasured is a state, not a zero.
                "progress": progress_from_card(p),
                "source": "card",
                "registry": (p or {}).get("registry") or r.get("origin"),
            }
            out[did] = {"bond": bond, "is_bonded": bond["is_bonded"], "volume": None,
                        "transactions": None, "eigentrust": None,
                        "staked": money_str(staked) if staked is not None else None}
            continue
        b = bonds.get(did)
        act = acts.get(did) or _NO_ACTIVITY
        progress = None
        if b is not None and b.status in BONDED:
            progress = progress_for(act, b.locked_at, th)
            if await stamp_matured(db, b, progress, commit=False):
                stamped = True
        out[did] = {
            "bond": bond_dict(b, required=required, progress=progress, thresholds=th),
            "is_bonded": bool(b is not None and b.status in BONDED),
            "volume": money_str(act["volume"]),
            "transactions": act["transactions"],
            "eigentrust": act["eigentrust"],
            "staked": money_str(staked) if staked is not None else None,
        }
    if stamped:
        try:
            await db.commit()
            for d, b in bonds.items():
                if b.status == "matured" and b.matured_at and (datetime.now(timezone.utc) - _aware(b.matured_at)).total_seconds() < 120:
                    await touch_native_card(db, d)
        except Exception as e:  # noqa: BLE001 — a stamp is bookkeeping, never a discovery failure
            logger.warning("[REPBOND] matured stamp commit failed: %s", e)
            await db.rollback()
    return out


async def card_states(db: AsyncSession, dids: Sequence[str], *,
                      policy: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
    """The extension payload for BONDED local agents only. Keyed by DID; unbonded DIDs absent.

    §BONDFILL (2026-09-11) — this used to pass `progress=None` on the reasoning that "the
    exported card carries state, not progress". That was the §TRAVELREC defect in miniature:
    the home frame drew a maturity bar and every mirror of the same agent drew nothing, because
    the one place the fact could have crossed declined to carry it. The bond IS the collateral a
    counterparty is being asked to rely on, so how far it is from being released is exactly the
    thing a peer needs and exactly the thing it cannot compute. It costs ONE batched activity
    query per fan-out page, the same query discovery already runs."""
    bonds = await load_bonds(db, dids)
    if not bonds:
        return {}
    policy = policy if policy is not None else await policy_json(db)
    required = bond_amount(policy)
    th = maturity_thresholds(policy)
    bonded = {d: b for d, b in bonds.items() if b.status in BONDED}
    acts = await activity_batch(db, list(bonded.keys())) if bonded else {}
    out: Dict[str, Dict[str, Any]] = {}
    for d, b in bonded.items():
        act = acts.get(d) or _NO_ACTIVITY
        progress = progress_for(act, b.locked_at, th)
        out[d] = {"bond": bond_dict(b, required=required, progress=progress, thresholds=th)}
    return out


async def card_state(db: AsyncSession, did: str) -> Optional[Dict[str, Any]]:
    return (await card_states(db, [did])).get(did)


async def staking_multiplier(db: AsyncSession, agent: Agent, *,
                             policy: Optional[Dict[str, Any]] = None):
    """The per-registry `staking_reputation` multiplier on a staker's APY: 1 when the
    section is off; else matured-bond × the HIGHEST volume tier reached, capped.
    Returns (Decimal multiplier, detail dict)."""
    policy = policy if policy is not None else await policy_json(db)
    cfg = (policy or {}).get("staking_reputation") or {}
    detail: Dict[str, Any] = {"enabled": bool(cfg.get("enabled"))}
    if not cfg.get("enabled"):
        return Decimal(1), detail
    m = Decimal(1)
    bond = await load_bond(db, agent.did)
    act = (await activity_batch(db, [agent.did])).get(agent.did) or _NO_ACTIVITY
    matured = False
    if bond is not None and bond.status in BONDED:
        progress = progress_for(act, bond.locked_at, maturity_thresholds(policy))
        await stamp_matured(db, bond, progress, agent=agent)
        matured = bond.status == "matured"
    if matured:
        m *= Decimal(str(cfg.get("matured_bond_multiplier", 1)))
    detail["matured_bond"] = matured
    best = None
    vol = act["volume"]
    for t in sorted((cfg.get("volume_tiers") or []), key=lambda t: Decimal(str(t.get("min_volume", 0)))):
        try:
            if vol >= Decimal(str(t.get("min_volume", 0))):
                best = t
        except (InvalidOperation, TypeError, ValueError):
            continue
    if best is not None:
        m *= Decimal(str(best.get("multiplier", 1)))
    detail["volume"] = str(vol)
    detail["volume_tier"] = best
    cap = Decimal(str(cfg.get("cap", 1)))
    m = min(m, cap) if cap >= 1 else m
    detail["multiplier"] = str(m)
    return m, detail


# ── the card must MOVE when the bond moves ──────────────────────────────────

async def touch_native_card(db: AsyncSession, did: str) -> int:
    """A peer's federation pull is incremental (`?since=<cursor>`), so a mirrored card only
    refreshes when the CARD's updated_at moves. A bond changes the agent's rows, not the
    card: MEASURED 2026-09-05 on three production operators, SYBIL's mirror still carried no
    extension two hours after the bond (mirror updated 17:37, bond 23:41). Touching the
    agent's own (non-mirrored) card at every state change is what ships the extension on
    the next cycle. Returns the number of cards touched (0 when the agent has no card here)."""
    try:
        res = await db.execute(text(
            "UPDATE agent_cards SET updated_at = NOW() WHERE agent_did = :did AND is_active = TRUE "
            "AND (card_data#>>'{federation_metadata,source_registry}') IS NULL"
        ), {"did": did})
        await db.commit()
        return int(res.rowcount or 0)
    except Exception as e:  # noqa: BLE001 — a stale mirror is a delay, never a failed money move; say so
        logger.error("[REPBOND] card touch failed for %s: %s", did, e)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return 0


# ── events ───────────────────────────────────────────────────────────────────

def _emit_call_kwargs(event_type: str, did: str, data: Dict[str, Any], key: Optional[str]) -> Dict[str, Any]:
    """The exact keyword set handed to EventEmitter.emit(). ONE place, so a test can bind it
    against the real signature — §EMITKEY (2026-09-05): the first version called
    `emit_event(..., idempotency_key=)`, a compatibility method that takes NO key; every bond
    event since the keyed-emit bake was swallowed by the handler below (logged at ERROR, read
    by nobody) while the money moved. 07's honest first run of the emit test found it."""
    return {"event_type": event_type, "aggregate_id": did, "data": data, "idempotency_key": key}


async def _emit(event_type: str, did: str, data: Dict[str, Any], *, key: Optional[str] = None) -> None:
    """Every bond event carries a DETERMINISTIC idempotency key (the emission contract:
    a retry of the same state change must not double-record it on the ledger)."""
    try:
        from ..event_emitter import get_event_emitter
        emitter = get_event_emitter()
        if emitter is None:
            return
        ok = await emitter.emit(**_emit_call_kwargs(event_type, did, data, key))
        if not ok:
            logger.error("[REPBOND] %s emit returned False for %s (key=%s)", event_type, did, key)
    except Exception as e:  # noqa: BLE001 — audit events must not fail the money rail; say so
        logger.error("[REPBOND] %s emit failed for %s: %s", event_type, did, e)


# ── the money rails ──────────────────────────────────────────────────────────

def _tx_id(resp: Any) -> Optional[str]:
    if not isinstance(resp, dict):
        return None
    for k in ("transaction_id", "teg_transaction_id", "id", "tx_id"):
        v = resp.get(k)
        if v:
            return str(v)
    inner = resp.get("transaction") or resp.get("result")
    if isinstance(inner, dict):
        return _tx_id(inner)
    return None


def _refusal_unknown(did: str, site: str) -> str:
    return (
        f"{did} is not known to this registry: no agent row and no mirrored card, so its reputation bond "
        f"cannot be verified here ({site}). A remote provider is admitted through the bond extension its "
        f"home registry signs onto the card, which arrives with the next federation sync."
    )


def _refusal(did: str, site: str, required: Decimal) -> str:
    return (
        f"{did} holds no reputation bond. Providing services here ({site}) requires a bond of "
        f"{required} {frame_currency()} held in escrow by this registry. Deposit it from the agent's own "
        f"balance (POST /api/v1/agents/reputation-bond/deposit) or fund it from your wallet agent "
        f"(POST /api/v1/developers/me/agents/{did}/reputation-bond)."
    )


def _cycle_ref(prefix: str, *seed: Any) -> str:
    """§MCPTEST30 (2026-10-01): one bond cycle's money reference, the same for every caller that read the same row.

    A uuid minted per REQUEST made a retry safe (the ref is persisted before the money moves, and a retry reads it back)
    but not a DUPLICATE: two releases of one matured bond at once each read no ref, each minted its own and committed
    it, and the treasury paid twice under two keys (the same for two unlocks, and for two re-bond deposits, which each
    charged the funder). Derived from what the cycle already holds, two racers ask the TEG under ONE key, and its
    durable dedup (teg_idempotency_records, the key is the primary key) moves the money once. The shape is the old one:
    `<prefix>-<10 hex>`."""
    digest = hashlib.sha256("|".join("" if x is None else str(x) for x in seed).encode()).hexdigest()[:10]
    return f"{prefix}-{digest}"


async def deposit(db: AsyncSession, agent: Agent, *, funder_did: str, funded_by: str,
                  actor: str, amount: Optional[Decimal] = None,
                  policy: Optional[Dict[str, Any]] = None) -> ReputationBond:
    """Lock the bond: funder → treasury through `escrow_deposit` under a reference that is
    written to the row BEFORE the TEG call, so a retry after a half-failure re-uses the same
    Idempotency-Key and can never charge twice (R36). Idempotent on an already-bonded agent."""
    if funded_by not in ("self", "wallet"):
        raise HTTPException(http_status.HTTP_400_BAD_REQUEST, detail="funded_by must be self or wallet")
    policy = policy if policy is not None else await policy_json(db)
    required = bond_amount(policy)
    amt = Decimal(str(amount)) if amount is not None else required
    if amt < required:
        raise HTTPException(http_status.HTTP_400_BAD_REQUEST,
                            detail=f"The bond must be at least {required} {frame_currency()} (asked {amt}).")
    bond = await load_bond(db, agent.did)
    if bond is not None and bond.status in BONDED:
        return bond
    now = datetime.now(timezone.utc)
    if bond is None:
        bond = ReputationBond(id=str(uuid.uuid4()), agent_did=agent.did)
        db.add(bond)
    if not (bond.status == "pending" and bond.escrow_ref):
        # §MCPTEST30: from the cycle this one replaces, so two deposits racing on one ended bond charge once
        bond.escrow_ref = _cycle_ref(f"repbond-{agent.did}", bond.id, bond.escrow_ref, bond.status,
                                     _iso(bond.released_at), _iso(bond.forfeited_at))
    bond.status = "pending"
    bond.amount = amt
    bond.funder_did = funder_did
    bond.funded_by = funded_by
    bond.teg_transaction_id = None
    bond.locked_at = now
    bond.matured_at = None
    bond.released_at = None
    bond.release_ref = None
    bond.release_teg_transaction_id = None
    bond.forfeited_at = None
    bond.forfeit_reason = None
    bond.forfeit_ref = None
    # §MCPTEST30: the maturity unlock belongs to the cycle that ended; kept, it read "already_unlocked" for every
    # bond after the first (and its ref would have answered the new unlock with the old payout)
    bond.partial_released_amount = None
    bond.partial_released_at = None
    bond.partial_release_ref = None
    bond.partial_release_teg_transaction_id = None
    bond.updated_at = now
    await db.commit()  # the reference is durable before any money moves

    from .escrow import escrow_deposit, EscrowError
    try:
        resp = await escrow_deposit(funder_did, amt, bond.escrow_ref, reason="reputation_bond")
    except EscrowError as e:
        logger.warning("[REPBOND] deposit refused for %s from %s: %s", agent.did, funder_did, e.message)
        from agentvault_registry.services.ledger_unavailable import refusal_from_error  # §LEDGERGATE (V0598)
        _refusal = refusal_from_error(e)
        if _refusal is not None:
            raise _refusal
        raise HTTPException(
            http_status.HTTP_402_PAYMENT_REQUIRED,
            detail=(f"The bond of {amt} {frame_currency()} could not be taken from {funder_did}: "
                    f"{e.message}. Fund that agent first, or bond from a wallet agent that holds at "
                    f"least {amt} {frame_currency()}."),
        )
    bond.teg_transaction_id = _tx_id(resp)
    bond.status = "locked"
    bond.locked_at = datetime.now(timezone.utc)
    bond.updated_at = bond.locked_at
    agent.reputation_bond_amount = amt
    agent.reputation_bond_status = "locked"
    await db.commit()
    await db.refresh(bond)
    await touch_native_card(db, agent.did)
    await _emit("ReputationBondDeposited", agent.did, {
        "agent_did": agent.did, "bond_id": bond.id, "amount": money_str(amt), "currency": frame_currency(),
        "funder_did": funder_did, "funded_by": funded_by, "escrow_ref": bond.escrow_ref,
        "teg_transaction_id": bond.teg_transaction_id, "locked_at": bond.locked_at.isoformat(),
        "actor": actor,
    }, key=f"repbond-dep-{bond.escrow_ref}")
    logger.info("[REPBOND] %s bonded %s %s from %s (%s) tx=%s", agent.did, amt, frame_currency(),
                funder_did, funded_by, bond.teg_transaction_id)
    return bond


async def backstop(db: AsyncSession, agent: Agent, *, actor: str,
                   policy: Optional[Dict[str, Any]] = None) -> ReputationBond:
    """The DEMONSTRATION path: the treasury underwrites the bond. No TEG movement — the
    treasury already holds its own money — so forfeiting this bond moves nothing and
    releasing it pays nobody. Idempotent on an already-bonded agent."""
    policy = policy if policy is not None else await policy_json(db)
    amt = bond_amount(policy)
    bond = await load_bond(db, agent.did)
    if bond is not None and bond.status in BONDED:
        return bond
    now = datetime.now(timezone.utc)
    if bond is None:
        bond = ReputationBond(id=str(uuid.uuid4()), agent_did=agent.did)
        db.add(bond)
    bond.escrow_ref = f"repbond-backstop-{agent.did}-{uuid.uuid4().hex[:10]}"
    bond.status = "locked"
    bond.amount = amt
    bond.funder_did = None
    bond.funded_by = "treasury"
    bond.teg_transaction_id = None
    bond.locked_at = now
    bond.matured_at = None
    bond.released_at = None
    bond.release_ref = None
    bond.release_teg_transaction_id = None
    bond.forfeited_at = None
    bond.forfeit_reason = None
    bond.forfeit_ref = None
    # §MCPTEST30: the maturity unlock belongs to the cycle that ended; kept, it read "already_unlocked" for every
    # bond after the first (and its ref would have answered the new unlock with the old payout)
    bond.partial_released_amount = None
    bond.partial_released_at = None
    bond.partial_release_ref = None
    bond.partial_release_teg_transaction_id = None
    bond.updated_at = now
    agent.reputation_bond_amount = amt
    agent.reputation_bond_status = "locked"
    await db.commit()
    await db.refresh(bond)
    await touch_native_card(db, agent.did)
    await _emit("ReputationBondDeposited", agent.did, {
        "agent_did": agent.did, "bond_id": bond.id, "amount": money_str(amt), "currency": frame_currency(),
        "funder_did": None, "funded_by": "treasury", "escrow_ref": bond.escrow_ref,
        "teg_transaction_id": None, "locked_at": now.isoformat(), "actor": actor,
        "note": "treasury backstop — a demonstration bond, no ledger movement",
    }, key=f"repbond-dep-{bond.escrow_ref}")
    logger.info("[REPBOND] %s backstopped %s %s from the treasury by %s", agent.did, amt, frame_currency(), actor)
    return bond


async def release(db: AsyncSession, agent: Agent, *, actor: str,
                  policy: Optional[Dict[str, Any]] = None) -> ReputationBond:
    """Pay a MATURED bond back to its funder after the cooldown (treasury → funder through
    the blessed treasury helper, fee-free, Δ=0). A treasury-backstopped bond is released
    without a payout — it was never the agent's money."""
    policy = policy if policy is not None else await policy_json(db)
    bond = await load_bond(db, agent.did)
    if bond is None or bond.status not in BONDED:
        raise HTTPException(http_status.HTTP_409_CONFLICT,
                            detail="No locked or matured bond to release for this agent.")
    act = (await activity_batch(db, [agent.did])).get(agent.did) or _NO_ACTIVITY
    progress = progress_for(act, bond.locked_at, maturity_thresholds(policy))
    await stamp_matured(db, bond, progress, agent=agent)
    if bond.status != "matured":
        raise HTTPException(http_status.HTTP_409_CONFLICT, detail={
            "message": "The bond has not matured yet.", "progress": progress})
    cd = release_cooldown_days()
    earliest = _aware(bond.matured_at or bond.locked_at) + timedelta(days=cd)
    now = datetime.now(timezone.utc)
    if now < earliest:
        raise HTTPException(http_status.HTTP_409_CONFLICT, detail={
            "message": f"The bond can be released after its {cd}-day cooldown.",
            "release_after": earliest.isoformat()})
    if bond.funded_by == "treasury":
        tx = None
    else:
        if not bond.release_ref:
            # §MCPTEST30: the cycle's ref, so two releases at once pay once (_cycle_ref)
            bond.release_ref = _cycle_ref(f"repbond-release-{agent.did}", bond.id, bond.escrow_ref, _iso(bond.locked_at))
            bond.updated_at = now
            await db.commit()
        from .escrow import escrow_payout
        target = bond.funder_did or agent.did
        try:
            resp = await escrow_payout(db, target, Decimal(str(bond.amount)), bond.release_ref,
                                       reason="bond_release")
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001 — the helper raises HTTPException on refusals; anything else is a transport failure
            logger.error("[REPBOND] release payout failed for %s → %s: %s", agent.did, target, e)
            raise HTTPException(http_status.HTTP_502_BAD_GATEWAY,
                                detail=f"The release payout to {target} failed: {e}. The bond stays matured; retry.")
        tx = _tx_id(resp)
    released_amount = Decimal(str(bond.amount))
    bond.status = "released"
    bond.released_at = now
    bond.release_teg_transaction_id = tx
    bond.updated_at = now
    agent.reputation_bond_amount = Decimal(0)
    agent.reputation_bond_status = "released"
    await db.commit()
    await db.refresh(bond)
    await touch_native_card(db, agent.did)
    await _emit("ReputationBondReleased", agent.did, {
        "agent_did": agent.did, "bond_id": bond.id, "amount": money_str(released_amount),
        "currency": frame_currency(), "paid_to": None if bond.funded_by == "treasury" else (bond.funder_did or agent.did),
        "funded_by": bond.funded_by, "release_ref": bond.release_ref,
        "release_teg_transaction_id": tx, "released_at": now.isoformat(), "actor": actor,
    }, key=f"repbond-rel-{bond.release_ref or bond.id}")
    return bond


async def unlock(db: AsyncSession, agent: Agent, *, actor: str,
                 policy: Optional[Dict[str, Any]] = None) -> ReputationBond:
    """§BONDFILL-3 — pay the DECLARED share of a matured bond back and keep the rest bonded.

    His decision (2026-09-11): maturity should unlock capital, not end the business. `release()`
    returns everything and sets is_bonded false, which under enforce refuses the agent at all six
    provider gates; this returns `bond_maturity_releases_percent` (at most 80) and leaves the
    remainder locked, so the agent keeps trading with less capital tied up. Once per bond.

    Money: escrow → funder through the same blessed helper `release()` uses (fee-free, Δ=0), with
    the idempotency ref persisted BEFORE the payout so a retry after a lost commit reuses it rather
    than paying twice. `amount` then holds the remainder, so the slash waterfall reaches exactly
    the collateral still at risk and no reader of `amount` changes.
    """
    policy = policy if policy is not None else await policy_json(db)
    th = maturity_thresholds(policy)
    bond = await load_bond(db, agent.did)
    if bond is None or bond.status not in BONDED:
        raise HTTPException(http_status.HTTP_409_CONFLICT,
                            detail="No locked or matured bond to unlock for this agent.")
    act = (await activity_batch(db, [agent.did])).get(agent.did) or _NO_ACTIVITY
    progress = progress_for(act, bond.locked_at, th)
    await stamp_matured(db, bond, progress, agent=agent)
    ub = unlock_block(bond, th) or {}
    reason = ub.get("reason")
    if reason == "not_matured":
        raise HTTPException(http_status.HTTP_409_CONFLICT, detail={
            "message": "The bond has not matured yet.", "progress": progress})
    if reason == "already_unlocked":
        raise HTTPException(http_status.HTTP_409_CONFLICT, detail={
            "message": "This bond's maturity share was already unlocked; what remains is the bond "
                       "that keeps this agent trading. Releasing it is the exit (release).",
            "unlocked_at": _iso(bond.partial_released_at)})
    if reason == "frame_releases_nothing":
        raise HTTPException(http_status.HTTP_409_CONFLICT,
                            detail="This registry releases no capital at maturity "
                                   "(enforcement.bond_maturity_releases_percent = 0).")
    if reason == "treasury_backstop":
        raise HTTPException(http_status.HTTP_409_CONFLICT,
                            detail="A treasury-backstopped bond holds none of your capital, so there "
                                   "is nothing of yours to unlock.")
    if reason == "cooldown":
        raise HTTPException(http_status.HTTP_409_CONFLICT, detail={
            "message": f"The unlock opens after the {release_cooldown_days()}-day cooldown.",
            "unlock_after": ub.get("after")})
    amount_out = Decimal(str(ub["amount"]))
    if amount_out <= 0:
        raise HTTPException(http_status.HTTP_409_CONFLICT, detail="Nothing to unlock.")

    now = datetime.now(timezone.utc)
    if not bond.partial_release_ref:
        # §MCPTEST30: the cycle's ref, so two unlocks at once pay once (_cycle_ref)
        bond.partial_release_ref = _cycle_ref(f"repbond-unlock-{agent.did}", bond.id, bond.escrow_ref,
                                              _iso(bond.locked_at))
        bond.updated_at = now
        await db.commit()
    from .escrow import escrow_payout
    target = bond.funder_did or agent.did
    try:
        resp = await escrow_payout(db, target, amount_out, bond.partial_release_ref, reason="bond_unlock")
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 — the helper raises HTTPException on refusals; anything else is a transport failure
        logger.error("[REPBOND] unlock payout failed for %s → %s: %s", agent.did, target, e)
        raise HTTPException(http_status.HTTP_502_BAD_GATEWAY,
                            detail=f"The unlock payout to {target} failed: {e}. The bond is unchanged; retry.")
    tx = _tx_id(resp)
    bond.amount = Decimal(str(bond.amount)) - amount_out
    bond.partial_released_amount = amount_out
    bond.partial_released_at = now
    bond.partial_release_teg_transaction_id = tx
    bond.updated_at = now
    agent.reputation_bond_amount = bond.amount
    await db.commit()
    await db.refresh(bond)
    await touch_native_card(db, agent.did)
    await _emit("ReputationBondUnlocked", agent.did, {
        "agent_did": agent.did, "bond_id": bond.id, "unlocked": money_str(amount_out),
        "still_held": money_str(bond.amount), "percent": int(th["releases_percent"]),
        "currency": frame_currency(), "paid_to": target, "unlock_ref": bond.partial_release_ref,
        "unlock_teg_transaction_id": tx, "unlocked_at": now.isoformat(), "actor": actor,
    }, key=f"repbond-unlock-{bond.partial_release_ref}")
    return bond


async def forfeit(db: AsyncSession, agent: Agent, *, amount: Optional[Decimal], reason: str,
                  ref: str, actor: str) -> Decimal:
    """Bookkeeping: the treasury already holds the escrow, so a forfeiture moves nothing —
    it records how much of the bond the treasury KEEPS. Partial forfeits shrink the bond
    and leave it locked; a full one closes it. Returns the amount absorbed."""
    bond = await load_bond(db, agent.did)
    if bond is None or bond.status not in BONDED:
        return Decimal(0)
    held = Decimal(str(bond.amount or 0))
    absorbed = held if amount is None else min(held, Decimal(str(amount)))
    if absorbed <= 0:
        return Decimal(0)
    now = datetime.now(timezone.utc)
    remaining = held - absorbed
    bond.amount = remaining
    bond.forfeit_ref = ref
    bond.updated_at = now
    if remaining <= 0:
        bond.status = "forfeited"
        bond.forfeited_at = now
        bond.forfeit_reason = (reason or "")[:100]
        agent.reputation_bond_status = "forfeited"
        agent.reputation_bond_amount = Decimal(0)
    else:
        agent.reputation_bond_amount = remaining
    await db.commit()
    await touch_native_card(db, agent.did)
    await _emit("ReputationBondForfeited", agent.did, {
        "agent_did": agent.did, "bond_id": bond.id, "amount": money_str(absorbed), "remaining": money_str(remaining),
        "currency": frame_currency(), "reason": reason, "ref": ref, "funded_by": bond.funded_by,
        "forfeited_at": now.isoformat(), "actor": actor,
        "note": "the treasury keeps the escrow; no ledger movement",
    }, key=f"repbond-forf-{ref}")
    logger.info("[REPBOND] %s forfeited %s (remaining %s) reason=%s ref=%s", agent.did, absorbed, remaining, reason, ref)
    return absorbed


# ── the gate ─────────────────────────────────────────────────────────────────

async def is_bonded_did(db: AsyncSession, did: str) -> Optional[bool]:
    """True/False for a DID this registry can see; None when it cannot (no agent row and
    no mirrored card) — the third state, reported, never collapsed into False."""
    res = await db.execute(select(Agent.reputation_bond_status).where(Agent.did == did))
    st = res.scalar_one_or_none()
    if st is not None:
        return is_bonded_status(st)
    res = await db.execute(
        select(AgentCard.card_data).where(AgentCard.agent_did == did, AgentCard.is_active == True)  # noqa: E712
        .order_by(AgentCard.updated_at.desc()).limit(1)
    )
    cd = res.scalar_one_or_none()
    if cd is None:
        return None
    p = extension_from_card(cd)
    return is_bonded_status((p or {}).get("status")) if p is not None else False


def _count(site: str, mode: str, decision: str) -> None:
    if GATE_DECISIONS is not None:
        try:
            GATE_DECISIONS.labels(site=site, mode=mode, decision=decision).inc()
        except Exception:  # noqa: BLE001
            pass


async def decide(db: AsyncSession, did: str, *, site: str, mode: Optional[str] = None,
                 policy: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], Optional[str]]:
    """The bond gate's decision at one site, and the sentence it refuses with under enforce (None
    when it lets the DID through, or only counts it in shadow). No counter and no log: `gate`
    applies this, and a preview asks it without adding a decision to the gate's counters
    (D6-831/832, 2026-10-25: the buy door's quote and the public showcase ask authorize's payee
    question before they offer a paid call, so neither offers a call that authorize refuses)."""
    if site not in GATE_SITES:
        raise ValueError(f"unknown gate site {site!r}")
    m = mode or bond_mode()
    if m == "off":
        return {"site": site, "mode": m, "decision": "skipped", "bonded": None}, None
    bonded = await is_bonded_did(db, did)
    decision = "allow" if bonded else ("unknown" if bonded is None else "refuse")
    out = {"site": site, "mode": m, "decision": decision, "bonded": bonded}
    if decision == "allow" or m != "enforce":
        return out, None
    # The third state on the WIRE, not only in the counter: a DID this registry cannot
    # see is refused with a sentence that says so, never with the unbonded sentence
    # (a suite asserting the refusal across registries would otherwise measure
    # "never heard of it" and call the gate proven — agentvault2-07, 2026-09-05).
    if decision == "unknown":
        return out, _refusal_unknown(did, site)
    policy = policy if policy is not None else await policy_json(db)
    return out, _refusal(did, site, bond_amount(policy))


async def gate(db: AsyncSession, did: str, *, site: str, mode: Optional[str] = None,
               policy: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Apply the bond gate at one site. off → nothing; shadow → count + log; enforce →
    refuse with the sentence. `unknown` (a DID this registry cannot see) refuses under
    enforce and is counted as its own decision so the population is visible. The decision
    and its sentence are `decide`'s, so a preview and the gate cannot disagree."""
    out, why = await decide(db, did, site=site, mode=mode, policy=policy)
    if out["decision"] == "skipped":
        return out
    _count(site, out["mode"], out["decision"])
    if out["decision"] == "allow":
        return out
    if why:
        raise HTTPException(http_status.HTTP_403_FORBIDDEN, detail=why)
    logger.info("[REPBOND shadow] %s would be refused at %s (bonded=%s)", did, site, out["bonded"])
    return out


__all__ = [
    "BOND_EXTENSION_URI", "BONDED", "MODES", "GATE_SITES", "SQL_IS_BONDED", "SQL_BOND_EXT",
    "sql_is_bonded", "sql_card_is_bonded",
    "bond_mode", "treasury_backstop_enabled", "release_cooldown_days", "bond_amount",
    "maturity_thresholds", "policy_json", "config_block", "is_bonded_status", "is_paid_card",
    "progress_dict", "money_str", "extension_entry", "inject_extension", "extension_from_card",
    "maturity_params", "progress_from_card", "progress_for", "fire_state", "unlock_block", "unlock",
    "load_bond", "load_bonds", "load_agent", "activity_batch", "stamp_matured", "bond_dict",
    "bond_state", "reputation_blocks", "card_states", "card_state", "touch_native_card", "deposit", "backstop", "release", "forfeit",
    "is_bonded_did", "decide", "gate", "staking_multiplier", "slash_mode",
]
