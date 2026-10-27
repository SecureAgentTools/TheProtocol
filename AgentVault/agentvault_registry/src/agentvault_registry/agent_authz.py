"""IRONKEY agent authorization — role→permission catalog + resolver + mode switch.

Fleet-wide enforcement lives in the Python ``AGENT_RBAC_MODE`` env switch (NOT OPA — OPA
is reg-a-only and can only *tighten*). Modes:
  * ``off``     — inert; today's behavior, byte-equivalent (the default).
  * ``shadow``  — compute the decision, log a would-deny, but ALLOW (deny nothing).
  * ``enforce`` — deny with a 403 when the permission/spend check fails.

Δ-irrelevant by construction: every check fires PRE-escrow; a denial is a clean 403 with
no ledger footprint. This module owns the role catalog + permission resolution; the
``require_agent_permission`` dependency factory lives in ``security.py`` (next to
``require_admin_flag``, the developer-side analog it mirrors).
"""
from __future__ import annotations

import logging
import os
from typing import Set

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ── Permission taxonomy (~18 ``domain.verb`` strings, derived from the real surface) ──
# read.profile + enforcement.self are BASE (granted to every authenticated agent).
ALL_PERMISSIONS: Set[str] = {
    "read.profile", "enforcement.self", "fx.quote",
    "teg.transfer", "teg.transfer_xreg", "teg.system_transfer", "staking.manage",
    "exchange.trade", "exchange.ipo", "exchange.vote",
    "gov.propose", "gov.vote",
    "a2a.pay", "a2a.collect",
    "contracts.engage", "disputes.file", "reputation.signal", "identity.mtls",
    # L4 — the meta-permission: may this agent issue/attenuate capability tokens to
    # sub-agents? Deliberately NOT in any normal role (only legacy-full carries it, and
    # explicit grant). "May delegate" is exactly the DeepMind meta-permission — an agent
    # that can act is not thereby an agent that can hand its keys onward.
    "authz.delegate",
    # PHONE FABRIC (2026-07-07) — may this agent drive a phone (computer-use)? High-blast,
    # like authz.delegate: NOT in any normal role — legacy-full + explicit grant only. Every
    # phone session runs inside an L4 capability token (allowed_apps/budget/ttl/revoke_subtree).
    "phone.use",
    # THE GUILD (org consent, 2026-07-18) — may this agent bind its ORGANIZATION in a firm
    # bid (the org treasury collects the payout AND the reputation)? Consulted ONLY via
    # ``org:``-principal delegation grant rows (the org itself consents, GUILD_ORG_BID_MODE) —
    # holding it via a role, including legacy-full, does NOT authorize a firm bid.
    "guild.bid_for_org",
    # §ORGSPEND (2026-08-29, Commander's design) — may this actor COMMISSION work in the
    # org's name (post a guild order whose bounty leaves the ORG TREASURY)? The org-consent
    # sibling of guild.bid_for_org: bid_for_org binds the org as WORKER, post_for_org binds
    # it as CLIENT. Sits in the org ADMIN slice (org_authz) and is conferred through the same
    # org: grant rail; the dev-driven work-order door additionally requires org-admin ROLE
    # and every draw passes the procurement cap (org_treasury._procurement_cap_or_raise).
    "guild.post_for_org",
    # CI/CD under capability (★4, 2026-07-18) — may this actor trigger a deployment of an
    # agent it does not own, via an attenuated capability token? Adding it to the taxonomy
    # makes it caveat-able + delegable for free (filtered against ALL_PERMISSIONS at both
    # issue and resolve). Not in any normal role — granted/delegated explicitly, so "who may
    # ship this agent" becomes an attenuable, revocable grant instead of all-or-nothing.
    # ⚠ RESERVED (2026-07-24 wiring audit S7): deployments are DEV-tier today — no agent-tier
    # deploy endpoint exists, so NO gate consults this yet. Caveating it into a token is
    # currently inert; it activates when an agent-tier deploy surface ships.
    "cicd.deploy",
    # GÖDEL FORGE (2026-07-19) — the self-improving-harness meta-permissions. All grant-only
    # (NOT in any normal role; legacy-full auto-carries via set(ALL_PERMISSIONS)) so a
    # self-modifying agent commits variants strictly under its birth-token caveats:
    #   cicd.version         — may this agent commit a NEW VERSION of its own code line
    #   bundle.write         — may this agent FORK/write a bundle (archive a variant)
    #   forge.evolve_for_org — org-consent (org: grant only): may this agent spawn+eval
    #                          variants ON BEHALF OF its lineage org (the arena admission gate,
    #                          mirrors guild.bid_for_org — a role, incl. legacy-full, never suffices)
    #   forge.verify_for_org — org-consent: may this agent serve as a code_patch VERIFIER for
    #                          its Verifier-Guild org (staked; N-of-M quorum)
    #   forge.royalty_admin  — may this actor administer a lineage's royalty_bps (org-admin path)
    #                          ⚠ RESERVED (2026-07-24 audit S7): the royalty-PATCH surface is
    #                          DEV/org-admin-tier — no agent-tier gate consults this yet.
    #                          (Fork-time royalty_bps under bundle.write is BY DESIGN: the
    #                          forker prices their own child, cap 500, child-only stamp.)
    "cicd.version",
    "bundle.write",
    "forge.evolve_for_org",
    "forge.verify_for_org",
    "forge.royalty_admin",
    # CONTRACT SPINE (2026-07-25) — grant-only (NOT in any normal role; legacy-full auto-carries):
    #   contract.template.publish — may this agent create/version/PUBLISH/fork contract templates
    #                               (publishing is a marketplace act; instantiating needs only
    #                               contracts.engage — it just mints an ordinary contract offer)
    "contract.template.publish",
}
# teg.system_transfer is deliberately NOT in any of the 7 normal roles — only
# `legacy-full` carries it (grandfather). A pre-existing over-permission: /teg/system-transfer
# is agent-callable today; gating it means post-ratchet least-privilege agents can't reach it.

