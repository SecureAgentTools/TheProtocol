"""§ORGTREASURY (Track C, C1) — THE one answer to "where does this organization's money live".

## Why this module exists

Before it, an org's money account was `exchange_listings.treasury_agent_did` — resolved by
FOUR independent copies of the same SQL (`routers/guild.py::_org_treasury`,
`services/forge_royalty.py::_org_treasury_did`, an inline query in
`services/contract_settlement.py`, and the roll-up in `services/exchange_service.py`). Two of
those copies used ``LIMIT 1`` with **no ORDER BY**, so a multi-listing org would be paid into a
nondeterministic purse. Adding an org-level treasury without unifying them would have created a
FIFTH answer, and the Guild would pay a firm into one account while contracts paid it into
another — the §FANOUTFIX class verbatim (a widening fix that leaves other call sites asking the
old question).

So: every caller asks :func:`resolve_org_treasury_did`, and nothing else reads either column.

## The account itself

An org treasury is a normal Agent row that is **keyless**: its ``client_secret`` is generated,
hashed and immediately discarded, so `POST /auth/agent/token` can never mint a JWT for it. That
is the same construction AGORA uses for listing treasuries
(`services/exchange_service.py::create_listing`) and it is load-bearing — see the money rules.

## Money rules (do not break these)

1. **Never wire a keyless DID through an agent-JWT rail.** `/teg/transfer` and
   `/teg/system-transfer` both require an agent JWT. `get_teg_token_for_agent()` does NOT fail
   cleanly for a keyless agent — it returns ``ADMIN_IMPERSONATE:{did}``, which downstream becomes
   admin-key + ``X-Act-As-Agent``. A treasury spend down that path would silently bypass
   `enforce_agent_spend`, IRONKEY, the liability gate and the fee path. Money leaves an org
   treasury only through the escrow mover (C2), never through an agent token.
2. **The AGORA mover cannot do a direct A→B move** — the TEG endpoint rejects any
   `/admin/exchange/move` without ``exchange_escrow`` on one side. A treasury→dest payment is
   therefore TWO legs through the escrow hub, and the escrow nets exactly 0.
3. **Both legs must share a deterministic idempotency-key base.** Deriving the key from
   ``secrets.token_hex()`` on each attempt makes a retry re-execute the debit leg and
   double-charge the treasury (the exref replay guard is a lookup, not a constraint — the
   frame-b incident cost 1,850 duplicate legs / 3.6k AVT).

Δ note: creating a treasury moves nothing. The TEG materialises the account lazily at zero
balance on first reference (`AgentCRUD.get_or_create`), so C1 is Δ-neutral by construction.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from decimal import Decimal
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# The DID shape for an org-level treasury. Deliberately distinct from AGORA's
# `did:theprotocol:org-{symbol}-treasury` so a listed org's two accounts can never collide.
DID_TEMPLATE = "did:theprotocol:orgtreasury-{slug}"



def _org_treasury_card_data(org_name: str, did: str) -> dict:
    """The org treasury's card, CONFORMANT to the canonical A2A AgentCard schema.

    Third instance of the stub §VENUEGW fixed for the AGORA deposit gateway on 2026-08-26 (the
    second is the AGORA treasury in `exchange_service.py`, fixed in the same pass). A five-field
    card is QUARANTINED by any peer running `FEDERATION_INGEST_FAIL_CLOSED=true` — both live frames
    — so it can never reach a mirror, and nothing says so.
    """
    from ..core import public_url as _pu
    base = (_pu.public_base_url_static() or "").rstrip("/")
    slug = did.rsplit(":", 1)[-1]
    url = f"{base}/api/v1/organizations" if base else f"https://theprotocol.cloud/org/{slug}"
    return {
        "protocolVersion": "0.3.0",
        "humanReadableId": f"org/{slug}",
        "agentVersion": "1.0.0",
        "name": f"{org_name} Treasury",
        "description": (
            f"Organization treasury for {org_name} — holds the org's funds, funds member agents, "
            "and receives their income. Keyless by design."
        ),
        "url": url,
        "provider": {"name": org_name, "url": "https://theprotocol.cloud"},
        "capabilities": {"streaming": False},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [{
            "id": "org-treasury",
            "name": "Organization treasury",
            "description": "Holds the organization's funds and settles member income.",
        }],
        "authSchemes": [{"scheme": "none"}],
        "did": did,
        "org_treasury": True,
        "version": "1.0",
    }


async def resolve_org_treasury_did(db: AsyncSession, org_id: str) -> Optional[str]:
    """THE org money account, or None if the org has neither.

    Order of truth:
      1. ``organizations.treasury_agent_did`` — the org's own account (Track C).
      2. the org's FIRST AGORA listing treasury, ordered by ``created_at ASC``.

    Step 2 is why every pre-existing org keeps its exact current payee: at migration time no
    org has step 1 set, so this returns precisely what the old queries returned — with the
    ordering now deterministic for every caller instead of two out of four.
    """
    row = (await db.execute(text(
        "SELECT treasury_agent_did FROM organizations WHERE id = :o"
    ), {"o": str(org_id)})).first()
    if row and row[0]:
        return str(row[0])

    row = (await db.execute(text(
        "SELECT treasury_agent_did FROM exchange_listings WHERE organization_id = :o "
        "AND treasury_agent_did IS NOT NULL ORDER BY created_at ASC LIMIT 1"
    ), {"o": str(org_id)})).first()
    return str(row[0]) if row and row[0] else None


async def org_treasury_source(db: AsyncSession, org_id: str) -> Optional[str]:
    """Which of the two answers applied — ``"org"``, ``"agora_listing"`` or None.

    Diagnostics only (the dashboard and the audit trail want to say WHERE the money lives, and
    "it's actually your AGORA listing's purse" is exactly the kind of thing an operator should
    not have to infer). Never branch money on this.
    """
    row = (await db.execute(text(
        "SELECT treasury_agent_did FROM organizations WHERE id = :o"
    ), {"o": str(org_id)})).first()
    if row and row[0]:
        return "org"
    row = (await db.execute(text(
        "SELECT 1 FROM exchange_listings WHERE organization_id = :o "
        "AND treasury_agent_did IS NOT NULL LIMIT 1"
    ), {"o": str(org_id)})).first()
    return "agora_listing" if row else None


MAX_AMOUNT = Decimal("10000000")  # same ceiling every other money rail uses


async def _two_leg_move(
    db: AsyncSession, *, src_did: str, dst_did: str, amount: Decimal,
    reason: str, idem_base: str,
) -> dict:
    """Move ``amount`` from ``src_did`` to ``dst_did`` through the escrow hub.

    TWO legs, because the TEG's `/admin/exchange/move` refuses any move without
    ``exchange_escrow`` on one side. The escrow nets exactly 0 across the pair, both endpoints
    are ordinary in-circulation balance accounts, and the TEG books each leg as a transit
    `LedgerBalanceChanged` — so the pair is **Δ-neutral by construction**: no mint, no burn.

    ``idem_base`` MUST be deterministic and caller-derived. If a retry re-derived it randomly
    the ``:out`` leg would execute twice and double-debit the source — the exref replay guard
    is a lookup, not a constraint (a prior incident cost 1,850 duplicate legs / 3.6k AVT). With
    a stable base, a retry replays the cached ``:out`` and completes the missing ``:in``, which
    is exactly what makes a half-finished transfer self-heal rather than strand funds in escrow.
    """
    from agentvault_registry.services.exchange_service import mover, EXCHANGE_ESCROW_SENTINEL

    await mover.move(src_did, EXCHANGE_ESCROW_SENTINEL, amount,
                     f"{reason}_out", f"{idem_base}:out")
    return await mover.move(EXCHANGE_ESCROW_SENTINEL, dst_did, amount,
                            reason, f"{idem_base}:in")


def move_ref(kind: str, org_id: str, principal: str, idempotency_key: str) -> str:
    """D6-777: the reference a treasury move's escrow legs, its ledger event and its room receipt derive from. It is the
    caller's (services/idempotency/cache.caller_key binds the client's key to the member or agent the route acts for), so
    two members who send the same key value never share a leg, and the same caller's retry derives its own legs again
    and replays them. `org<kind>.<org>.<key>` shares no form with a leg written before (`org<kind>-<org>-<key>`).
    `kind`: fund, remit or sweep. 83 characters at most (the TEG takes a leg key of up to 128)."""
    from agentvault_registry.services.idempotency.cache import caller_key
    return f"org{kind}.{org_id}.{caller_key(principal, idempotency_key)}"


def _debit_refused(exc) -> bool:
    """§DOCSFIX D6-497: the TEG refused the debit leg for want of funds. A retry under the same key replays the legs it
    already ran whatever the source holds now (the exref replay comes before any balance check), so fund and remit ask
    the TEG first instead of refusing on a balance read: a solvency check in front of the replay stranded a half-finished
    move in the escrow and answered a finished one with 409. Only a fresh debit is refused this way; the credit leg's
    source is the escrow, whose shortfall answers with its solvency gate's sentence."""
    return getattr(exc, "status_code", None) == 400 and "insufficient balance" in str(getattr(exc, "detail", "")).lower()


