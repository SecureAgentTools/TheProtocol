"""
§SHOWCASEVISITOR — one agent per visitor for the public showcase chat.

WHY THIS EXISTS. The showcase chat used to hand every anonymous visitor a token
for ONE shared identity per frame. That made two things impossible at once:

  * ISOLATION. Every visitor spoke as the same DID, so one visitor's threads and
    one visitor's money were readable as another's. A `session_ref` scoped it on
    the CLIENT, which is a convention, not a boundary.
  * A HONEST LEDGER. The chat sits beside a live event ledger filtered with the
    Bridge's own `involvesDids()` predicate. Filtering on a SHARED did matches
    every visitor's events, so the filter was correct and still read as
    unfiltered. Filtering on an identity that belongs to exactly one visitor is
    what makes "these are the events YOUR actions caused" a true sentence.

Both are the same fix: give the visitor their own agent.

THE SHAPE, and why it is not a new money rail (rule 14).
  FUNDER  = the frame's existing showcase payer, 10M funded, configured in this
            frame's own gitignored env. Its credentials NEVER leave the server —
            that is the change: the browser used to hold this token and now
            never does.
  VISITOR = a real agent SPAWNED under the funder through the EXISTING
            `POST /agents/spawn` L4 birth rail, over loopback, with the funder's
            own JWT. No developer credential, no bootstrap token, no new
            identity-creation code: the child inherits the parent's owning
            developer by construction.

WHY SPAWN AND NOT A DEVELOPER CREATE PATH. Spawn gives three things for free
that a hand-rolled path would have had to invent:
  1. `child authority ⊆ parent's CURRENT effective authority`, re-derived per
     request. A visitor can never hold what the funder does not.
  2. A birth token row whose `issuer_agent_did` is the funder — an AUTHORITATIVE
     list of "agents this showcase created", which survives a rename and is what
     the sweeper enumerates. A naming convention would not survive a rename and
     could not be trusted to bound a delete.
  3. `expires_at` on that same row IS the visitor's TTL. No second clock to
     drift.

🔴 THE SWEEPER MUST BE SCOPED BY ISSUER, NEVER BY `birth=true`. Measured on
frame-c before this was written: 4,307 birth tokens already exist, spawned by
the EigenTrust simulation. A sweeper keyed on "is a birth token" would have
enumerated 4,307 live simulation agents and tried to retire them. Every query
here is scoped to `issuer_agent_did = <funder>`.

🔴 THE FUNDER'S ALLOWLIST IS THE REASON FUNDING NEEDS A DANCE. The funder runs
`counterparty_mode='allowlist'` over exactly the 11 showcase service agents, so
by construction it CANNOT pay a brand-new visitor agent — the funding transfer
would be refused, correctly. Rather than widen the funder to `any` (which is the
one control standing between a leaked funder credential and the 10M), the child
DID is appended to the allowlist, paid, and removed again, each in one atomic
statement so concurrent visitors cannot corrupt the array. A crash between pay
and remove leaves a stray entry that only ever permits paying a dead throwaway;
the sweeper prunes it.
"""
from __future__ import annotations

import datetime as _dt
import logging
import os
import uuid
from decimal import Decimal
from typing import Any, Dict, List, Tuple

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

LOOPBACK = "http://localhost:8000"
API = "/api/v1"

# The child gets the funder's economic permissions and NOT `authz.delegate`, so
# a visitor can never spawn further agents. `no_redelegate` on the birth token
# says the same thing a second way, at the capability layer.
# §SHOWCASESTOCKS — `exchange.trade` added, which is the clerk recipe verbatim:
# `sim_eigentrust.py:495` spawns one execution-clerk per registry on a birth
# token carrying exchange.trade + ipo + teg.transfer, no_redelegate, 24h. The
# clerk's own JWT is base-only, so `/exchange/orders` clears ONLY via
# caveat ∩ ISSUER authority — suspend the parent and every clerk goes dark the
# same request. Without this the showcase could only ever buy from the IPO float
# at the founding price (SMKD: float 2.5 while the market trades at 51), which
# is what made the demo look fake.
VISITOR_PERMISSIONS = ["a2a.pay", "exchange.ipo", "exchange.trade",
                       "teg.transfer", "teg.transfer_xreg"]


def _env_f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except (TypeError, ValueError):
        return default