# Permissions granted to EVERY authenticated agent regardless of role (own-state reads).
BASE_PERMISSIONS: Set[str] = {"read.profile", "enforcement.self"}

# ── Role → permission map (code constant; served verbatim via /authz/catalog) ──
ROLE_PERMISSIONS: dict[str, Set[str]] = {
    "observer": BASE_PERMISSIONS | {"fx.quote"},
    "trader": BASE_PERMISSIONS | {"fx.quote", "teg.transfer", "teg.transfer_xreg",
                                  "exchange.trade", "exchange.ipo"},
    "staker": BASE_PERMISSIONS | {"staking.manage"},
    # identity.mtls (§EXTMTLS 2026-08-09) sits on BOTH sides of an A2A call: the
    # provider terminating peer connections needs a SPIFFE identity as much as the
    # client opening them. It was previously carried ONLY by legacy-full, so every
    # agent created after IRONKEY went to enforce was refused mTLS enrollment
    # outright. Deliberately NOT in BASE_PERMISSIONS: enrolling issues a
    # credential, so an observer/staker/canary that never speaks A2A should not
    # gain it silently. Deny-only either way — it gates enrollment, not money.
    "service-provider": BASE_PERMISSIONS | {"a2a.collect", "contracts.engage",
                                            "reputation.signal", "disputes.file",
                                            "identity.mtls"},
    "client": BASE_PERMISSIONS | {"a2a.pay", "teg.transfer", "contracts.engage",
                                  "disputes.file", "identity.mtls"},
    "governor": BASE_PERMISSIONS | {"gov.propose", "gov.vote", "exchange.vote"},
    "canary": BASE_PERMISSIONS | {"teg.transfer", "teg.transfer_xreg"},
    # §GATEWAYROLE 2026-09-24: the AGORA exchange gateway signs every repatriation AS ITSELF (the deposit gateway
    # sending a seller's proceeds home), so under enforce it needs exactly this. Granted at birth and healed by
    # services/exchange_passport.ensure_gateway_role. The same authority as `canary`, named for what it is.
    "gateway": BASE_PERMISSIONS | {"teg.transfer", "teg.transfer_xreg"},
    # Grandfather role assigned to all existing agents by migration 0107 — every
    # grantable permission. The ratchet to least-privilege replaces it explicitly.
    "legacy-full": set(ALL_PERMISSIONS),
}