async def _own_treasury_or_raise(db: AsyncSession, org_id: str) -> str:
    """The org's OWN treasury DID, or ValueError.

    Deliberately refuses to operate on an AGORA listing purse even though
    :func:`resolve_org_treasury_did` would happily return one. A listing treasury is governed
    by AGORA's own rails (reserve floors, dividend/buyback accounting); draining it through a
    generic org rail would silently bypass that. An org that wants these rails creates its own
    account first — one POST, and the two purses stay separately answerable.
    """
    src = await org_treasury_source(db, org_id)
    if src != "org":
        raise ValueError(
            "organization has no treasury of its own"
            + (" (its money currently lives in an AGORA listing purse — create an org treasury "
               "first, or use the AGORA treasury rails)" if src == "agora_listing" else "")
        )
    did = await resolve_org_treasury_did(db, org_id)
    if not did:
        raise ValueError("organization has no treasury")
    return did


async def _org_agent_or_raise(db: AsyncSession, org_id: str, agent_did: str) -> None:
    """The agent must be ACTIVE and belong to this org. Both halves matter: a soft-deleted
    agent keeps its ``organization_id`` (the A4 battery caught bulk grants leaking to exactly
    those rows), and an agent outside the org is simply not the org's business."""
    row = (await db.execute(text(
        "SELECT status, organization_id FROM agents WHERE did = :d"
    ), {"d": agent_did})).first()
    if not row:
        raise ValueError("agent not found")
    if str(row.status).lower() != "active":
        raise ValueError(f"agent is not active (status={row.status})")
    if not row.organization_id or str(row.organization_id) != str(org_id):
        raise ValueError("agent does not belong to this organization")