def _env_i(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except (TypeError, ValueError):
        return default


# §MCPTEST30 (V0640): the showcase endpoints' refusal names which of its two off states it is, both keeping the first
# sentence the API tester's classifier and the console read. A registry that sets no SHOWCASE_CATALOG_JSON holds the
# built-in catalog, which describes another deployment, so main.py turns the showcase off there (§CARDLINK); nobody
# switched it off, and "disabled" alone read as a switch (the sandbox frames, 2026-10-24: the console suite's buy door
# NOT MEASURED on "The showcase is disabled on this deployment." with SHOWCASE_ENABLED unset on both).
SHOWCASE_OFF = "The showcase is disabled on this deployment."


def showcase_off_sentence(foreign_catalog: bool) -> str:
    """The refusal: switched off here (SHOWCASE_ENABLED), or no showcase services of this registry's own."""
    if foreign_catalog:
        return (SHOWCASE_OFF[:-1] + ": this registry has no showcase services of its own (its built-in catalog "
                "describes another deployment).")
    return SHOWCASE_OFF


# §MCPTEST30 (V0641, D6-831, agentvault2-66 2026-10-25): which paid showcase calls this frame can make, asked as the
# call asks it, so the catalogue (/public/showcase/agents) and the call (/public/showcase/call) say the same thing.
# Measured on sbx-alpha 2026-10-25: a frame with no showcase payer listed a paid agent, its call skipped authorize, the
# agent answered 402, and the call was relayed to SHOWCASE_RELAY_URL's default, production EU, which paid its own agent
# 0.5 ECU while the sandbox page said "0.5 SBXA SETTLED". A relay is now only where a deployment names one, and a paid
# entry this frame cannot pay for is listed without a run, with the reason the call refuses with.
NO_PAYER = ("This frame has no showcase payer of its own and names no showcase relay, so a paid showcase call "
            "cannot be made here.")


def relay_base() -> str:
    """The showcase relay this deployment names (SHOWCASE_RELAY_URL), or "" for none: the default since V0641 (it was
    https://api.theprotocol.cloud, Frame A's when it hosted every showcase agent; EU and ASIA set it empty)."""
    return (os.getenv("SHOWCASE_RELAY_URL", "") or "").strip().rstrip("/")


def calls_tail(relay: str) -> str:
    """What a frame with no showcase identity can still do with a service call, said as it is."""
    if relay:
        return f"Service calls still work here and are relayed to {relay}."
    return "Paid service calls cannot be made here either: this frame names no showcase relay."


def entry_paid(info: Any) -> bool:
    """A showcase entry that charges (a price above zero); a price that is not a number is not free."""
    try:
        return Decimal(str((info or {}).get("price") or "0")) > 0
    except (ArithmeticError, TypeError, ValueError):
        return True


async def call_refusals(db: Any, keys: List[str], *, agents: Dict[str, Any], dids: Dict[str, Any], has_payer: bool,
                        relay: str, payee_refusal: Any) -> Dict[str, Tuple[int, str]]:
    """key -> (HTTP status, sentence) for each paid entry this frame cannot make a call to; an entry it can call is
    absent, and a free entry needs neither check. The payee is asked authorize's own question (`payee_refusal`, from
    routers.a2a_payment: the bond, then enforcement; 403 with authorize's sentence), then whether this frame can pay at
    all (a payer of its own, or a relay it names; 503 otherwise)."""
    out: Dict[str, Tuple[int, str]] = {}
    paid = [k for k in keys if entry_paid(agents.get(k) or {})]
    for k in paid:
        did = dids.get(k)
        why = await payee_refusal(db, did) if did else None
        if why:
            out[k] = (403, why)
    if not has_payer and not relay:
        for k in paid:
            out.setdefault(k, (503, NO_PAYER))
    return out


def visitor_enabled() -> bool:
    """Default ON, but inert without a funder: the endpoint refuses honestly on a
    frame that has no showcase payer of its own, the same way the session rail
    already does. A flag that is on where the thing cannot work is a flag that
    lies."""
    return (os.getenv("SHOWCASE_VISITOR_ENABLED", "true") or "true").strip().lower() in (
        "1", "true", "yes", "on")


def visitor_config() -> Dict[str, Any]:
    return {
        # 1000 on his instruction: "you can fund the account with 1000! not 10.
        # its fine." 3 was too tight to be a showcase — an IPO share at 26 BVT
        # was already out of reach, so half the menu refused on funds and the
        # page taught the reader that nothing works. The containment was never
        # the float anyway: it is the counterparty allowlist and the per-tx cap.
        "float": _env_f("SHOWCASE_VISITOR_FLOAT", 5000.0),
        "ttl_seconds": _env_i("SHOWCASE_VISITOR_TTL_SECONDS", 7200),      # 2h
        # 2026-08-26, his instruction: "we increase the cap to 5000 every
        # session gets 5000." The per-tx cap now equals the float, so anything
        # the visitor can afford is buyable — SLG (~1069) included. Containment
        # is unchanged and never was the number: the counterparty allowlist
        # (11 showcase agents + 3 AGORA gateways) is what a leaked visitor
        # token runs into, plus the per-day cap and the TTL sweep.
        # Raised with the float so real listings are reachable (SLG trades at
        # ~26 BVT). Still a cap, still per-day bounded, still allowlisted.
        # Measured by buying every listing once: a 100 cap refused SYBIL (105),
        # SPLT and SLG purely on the cap, which reads as "broken" rather than
        # "bounded". 600 clears everything the float can actually afford; SLG at
        # ~1069 is over the float itself and is stated as such rather than
        # failing on click.
        "max_per_tx": _env_f("SHOWCASE_VISITOR_MAX_PER_TX", 5000.0),
        "max_per_day": _env_f("SHOWCASE_VISITOR_MAX_PER_DAY", 10000.0),
        "rate_per_hour": _env_i("SHOWCASE_VISITOR_RATE_PER_HOUR", 30),
        "sweep_interval": _env_i("SHOWCASE_VISITOR_SWEEP_INTERVAL", 900),  # 15m
        "sweep_batch": _env_i("SHOWCASE_VISITOR_SWEEP_BATCH", 25),
    }


# ── the funder's allowlist, opened and closed around one payment ──────────────
async def allow_add(db: AsyncSession, funder_did: str, child_did: str) -> None:
    await db.execute(text("""
        UPDATE agent_spend_policies
           SET counterparty_allow = array_append(COALESCE(counterparty_allow, '{}'), :c)
         WHERE agent_did = :f
           AND NOT (:c = ANY(COALESCE(counterparty_allow, '{}')))
    """), {"f": funder_did, "c": child_did})
    await db.commit()


async def allow_remove(db: AsyncSession, funder_did: str, child_did: str) -> None:
    await db.execute(text("""
        UPDATE agent_spend_policies
           SET counterparty_allow = array_remove(counterparty_allow, :c)
         WHERE agent_did = :f
    """), {"f": funder_did, "c": child_did})
    await db.commit()


# The AGORA gateways. A passport buy funds the VENUE's gateway over
# /teg/send, so without these every foreign purchase died at
# `counterparty_not_allowlisted` — measured on BSEA, EAST, FLUX and GRLD. These
# are system accounts owned by the venue rail, not arbitrary payees, so
# allowlisting them widens nothing a visitor could exploit: the money can still
# only reach a showcase agent or a venue gateway.
GATEWAY_DIDS = [
    "did:theprotocol:agora-gateway-avt",
    "did:theprotocol:agora-gateway-bvt",
    "did:theprotocol:agora-gateway-jday",
]


async def _known_gateways(db: AsyncSession) -> List[str]:
    """Every AGORA deposit gateway this registry knows, plus the three frame-wide ones.

    §VENUEGW 2026-08-26 — venue gateways are now per-VENUE
    (`agora-gateway-op-london-avt`), so a hardcoded list of three currencies stopped
    covering the cloud-ops the moment they became real venues, and every buy there died
    at `counterparty_not_allowlisted`. Read them instead: a gateway is self-declaring
    (`card_data.agora_gateway`), so the allowlist grows exactly as the network does and
    never lists a payee this registry has not actually seen a card for.

    Deliberately NOT a wildcard in the matcher — `counterparty_not_allowlisted` stays an
    exact-membership test, so what a visitor may pay is still an enumerable list.
    """
    try:
        rows = (await db.execute(text(
            "SELECT agent_did FROM agent_cards "
            "WHERE card_data->>'agora_gateway' = 'true' AND is_active = true"
        ))).scalars().all()
    except Exception:
        rows = []
    return sorted({*GATEWAY_DIDS, *(str(r) for r in rows if r)})


async def write_child_policy(db: AsyncSession, child_did: str, allow: List[str],
                             cfg: Dict[str, Any]) -> None:
    """The visitor gets its OWN spend policy, the same shape the shared payer has
    had all along — per-tx cap, per-day cap, hourly rate, and an allowlist of the
    showcase agents. Containment does not depend on the token staying secret."""
    await db.execute(text("""
        INSERT INTO agent_spend_policies
            (agent_did, max_per_tx, max_per_day, rate_per_hour,
             counterparty_mode, counterparty_allow, updated_at)
        VALUES (:d, :tx, :day, :rate, 'allowlist', :allow, now())
        ON CONFLICT (agent_did) DO UPDATE
            SET max_per_tx = EXCLUDED.max_per_tx,
                max_per_day = EXCLUDED.max_per_day,
                rate_per_hour = EXCLUDED.rate_per_hour,
                counterparty_mode = 'allowlist',
                counterparty_allow = EXCLUDED.counterparty_allow,
                updated_at = now()
    """), {"d": child_did, "tx": cfg["max_per_tx"], "day": cfg["max_per_day"],
           "rate": cfg["rate_per_hour"], "allow": list(allow) + await _known_gateways(db)})
    await db.commit()


# ── onboarding, narrated ─────────────────────────────────────────────────────
def _step(key: str, label: str, detail: str, ok: bool = True) -> Dict[str, Any]:
    return {"key": key, "label": label, "detail": detail, "ok": ok}


async def onboard_visitor(
    db: AsyncSession,
    funder_jwt: str,
    funder_did: str,
    showcase_dids: List[str],
    currency: str,
) -> Tuple[bool, Dict[str, Any]]:
    """Create + scope + fund one visitor agent. Returns (ok, payload).

    The payload carries a `steps[]` narration because the Commander's ruling is
    that the onboarding is PART OF THE DEMONSTRATION and must be visible in the
    chat: identity created, authority scoped, funded by the showcase agent,
    ready. A visitor who watches an agent be born, bounded and funded in four
    lines has understood more of this platform than any paragraph on the page.

    🔴 The child's `client_secret` is deliberately NOT returned. The browser
    receives a minutes-long JWT and nothing else. A secret in a response is a
    secret in a log, in a screenshot, and in a bug report.
    """
    cfg = visitor_config()
    steps: List[Dict[str, Any]] = []
    ttl = int(cfg["ttl_seconds"])

    # 1 ── mint the identity through the existing L4 birth rail
    try:
        async with httpx.AsyncClient(timeout=25.0) as c:
            r = await c.post(
                f"{LOOPBACK}{API}/agents/spawn",
                headers={"Authorization": f"Bearer {funder_jwt}"},
                json={
                    "name": f"Showcase visitor {uuid.uuid4().hex[:6]}",
                    "permissions": VISITOR_PERMISSIONS,
                    "ttl_seconds": ttl,
                    "max_per_tx": cfg["max_per_tx"],
                    "counterparty_allow": showcase_dids,
                    "no_redelegate": True,
                },
            )
        if r.status_code != 200:
            detail = (r.json() or {}).get("detail") if r.headers.get(
                "content-type", "").startswith("application/json") else r.text[:200]
            logger.warning("[ShowcaseVisitor] spawn failed %s: %s", r.status_code, detail)
            return False, {"error": "Could not create a showcase agent right now.",
                           "reason": str(detail)[:200],
                           "steps": [_step("identity", "Create an agent",
                                           f"The registry refused: {detail}", ok=False)]}
        spawned = r.json()
    except Exception as e:  # noqa: BLE001
        logger.warning("[ShowcaseVisitor] spawn error: %s", e)
        return False, {"error": "Could not create a showcase agent right now.",
                       "steps": [_step("identity", "Create an agent", str(e)[:160], ok=False)]}

    child_did = spawned["child_did"]
    child_cid = spawned["client_id"]
    child_secret = spawned["client_secret"]
    # Named for what it IS. The Commander spotted `AgentSpawned` in the ledger
    # and read the mechanic off it correctly: this is a capability-scoped
    # SUB-AGENT, born under the showcase agent through the L4 birth rail, not a
    # fresh top-level account. That is the interesting part and the label should
    # say so rather than flatten it to "created".
    steps.append(_step("identity", "Sub-agent spawned",
                       f"{child_did} — a real identity, born under the showcase agent "
                       f"({funder_did.split(':')[-1]}) on an L4 birth token. Its authority can "
                       f"never exceed its parent's, and revoking the parent revokes it."))

    # 2 ── its own spend policy: the boundary that does not depend on secrecy
    try:
        await write_child_policy(db, child_did, showcase_dids, cfg)
        steps.append(_step(
            "authority", "Authority scoped",
            f"May pay only the {len(showcase_dids)} showcase agents and the market's "
            f"settlement gateways, at most "
            f"{cfg['max_per_tx']:g} {currency} per payment and {cfg['max_per_day']:g} "
            f"{currency} per day. It cannot delegate, cannot trade, and cannot pay "
            f"any other address."))
    except Exception as e:  # noqa: BLE001
        await db.rollback()
        logger.warning("[ShowcaseVisitor] child policy write failed for %s: %s", child_did, e)
        # An unscoped child must not be handed out. Say so and stop.
        return False, {"error": "Could not scope the showcase agent, so it was not issued.",
                       "steps": steps + [_step("authority", "Authority scoped",
                                               str(e)[:160], ok=False)]}

    # 3 ── fund it FROM THE SHOWCASE AGENT, never from the treasury
    amount = f"{Decimal(str(cfg['float'])):f}"
    funded = False
    try:
        await allow_add(db, funder_did, child_did)
        async with httpx.AsyncClient(timeout=25.0) as c:
            t = await c.post(
                f"{LOOPBACK}{API}/teg/transfer",
                headers={"Authorization": f"Bearer {funder_jwt}"},
                json={"receiver_agent_id": child_did, "amount": amount,
                      "message": "showcase visitor float"},
            )
        funded = t.status_code in (200, 201)
        if funded:
            steps.append(_step(
                "funding", "Funded by the showcase agent",
                f"{amount} {currency} moved from the showcase agent to this new agent. "
                f"Real money on the public ledger — not a simulation, and not minted: "
                f"it came out of an existing balance."))
        else:
            body = t.text[:200]
            logger.warning("[ShowcaseVisitor] funding failed %s: %s", t.status_code, body)
            steps.append(_step("funding", "Funding refused",
                               f"The transfer was refused ({t.status_code}). The agent exists "
                               f"and is scoped, but has no balance yet, so paid calls will "
                               f"fail until it is funded.", ok=False))
    except Exception as e:  # noqa: BLE001
        logger.warning("[ShowcaseVisitor] funding error: %s", e)
        steps.append(_step("funding", "Funding refused", str(e)[:160], ok=False))
    finally:
        # Always close the window, including on the failure path.
        try:
            await allow_remove(db, funder_did, child_did)
        except Exception as e:  # noqa: BLE001
            logger.warning("[ShowcaseVisitor] allowlist close failed for %s: %s — "
                           "the sweeper will prune it", child_did, e)

    # 4 ── a token for the browser. The secret stays here.
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            tok = await c.post(f"{LOOPBACK}{API}/auth/agent/token",
                               data={"username": child_cid, "password": child_secret})
        if tok.status_code != 200:
            return False, {"error": "The agent was created but could not be signed in.",
                           "steps": steps + [_step("ready", "Sign in", "Token mint failed.",
                                                   ok=False)]}
        tj = tok.json()
    except Exception as e:  # noqa: BLE001
        return False, {"error": "The agent was created but could not be signed in.",
                       "steps": steps + [_step("ready", "Sign in", str(e)[:160], ok=False)]}

    expires_at = (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(seconds=ttl))
    steps.append(_step(
        "ready", "Ready",
        f"Signed in as this agent. It is yours for {ttl // 3600}h, after which the "
        f"registry sweeps it: any balance left is returned and the identity is retired."))

    return True, {
        "agent_did": child_did,
        "access_token": tj.get("access_token"),
        "token_type": "bearer",
        "expires_in": tj.get("expires_in"),
        "session_ref": f"scv-{uuid.uuid4().hex[:16]}",
        "shared_identity": False,
        "parent_did": funder_did,
        "funded": funded,
        "float": amount if funded else "0",
        "currency": currency,
        "expires_at": expires_at.isoformat(),
        "scope": VISITOR_PERMISSIONS,
        "cannot": ["pay any address outside the showcase allowlist",
                   "spawn or delegate further agents",
                   "staking.manage", "exchange.trade"],
        "limits": {"max_per_tx": cfg["max_per_tx"], "max_per_day": cfg["max_per_day"],
                   "rate_per_hour": cfg["rate_per_hour"]},
        "steps": steps,
        "notice": ("This agent is yours alone for this session. It holds real balance on "
                   "the public ledger, it may pay only the showcase agents, and every "
                   "payment is capped. When it expires the registry returns what is left "
                   "and retires the identity."),
    }