# D6-270: a developer delegates (principal `dev:<id>`) exactly the authority it may give its own agent directly
# through the access API: every role but the grandfather `legacy-full`, plus the one bare switch an owner toggles
# (`authz.delegate`, routers/agent_authz_api.UI_GRANTABLE_PERMISSIONS). The platform-reserved permissions
# (teg.system_transfer, phone.use, contract.template.publish, the org-consent and forge ones) are no developer's to
# hand out, and a developer's grant reaches only an agent that developer created.
DEV_DELEGATABLE_PERMISSIONS: frozenset = frozenset(
    set().union(*(perms for role, perms in ROLE_PERMISSIONS.items() if role != "legacy-full")) | {"authz.delegate"}
)


def agent_rbac_mode() -> str:
    """``off`` | ``shadow`` | ``enforce`` — default ``off`` (byte-inert)."""
    m = os.getenv("AGENT_RBAC_MODE", "off").strip().lower()
    return m if m in ("off", "shadow", "enforce") else "off"


def agent_delegation_mode() -> str:
    """L3/L4 switch — ``off`` | ``shadow`` | ``enforce`` (default ``off``, byte-inert).

    Separate from ``AGENT_RBAC_MODE`` so delegation grants + capability tokens can be
    staged independently of the base role/spend enforcement. ``off`` → delegation grants
    and capability caveats are NEVER consulted (today's behavior). ``shadow`` → resolve
    and log deltas but do not let a capability *tighten* anything. ``enforce`` → capability
    tokens intersect (can only reduce) an agent's authority, delegation grants extend it.
    """
    m = os.getenv("AGENT_DELEGATION_MODE", "off").strip().lower()
    return m if m in ("off", "shadow", "enforce") else "off"