def _amount_or_raise(amount: str | float | Decimal) -> Decimal:
    try:
        amt = Decimal(str(amount))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"invalid amount: {amount!r}") from exc
    if amt <= 0:
        raise ValueError("amount must be > 0")
    if amt > MAX_AMOUNT:
        raise ValueError(f"amount exceeds the {MAX_AMOUNT} ceiling")
    return amt


class ProcurementCapExceeded(ValueError):
    """§ORGSPEND — a dev-driven treasury draw exceeded the member's procurement limit.

    A subclass so existing ``except ValueError`` paths stay safe, but routes catch it
    FIRST and answer 403 (an authority refusal, not a conflict)."""


async def _procurement_cap_or_raise(
    db: AsyncSession, org_id: str, developer_id: int, amount: Decimal,
) -> None:
    """§ORGSPEND — THE one choke point for HOW MUCH a member may move for the firm.

    Called by every dev-driven org-money draw (fund, sweep, and the work-order
    commissioning draw). Per-TRANSACTION by design — that is what one stateless check
    can promise honestly; a per-window budget would need spend state and is a named
    future option, not this. Remit (money INTO the treasury) is never capped.
    Caps live in the org settings catalog (`procurement_limit_default` +
    `procurement_limits` per-member overrides, resolved by org_policy.procurement_cap);
    unset/0 = unlimited, so pre-existing orgs behave exactly as before."""
    from agentvault_registry.services.org_policy import procurement_cap

    row = (await db.execute(text(
        "SELECT settings FROM organizations WHERE id = :o"
    ), {"o": str(org_id)})).first()
    settings = row[0] if row and isinstance(row[0], dict) else None
    cap = procurement_cap(settings, developer_id)
    if cap is not None and amount > cap:
        raise ProcurementCapExceeded(
            f"procurement limit {cap} for this member — this draw is {amount}. "
            "An org owner can raise the limit in Settings (procurement_limit_default "
            f"or a procurement_limits override for developer {developer_id})."
        )