async def resolve_delegated_permissions(
    db: AsyncSession, agent_did: str, act_principal: str | None
) -> Set[str]:
    """L3-D2 — extra permissions this agent holds *by delegation from* ``act_principal``.

    A delegation grant contributes permissions ONLY when the presented token's ``act.sub``
    matches the grant's principal (tenet: authority is never inherited silently — the token
    must SAY on whose behalf it acts). ``org:``-principal grants additionally require the
    agent to be linked to that org (``agents.organization_id``), so an org-admin's grant
    only reaches agents that org actually owns. Expired/revoked grants are filtered in-query.
    Returns ∅ when delegation mode is off, no ``act`` is present, or nothing matches.
    """
    if agent_delegation_mode() == "off" or not act_principal:
        return set()
    try:
        rows = (await db.execute(text(
            "SELECT permissions, principal_type, principal_ref FROM agent_delegation_grants "
            "WHERE delegate_agent_did = :did AND principal_ref = :pref "
            "AND revoked_at IS NULL AND (expires_at IS NULL OR expires_at > now())"
        ), {"did": agent_did, "pref": act_principal})).fetchall()
    except Exception:
        return set()  # table missing / read error → no delegated authority (fail-safe: grant nothing)
    if not rows:
        return set()
    # For org: principals, confirm the delegate agent is actually linked to that org.
    perms: Set[str] = set()
    org_ok_cache: dict[str, bool] = {}
    dev_ok_cache: dict[str, bool] = {}
    for permissions, ptype, pref in rows:
        if ptype == "dev":
            # §TWOAGENT (2026-09-23): a developer's grant conveys nothing once that developer is suspended or deleted,
            # the rule the liability clamp already applies (PART 15: suspend the human, and nothing leaning on them
            # conveys authority on the next request). It used to outlive the suspension until its own expiry.
            # D6-270: and it reaches only an agent that developer created, whoever wrote the row.
            if pref not in dev_ok_cache:
                dev_ok_cache[pref] = (await _dev_principal_live(db, pref)
                                      and await _dev_created_agent(db, pref, agent_did))
            if not dev_ok_cache[pref]:
                continue
        if ptype == "org":
            if pref not in org_ok_cache:
                try:
                    slug = pref.split(":", 1)[1] if ":" in pref else pref
                    # E1c — o.is_active: authority from a deactivated (deleted) org must die
                    # with it. The link half already covers unassignment (org_id goes NULL);
                    # this half covers the org itself going away, including orgs deleted
                    # before the delete path learned to revoke its grants.
                    linked = (await db.execute(text(
                        "SELECT 1 FROM agents a JOIN organizations o ON a.organization_id = o.id "
                        "WHERE a.did = :did AND o.is_active = true "
                        "AND (o.slug = :slug OR CAST(o.id AS TEXT) = :slug) LIMIT 1"
                    ), {"did": agent_did, "slug": slug})).first()
                    org_ok_cache[pref] = linked is not None
                except Exception:
                    org_ok_cache[pref] = False
            if not org_ok_cache[pref]:
                continue
        granted = {p for p in (permissions or []) if p in ALL_PERMISSIONS}
        # D6-270: a principal conveys only what it may hand out. Applied here as well as when a grant is written, so a
        # row written before that check conveys no more than a new one could.
        if ptype == "dev":
            granted &= DEV_DELEGATABLE_PERMISSIONS
        elif ptype == "org":
            from agentvault_registry.services.org_authz import NEVER_IN_ORG_SLICES  # it imports this module
            granted -= NEVER_IN_ORG_SLICES
        if ptype == "agent":
            # §TWOAGENT G4 (2026-09-23): an agent principal's grant conveys no more than that agent holds NOW, at its
            # home. For a cross-registry credential the home is asked (fail closed); a local issuer is read here.
            from agentvault_registry.services.xreg_issuer_authority import conveyed_for
            granted = await conveyed_for(db, agent_did, pref, granted)
        perms |= granted
    return perms


async def _dev_principal_live(db: AsyncSession, principal_ref: str) -> bool:
    """`dev:<id>` names a developer who exists, is not suspended and is not deleted or being deleted."""
    try:
        dev_id = int(str(principal_ref).split(":", 1)[1])
        row = (await db.execute(text(
            "SELECT is_suspended, deleted_at, deletion_status FROM developers WHERE id = :i"), {"i": dev_id})).first()
    except Exception:
        return False   # an unreadable principal conveys nothing (fail-safe, like the grants read above)
    if row is None or bool(row[0]) or row[1] is not None:
        return False
    return str(row[2] or "").lower() not in ("pending", "pending_deletion", "deleted", "anonymized")


async def _dev_created_agent(db: AsyncSession, principal_ref: str, agent_did: str) -> bool:
    """D6-270: `dev:<id>` created the agent `agent_did` (the owner rule of the access API, agents.creator_developer_id)."""
    try:
        dev_id = int(str(principal_ref).split(":", 1)[1])
        row = (await db.execute(text(
            "SELECT 1 FROM agents WHERE did = :did AND creator_developer_id = :dev LIMIT 1"),
            {"did": agent_did, "dev": dev_id})).first()
    except Exception:
        return False   # unreadable: conveys nothing, like the reads above
    return row is not None


async def resolve_agent_permissions(
    db: AsyncSession, agent_did: str, act_principal: str | None = None
) -> Set[str]:
    """Effective permission set = BASE ∪ (roles→perms) ∪ direct grants ∪ delegated grants.

    Expired grants (``expires_at <= now()``) are filtered at the query, so time-based
    grants self-retire with no sweeper. An agent with no rows falls back to BASE only
    (least privilege) — but note migration 0107 backfills ``legacy-full`` for every
    pre-existing agent, so this only bites brand-new agents once enforcement is on.

    ``act_principal`` (L3) — when the presented token carries ``act.sub`` (on-behalf-of),
    delegation grants FROM that principal TO this agent add their permissions. Absent an
    ``act`` claim, or with ``AGENT_DELEGATION_MODE=off``, delegated grants contribute
    nothing (byte-equivalent to the L1/L2 behavior).
    """
    rows = (await db.execute(text(
        "SELECT grant_type, value FROM agent_role_grants "
        "WHERE agent_did = :did AND (expires_at IS NULL OR expires_at > now())"
    ), {"did": agent_did})).fetchall()
    perms: Set[str] = set(BASE_PERMISSIONS)
    for grant_type, value in rows:
        if grant_type == "role":
            perms |= ROLE_PERMISSIONS.get(value, set())
        elif grant_type == "permission":
            perms.add(value)
    if act_principal:
        perms |= await resolve_delegated_permissions(db, agent_did, act_principal)
    return perms


async def resolve_agent_roles(db: AsyncSession, agent_did: str) -> list[str]:
    """The agent's currently-held role names (non-expired) — for the authz readout."""
    rows = (await db.execute(text(
        "SELECT value FROM agent_role_grants "
        "WHERE agent_did = :did AND grant_type = 'role' "
        "AND (expires_at IS NULL OR expires_at > now()) ORDER BY value"
    ), {"did": agent_did})).fetchall()
    return [r[0] for r in rows]


# ── L2 spend policy (STRATEGY §4.3) ──────────────────────────────────────────
# TWO axes: (a) per-tx cap = EXPOSURE admission on a single action's face amount
# (stateless, implemented here); (b) daily cap = rolling-24h NET SETTLED outflow via
# Redis reserved/settled counters + settle/refund hooks (the deferred half). "Outflow"
# EXCLUDES staking (self-lock), fees, and refunded escrow. Deny-only, pre-escrow →
# Δ-irrelevant. `require_approval_above` (step-up) is a deny HERE; under enforce the gate
# (security.py, B3) parks it in the approval queue (services/spend_approvals.py).