async def fund_agent_from_org(
    db: AsyncSession, *, org_id: str, agent_did: str, amount, idempotency_key: str,
    actor_developer_id: int,
) -> dict:
    """Org treasury → one of the org's agents. Caller must already be org-admin-gated.

    Solvency is read from TEG truth, never from ``agents.liquid_balance`` (the cache is
    Numeric(30,6) while the ledger works in 18 decimals, and it lags every uncommitted leg).
    """
    from agentvault_registry.services.exchange_service import mover, MoverError

    amt = _amount_or_raise(amount)
    treasury = await _own_treasury_or_raise(db, org_id)
    await _org_agent_or_raise(db, org_id, agent_did)
    await _procurement_cap_or_raise(db, org_id, actor_developer_id, amt)

    from agentvault_registry.services.idempotency.cache import developer_caller
    ref = move_ref("fund", org_id, developer_caller(actor_developer_id), idempotency_key)
    bal = await mover.agent_balance(treasury)
    try:
        res = await _two_leg_move(
            db, src_did=treasury, dst_did=agent_did, amount=amt,
            reason="org_treasury_fund", idem_base=ref,
        )
    except MoverError as exc:
        if _debit_refused(exc):
            raise ValueError(f"insufficient treasury balance: has {bal}, needs {amt}") from exc
        raise
    _emit_org_money_event(
        "OrganizationTreasuryFunded", org_id,
        {"treasury_did": treasury, "agent_did": agent_did, "amount": str(amt),
         "actor_developer_id": actor_developer_id},
        ref,
    )
    logger.info("[ORGTREASURY] fund org=%s → %s amount=%s", org_id, agent_did, amt)
    return {"treasury_agent_did": treasury, "agent_did": agent_did,
            "amount": str(amt), "result": res}


async def remit_agent_to_org(
    db: AsyncSession, *, org_id: str, agent_did: str, amount, idempotency_key: str,
) -> dict:
    """One of the org's agents → the org treasury, authorized BY THAT AGENT.

    There is deliberately NO admin-initiated pull. An org admin can already assign authority,
    cap spending and fund an agent; letting them also drain an agent's balance would be a theft
    primitive, because an agent joins an org by its *creator's* choice (the assign route
    requires org-admin AND agent-creator) and its balance remains its own. So the agent remits;
    nobody reaches into it.
    """
    from agentvault_registry.services.exchange_service import mover, MoverError

    amt = _amount_or_raise(amount)
    treasury = await _own_treasury_or_raise(db, org_id)
    await _org_agent_or_raise(db, org_id, agent_did)

    from agentvault_registry.services.idempotency.cache import agent_caller
    ref = move_ref("remit", org_id, agent_caller(agent_did), idempotency_key)   # the remitting agent is the caller
    bal = await mover.agent_balance(agent_did)
    try:
        res = await _two_leg_move(
            db, src_did=agent_did, dst_did=treasury, amount=amt,
            reason="org_treasury_remit", idem_base=ref,
        )
    except MoverError as exc:
        if _debit_refused(exc):
            raise ValueError(f"insufficient agent balance: has {bal}, needs {amt}") from exc
        raise
    _emit_org_money_event(
        "OrganizationTreasuryRemitted", org_id,
        {"treasury_did": treasury, "agent_did": agent_did, "amount": str(amt)},
        ref,
    )
    logger.info("[ORGTREASURY] remit org=%s ← %s amount=%s", org_id, agent_did, amt)
    return {"treasury_agent_did": treasury, "agent_did": agent_did,
            "amount": str(amt), "result": res}