async def check_spend_policy(
    db: AsyncSession,
    agent_did: str,
    amount,
    *,
    currency: str | None = None,
    counterparty_did: str | None = None,
    same_registry: bool | None = None,
) -> tuple[bool, str | None]:
    """Spend admission. Returns ``(allowed, reason)``. No policy row = uncapped.

    Enforces BOTH axes: (a) per-tx exposure cap + currency/counterparty scope (stateless);
    (b) the rolling-24h NET SETTLED daily cap, summed from ``velocity_metrics`` (the
    registry-local settled-transfer reconciliation source — no worker hooks needed).
    Amounts are the agent's HOME-currency debit side. Never raises — pure decision.
    """
    from decimal import Decimal, InvalidOperation
    try:
        r = (await db.execute(text(
            "SELECT max_per_tx, max_per_day, allowed_currencies, counterparty_mode, "
            "counterparty_allow, require_approval_above, rate_per_hour, geo_allow "
            "FROM agent_spend_policies WHERE agent_did = :d"
        ), {"d": agent_did})).first()
    except Exception:
        return True, None  # fail-open on read error (per-tx is best-effort; §12 daily half is fail-closed)
    if not r:
        return True, None
    try:
        amt = Decimal(str(amount)) if amount is not None else None
    except (InvalidOperation, ValueError, TypeError):
        amt = None
    if r.max_per_tx is not None and amt is not None and amt > r.max_per_tx:
        return False, f"per_tx_cap_exceeded:max={r.max_per_tx}"
    # Rolling-24h NET SETTLED daily cap — summed from velocity_metrics (settled transfer
    # volume; registry-local). Current-hour lag makes it slightly permissive at the boundary,
    # acceptable for a blast-radius ceiling. Table missing/err → skip (per-tx still applies).
    if r.max_per_day is not None and amt is not None:
        try:
            used = (await db.execute(text(
                "SELECT COALESCE(SUM(tx_volume), 0) FROM velocity_metrics "
                "WHERE agent_did = :d AND window_start > now() - interval '24 hours'"
            ), {"d": agent_did})).scalar() or 0
            if Decimal(str(used)) + amt > r.max_per_day:
                return False, f"per_day_cap_exceeded:max={r.max_per_day},used_24h={used}"
        except Exception:
            pass
    if (r.require_approval_above is not None and amt is not None
            and amt > r.require_approval_above):
        # A deny here; under enforce the gate (security.py, B3) parks it as an ask for the
        # owner (Settings → Approvals) and lets the approved retry through once. The reason
        # says what happens next, for the denial rows an owner reads (§FESUITE 2026-10-10: it
        # said "no approval flow exists" from A5 on, after B3 had built one). The prefix is
        # what the gate matches: keep it.
        return False, (
            f"denied_above_approval_threshold:{r.require_approval_above} "
            f"(above the approval threshold: under enforcement it waits for the owner's approval)"
        )
    if currency and r.allowed_currencies and "*" not in r.allowed_currencies \
            and currency not in r.allowed_currencies:
        return False, f"currency_not_allowed:{currency}"
    mode = (r.counterparty_mode or "any")
    if mode == "same_registry" and same_registry is False:
        return False, "counterparty_off_registry"
    if mode == "allowlist" and counterparty_did and r.counterparty_allow \
            and counterparty_did not in r.counterparty_allow:
        return False, "counterparty_not_allowlisted"
    # ── B4 (RBAC plan): geo_allow — registries where this agent's spends may EXECUTE.
    # Each registry checks its OWN name, so a policy written once binds wherever the
    # agent's authority reaches (v3 hands spend cross-frame; the origin leg runs here).
    ga = getattr(r, "geo_allow", None)
    if ga and not _geo_ok(ga):
        return False, f"geo_not_allowed:{local_registry_name()}"
    # ── B4: rate_per_hour — live Redis window, LAST so cheaper axes verdict first.
    # Counts spend ATTEMPTS (allowed or later-denied) — conservative by design. Redis
    # unavailable → skip, matching this function's fail-open read philosophy (the
    # capability-token rate caveat in security.py is the fail-CLOSED sibling: an
    # issuer's explicit bound must hold even through an outage).
    rph = getattr(r, "rate_per_hour", None)
    if rph is not None and amt is not None:
        over = await spend_rate_exceeded(f"pol:{agent_did}", int(rph))
        if over is True:
            return False, f"rate_per_hour_exceeded:max={rph}"
    return True, None


def local_registry_name() -> str:
    """This registry's own display name (the geo_allow matching unit)."""
    try:
        from agentvault_registry.config import settings
        return str(getattr(settings, "REGISTRY_NAME", "") or "")
    except Exception:  # noqa: BLE001
        return ""


def _geo_ok(geo_allow) -> bool:
    """Case-insensitive membership of the LOCAL registry in the allow list."""
    try:
        local = local_registry_name().strip().lower()
        return bool(local) and local in {str(g).strip().lower() for g in (geo_allow or [])}
    except Exception:  # noqa: BLE001
        return True  # malformed list → don't brick spends over a bad value


async def spend_rate_exceeded(scope: str, limit: int):
    """Shared rolling-hour spend-rate window (B4). Returns True (over), False (under),
    or None (Redis unavailable — CALLER decides the fail direction: policy side skips,
    capability-caveat side denies). One INCR per gated attempt; the key is an hour
    bucket with a slightly-longer TTL, so the window is hour-aligned, not sliding —
    accepted coarseness for a blast-radius bound."""
    import datetime as _dt
    try:
        from agentvault_registry.background_tasks.leader import get_redis
        r = await get_redis()
        if r is None:
            return None
        bucket = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d%H")
        key = f"ironkey:spendrate:{scope}:{bucket}"
        n = int(await r.incr(key))
        if n == 1:
            await r.expire(key, 3900)
        return n > int(limit)
    except Exception:  # noqa: BLE001
        return None