async def sweep_org_treasury(
    db: AsyncSession, *, org_id: str, dest_agent_did: str, idempotency_key: str,
    actor_developer_id: int,
) -> dict:
    """E1b — drain the org's OWN treasury to an agent the OWNER created.

    The corporate-death rail: `delete_organization` refuses while this purse holds
    anything, and this is the sanctioned way out. Caller must already be OWNER-gated
    (not merely admin) — the residual claimant of an org's funds is the liable person
    behind it, nobody else. Sweeps the FULL balance; a zero balance is a successful
    no-op so delete flows can call it unconditionally.

    The destination must be an ACTIVE agent created by the owner, and must not itself
    be an org or AGORA listing treasury — sweeping one keyless purse into another
    would re-strand the money one hop away.
    """
    from agentvault_registry.services.exchange_service import mover

    treasury = await _own_treasury_or_raise(db, org_id)
    if dest_agent_did == treasury:
        raise ValueError("destination is the treasury itself")

    dest = (await db.execute(text(
        "SELECT status, creator_developer_id FROM agents WHERE did = :d"
    ), {"d": dest_agent_did})).first()
    if not dest:
        raise ValueError("destination agent not found")
    if str(dest.status).lower() != "active":
        raise ValueError(f"destination agent is not active (status={dest.status})")
    if int(dest.creator_developer_id or 0) != int(actor_developer_id):
        raise ValueError("destination must be an agent created by the org owner")
    parked = (await db.execute(text(
        "SELECT 1 FROM organizations WHERE treasury_agent_did = :d "
        "UNION ALL SELECT 1 FROM exchange_listings WHERE treasury_agent_did = :d LIMIT 1"
    ), {"d": dest_agent_did})).first()
    if parked:
        raise ValueError("destination is itself a treasury account: pick a normal agent")

    bal = await mover.agent_balance(treasury)
    if bal <= 0:
        return {"treasury_agent_did": treasury, "dest_agent_did": dest_agent_did,
                "amount": "0", "swept": False, "detail": "treasury already empty"}
    if bal > MAX_AMOUNT:
        # deliberate: a purse above the rail ceiling needs eyes, not a bigger pipe
        raise ValueError(f"treasury balance {bal} exceeds the {MAX_AMOUNT} per-move ceiling")
    # §ORGSPEND — the sweep is a dev-driven draw too; the cap binds it (no deadlock:
    # the settings PUT is not money-gated, so an owner can always raise their own limit).
    await _procurement_cap_or_raise(db, org_id, actor_developer_id, bal)

    from agentvault_registry.services.idempotency.cache import developer_caller
    ref = move_ref("sweep", org_id, developer_caller(actor_developer_id), idempotency_key)
    res = await _two_leg_move(
        db, src_did=treasury, dst_did=dest_agent_did, amount=bal,
        reason="org_treasury_sweep", idem_base=ref,
    )
    _emit_org_money_event(
        "OrganizationTreasurySwept", org_id,
        {"treasury_did": treasury, "dest_agent_did": dest_agent_did, "amount": str(bal),
         "actor_developer_id": actor_developer_id},
        ref,
    )
    logger.info("[ORGTREASURY] sweep org=%s → %s amount=%s", org_id, dest_agent_did, bal)
    return {"treasury_agent_did": treasury, "dest_agent_did": dest_agent_did,
            "amount": str(bal), "swept": True, "result": res}


async def org_treasury_blockers(db: AsyncSession, org_id: str) -> list[dict]:
    """E1b — everything that must be resolved before this org may be deleted.

    Returns [] when deletion is money-safe. Two classes:
      * a non-delisted AGORA listing (its purse is governed by AGORA's own rails —
        corporate death with live securities is refused outright);
      * a funded OWN treasury (sweep it first via the sweep rail).
    Read-only; the delete route turns a non-empty answer into a 409 whose detail
    the FE can render as a checklist.
    """
    from agentvault_registry.services.exchange_service import mover

    blockers: list[dict] = []
    rows = (await db.execute(text(
        "SELECT symbol, status FROM exchange_listings "
        "WHERE organization_id = :o AND status != 'delisted'"
    ), {"o": str(org_id)})).fetchall()
    for sym, status in rows:
        blockers.append({"kind": "exchange_listing", "symbol": sym, "status": status,
                         "action": "delist the listing first"})

    if await org_treasury_source(db, org_id) == "org":
        treasury = await resolve_org_treasury_did(db, org_id)
        if treasury:
            bal = await mover.agent_balance(treasury)
            if bal > 0:
                blockers.append({"kind": "funded_treasury", "treasury_agent_did": treasury,
                                 "balance": str(bal),
                                 "action": "sweep the treasury to one of your agents first"})
    return blockers


def _emit_org_money_event(event_type: str, org_id: str, data: dict, key: str) -> None:
    """Registry-side DOMAIN event, aggregate_id = org_id so it lands in the org audit tab (A6).

    Supply-inert: the ES projection dispatches on token event types only, so an unknown domain
    type is stored and ignored for the invariant — the money itself was already booked by the
    mover's own ledger legs. Emission must never break a money path, hence the swallow.
    All Decimals are str() before they get here (the VoteCast Decimal-loss gotcha).
    """
    try:
        from agentvault_registry.event_emitter import get_event_emitter
        get_event_emitter().emit_background(
            event_type=event_type, aggregate_id=str(org_id),
            aggregate_type="Organization", data=data, idempotency_key=key,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ORGTREASURY] emit %s failed (non-fatal): %r", event_type, exc)


async def ensure_org_treasury(
    db: AsyncSession, org_id: str, *, created_by_developer_id: int
) -> tuple[str, bool]:
    """Idempotently give the org its OWN keyless treasury. Returns ``(did, created)``.

    Creates exactly two rows — one ``agents`` row and one ``agent_cards`` row — mirroring
    `create_listing`'s construction, then stamps ``organizations.treasury_agent_did``. Callers
    commit; this function only flushes, so a treasury can be created atomically alongside
    whatever prompted it.

    Idempotent on both sides: if the column is already set it is returned untouched, and the
    DID is deterministic from the slug, so a re-run after a partial failure adopts the existing
    agent row rather than orphaning it.
    """
    from agentvault_registry import models  # local: avoid an import cycle at module load
    from agentvault_registry.security import hash_password

    row = (await db.execute(text(
        "SELECT id, name, slug, treasury_agent_did FROM organizations WHERE id = :o"
    ), {"o": str(org_id)})).first()
    if not row:
        raise ValueError(f"organization not found: {org_id}")
    if row.treasury_agent_did:
        return str(row.treasury_agent_did), False

    slug = str(row.slug)
    did = DID_TEMPLATE.format(slug=slug)[:120]

    existing = (await db.execute(text(
        "SELECT did FROM agents WHERE did = :d"
    ), {"d": did})).first()

    created = False
    if not existing:
        # KEYLESS: the plaintext secret is generated, hashed, and never stored or returned.
        # The column is NOT NULL, so the row needs *a* hash; nobody can ever produce a
        # matching secret, so no JWT can ever be minted for this DID.
        db.add(models.Agent(
            did=did,
            client_id=f"orgtreasury-{slug}-{secrets.token_hex(4)}"[:255],
            hashed_client_secret=hash_password(f"tp_secret_{secrets.token_hex(32)}"),
            creator_developer_id=created_by_developer_id,
            status="active",
        ))
        await db.flush()
        db.add(models.AgentCard(
            id=uuid.uuid4(),
            developer_id=created_by_developer_id,
            agent_did=did,
            card_data=_org_treasury_card_data(row.name, did),
            name=f"{row.name} Treasury"[:255],
            description=f"Organization treasury for {row.name}"[:500],
            is_active=True,
        ))
        created = True

    await db.execute(text(
        "UPDATE organizations SET treasury_agent_did = :d WHERE id = :o "
        "AND treasury_agent_did IS NULL"
    ), {"d": did, "o": str(org_id)})
    await db.flush()
    logger.info("[ORGTREASURY] org=%s treasury=%s created_agent=%s", org_id, did, created)
    return did, created
