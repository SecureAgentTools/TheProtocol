"""§OURSTATE-5a — priced first contact, and the personal Genesis behind it.

The strategy's line on spam is that it is an ECONOMIC problem, not an editorial
one (§6): blocks and a Requests folder cost a spammer nothing, while a price
costs them exactly what they were unwilling to pay. So a person may declare
what a stranger's first thread costs, and a stranger pays it the same way they
would pay anyone — an ordinary transfer on the rail that already exists.

WHAT THIS MODULE IS NOT, and cannot become without rewriting it:

  * It is NOT a wallet, an escrow, or a fee. It never moves value. Law 1: chat
    has no money code. The registry reads a transfer that ALREADY happened and
    decides whether it satisfies a declaration.
  * It is NOT a hold. There is no refund path, because there is nothing held —
    a paid intro is a payment to a person, not a deposit with the registry.
  * It does NOT price replies, only the FIRST thread from a stranger. Once a
    thread is active, conversation is free, forever.

Three rules earned elsewhere in this program and applied here:

  1. **A price is never a bare number.** It is stored and rendered with its
     currency, always, because this network has three of them and §FOREIGNACT
     was a whole session about a label that disagreed with the money.
  2. **A declaration that cannot be paid is not enforced.** Humans hold no
     balance here; the price is payable to one of the person's OWN agents. With
     no purse named, `priced` would refuse every stranger while collecting
     nothing — a lockout caused by a misconfiguration. It falls back to open
     and SAYS the declaration is inert, on their own card, where they can see
     it and fix it.
  3. **Verification reads the RECEIVER's ledger.** That is the only place that
     proves the money arrived. A sender-supplied reference is a claim; the
     payee's own transaction history is the fact.
"""
from __future__ import annotations

import decimal
import logging
from typing import Any, Optional

import httpx
from sqlalchemy import text as sa_text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

POLICIES = ("open", "contacts", "priced")
GENESIS_MAX = 2000
MAX_PRICE = decimal.Decimal("1000000")


def _dec(v: Any) -> Optional[decimal.Decimal]:
    if v is None or v == "":
        return None
    try:
        return decimal.Decimal(str(v))
    except (decimal.InvalidOperation, ValueError):
        return None


def money_str(d: Optional[decimal.Decimal]) -> Optional[str]:
    """Render an amount the way a human reads it: `5`, not `5.00000000`.

    `Numeric(24,8)` comes back fully padded, and a price is a sentence on
    someone's public card, not a column dump. ⚠ `format(..., 'f')` is
    load-bearing: `Decimal("100").normalize()` is `1E+2`, and this project has
    already been bitten by balances arriving in scientific notation.
    """
    if d is None:
        return None
    return format(d.normalize(), 'f')


def effective_policy(policy: str, price: Optional[decimal.Decimal],
                     currency: Optional[str], purse: Optional[str]) -> tuple[str, Optional[str]]:
    """What the registry will ACTUALLY enforce, and why it differs if it does.

    Pure, so it can be tested without a database — and it is the only place
    that decides, so the gate and the card can never disagree about whether a
    price is in force.

    A `priced` declaration that cannot be paid falls back to OPEN, never to
    "refuse everyone": a misconfiguration should cost the owner some visibility
    on their own card, not cost every stranger the ability to reach them.
    """
    if policy != "priced":
        return policy, None
    if not purse:
        return "open", "no agent is named to receive it"
    if price is None or price <= 0:
        return "open", "no amount is set"
    if not currency:
        # A price without a currency is the §FOREIGNACT defect in advance.
        return "open", "no currency is set"
    return "priced", None


async def declaration(db: AsyncSession, developer_id: int) -> dict:
    """What this person declares, and what the registry will actually enforce.

    The two are returned SEPARATELY and deliberately: `policy` is what they
    said, `effective` is what happens. Collapsing them would hide exactly the
    case a person most needs to see — a price nobody can pay.
    """
    row = (await db.execute(sa_text(
        "SELECT contact_policy, contact_price, contact_currency, contact_purse_did, genesis "
        "FROM developers WHERE id = :d"
    ), {"d": int(developer_id)})).first()
    if row is None:
        return {"policy": "open", "effective": "open", "price": None,
                "currency": None, "purse_did": None, "genesis": None}

    policy = (row[0] or "open").lower()
    if policy not in POLICIES:
        policy = "open"
    price = _dec(row[1])
    currency = row[2]
    purse = row[3]

    effective, inert = effective_policy(policy, price, currency, purse)

    out = {"policy": policy, "effective": effective,
           "price": money_str(price),
           "currency": currency, "purse_did": purse,
           "genesis": row[4]}
    if inert:
        out["inert_reason"] = inert
    return out


async def set_declaration(db: AsyncSession, developer_id: int, *,
                          policy: Optional[str] = None,
                          price: Optional[str] = None,
                          currency: Optional[str] = None,
                          purse_did: Optional[str] = None,
                          stated: Optional[str] = None) -> dict:
    """Write the declaration. Refuses BY NAME rather than silently coercing.

    The purse must be an agent this developer actually owns — otherwise a
    person could point their price at someone else's wallet, which is not a
    price, it is a redirect.
    """
    from ..services.chat_service import ChatError  # local: avoids an import cycle

    sets, params = [], {"d": int(developer_id)}

    if policy is not None:
        p = str(policy).lower()
        if p not in POLICIES:
            raise ChatError(422, f"contact policy is one of {', '.join(POLICIES)}")
        sets.append("contact_policy = :p"); params["p"] = p

    if price is not None:
        d = _dec(price)
        if d is None or d < 0:
            raise ChatError(422, "price must be a non-negative number")
        if d > MAX_PRICE:
            raise ChatError(422, f"price above the {MAX_PRICE} ceiling")
        sets.append("contact_price = :pr"); params["pr"] = d

    if currency is not None:
        c = str(currency).strip().upper()[:12] or None
        sets.append("contact_currency = :c"); params["c"] = c

    if purse_did is not None:
        pd = str(purse_did).strip() or None
        if pd:
            owns = (await db.execute(sa_text(
                "SELECT 1 FROM agents WHERE did = :x AND creator_developer_id = :d "
                "AND status = 'active'"
            ), {"x": pd, "d": int(developer_id)})).first()
            if owns is None:
                raise ChatError(422, "the receiving agent must be one of your own active agents")
        sets.append("contact_purse_did = :pd"); params["pd"] = pd

    if stated is not None:
        # The personal Genesis, same two-register shape as a room's: what YOU
        # say, kept apart from what the registry enforces.
        import datetime
        cur = (await db.execute(sa_text(
            "SELECT genesis FROM developers WHERE id = :d"), {"d": int(developer_id)})).scalar()
        old = cur or {}
        history = list(old.get("history") or [])
        if old.get("stated"):
            history.append({"stated": old.get("stated"), "updated_at": old.get("updated_at")})
        gen = {"stated": str(stated)[:GENESIS_MAX],
               "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
               "history": history[-5:]}
        sets.append("genesis = CAST(:g AS jsonb)")
        import json
        params["g"] = json.dumps(gen)

    if sets:
        await db.execute(sa_text(
            f"UPDATE developers SET {', '.join(sets)} WHERE id = :d"), params)
        await db.commit()
    return await declaration(db, developer_id)


def genesis_card(decl: dict, display_name: str) -> dict:
    """The personal terms card — TWO REGISTERS, visually and structurally apart.

    `stated` is what the person wrote on their wall. `enforced` is generated
    from the columns the registry actually reads at gate time, so a reader can
    always tell which sentences are backed by machinery. That distinction is
    law 5 applied to promises, and it is the whole reason this card exists
    rather than a free-text bio.
    """
    enforced: list[dict] = []
    eff = decl.get("effective")
    if eff == "priced":
        enforced.append({"k": "contact_price",
                         "label": f"first thread costs {decl['price']} {decl['currency']}"})
    elif eff == "contacts":
        enforced.append({"k": "contacts_only",
                         "label": "only people already in a thread may start a new one"})
    else:
        enforced.append({"k": "open", "label": "anyone may start a thread"})
    if decl.get("inert_reason"):
        enforced.append({"k": "inert",
                         "label": f"declared price is not in force — {decl['inert_reason']}"})
    g = decl.get("genesis") or {}
    return {"v": 1, "type": "person.genesis", "data": {
        "who": display_name,
        "stated": g.get("stated") or "",
        "enforced": enforced,
        "updated_at": g.get("updated_at"),
    }}


async def _teg_transactions(agent_row_id: int, agent_did: str, limit: int = 200) -> list[dict]:
    """The payee's OWN transaction history, read as the payee.

    Server-side and read-only. Nothing here can move value; the worst a bug
    can do is fail to recognise a payment that happened, which refuses contact
    rather than granting it — the safe direction for a gate.
    """
    from ..routers.teg_integration import (
        TEG_API_BASE_URL, TEG_API_V1_PREFIX, get_teg_token_for_agent, prepare_teg_headers)
    from ..es_ssl_helper import get_httpx_verify
    token = await get_teg_token_for_agent(agent_row_id, agent_did)
    # ⚠ `verify=get_httpx_verify()` is not optional: a bare AsyncClient uses the
    # system trust store, which does not carry this fabric's CA, and every read
    # fails CERTIFICATE_VERIFY_FAILED. The gate then refuses a payment that
    # actually settled — the safe direction, but still wrong.
    async with httpx.AsyncClient(verify=get_httpx_verify()) as client:
        r = await client.get(
            f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/token/transactions",
            params={"limit": limit, "offset": 0},
            headers=prepare_teg_headers(token), timeout=10.0)
    if r.status_code != 200:
        raise RuntimeError(f"teg transactions {r.status_code}")
    return list((r.json() or {}).get("transactions") or [])


async def verify_and_consume_intro(
    db: AsyncSession, *, tx_ref: str, payer_key: str, payee_developer_id: int,
    decl: dict) -> dict:
    """Prove the intro was paid, then spend the proof.

    Order matters and is deliberate: the row is INSERTED first (UNIQUE on
    `tx_ref`), so two threads racing on one payment cannot both win. Only then
    is the ledger read. A payment that turns out not to match is rolled back
    and the ref released — the reservation exists to serialise, not to punish.
    """
    from ..services.chat_service import ChatError

    ref = str(tx_ref or "").strip()
    if not ref:
        raise ChatError(402, f"this person's first thread costs "
                             f"{decl['price']} {decl['currency']} — attach the payment reference")

    purse_did = decl["purse_did"]
    prow = (await db.execute(sa_text(
        "SELECT id FROM agents WHERE did = :x"), {"x": purse_did})).first()
    if prow is None:
        # The declaration passed `declaration()` but the agent is gone since.
        raise ChatError(409, "the agent named to receive this payment no longer exists")

    want = _dec(decl["price"]) or decimal.Decimal(0)
    cur = (decl["currency"] or "").upper()

    # Reserve the reference. UNIQUE(tx_ref) is the entire anti-replay design:
    # one settled transfer opens exactly one thread, network-wide.
    # ⚠ The try wraps the EXECUTE, not just the flush: `db.execute()` sends the
    # INSERT immediately, so the unique violation is raised right there. With
    # the try around `flush()` alone the error escaped to the global handler and
    # the caller was told "A record with this value already exists" — true, and
    # useless, instead of the sentence that names what actually happened.
    try:
        await db.execute(sa_text(
            "INSERT INTO chat_intro_payments "
            "(tx_ref, payer_key, payee_developer_id, purse_did, amount, currency) "
            "VALUES (:t, :pk, :d, :pd, :a, :c)"
        ), {"t": ref, "pk": payer_key, "d": int(payee_developer_id),
            "pd": purse_did, "a": want, "c": cur})
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise ChatError(409, "that payment reference has already opened a conversation")

    try:
        txs = await _teg_transactions(int(prow[0]), purse_did)
    except Exception as e:  # noqa: BLE001
        await db.rollback()
        logger.error("[CONTACT] ledger read failed for intro %s: %s", ref, e)
        # An unreadable ledger is not a rejected payment, and must not be
        # reported as one.
        raise ChatError(503, "could not read the receiving ledger just now — try again shortly")

    match = next((t for t in txs if str(t.get("transaction_id")) == ref), None)
    if match is None:
        await db.rollback()
        raise ChatError(402, "that payment is not on the receiving ledger")
    if str(match.get("status", "")).lower() not in ("completed", "success", "settled"):
        await db.rollback()
        raise ChatError(402, f"that payment is {match.get('status')}, not settled")
    if str(match.get("receiver_agent_id")) != str(purse_did):
        await db.rollback()
        raise ChatError(402, "that payment went to a different agent")
    got = _dec(match.get("amount")) or decimal.Decimal(0)
    if got < want:
        await db.rollback()
        raise ChatError(402, f"the first thread costs {money_str(want)} {cur}; "
                             f"that payment was {money_str(got)}")

    return {"tx_ref": ref, "amount": str(got), "currency": cur, "purse_did": purse_did}


async def attach_intro_to_conversation(db: AsyncSession, tx_ref: str, conversation_id: str) -> None:
    """Bind the consumed receipt to the thread it opened (audit, not gating)."""
    await db.execute(sa_text(
        "UPDATE chat_intro_payments SET conversation_id = :c WHERE tx_ref = :t"
    ), {"c": conversation_id, "t": tx_ref})


async def has_existing_thread(db: AsyncSession, actor_key: str, target_key: str) -> bool:
    """Is there already a thread between these two? The `contacts` policy's
    whole question. Any prior conversation counts, in any state: "we have
    spoken" is not undone by a burn or by leaving.

    ⚠ `conversation_participants` has NO `principal_key` column — the first
    draft of this query invented one, which is the never-guess-a-column class
    this project keeps meeting. The key lives in python (`principal_key()`);
    the table stores ptype + developer_id + agent_did + remote_key, so the key
    is rebuilt in SQL to match that function exactly.
    """
    row = (await db.execute(sa_text("""
        SELECT 1
        FROM conversation_participants p1
        JOIN conversation_participants p2 ON p2.conversation_id = p1.conversation_id
        WHERE CASE p1.ptype
                WHEN 'developer' THEN 'dev:' || p1.developer_id
                WHEN 'agent'     THEN 'agt:' || lower(p1.agent_did)
                ELSE                  'rem:' || p1.remote_key END = :a
          AND CASE p2.ptype
                WHEN 'developer' THEN 'dev:' || p2.developer_id
                WHEN 'agent'     THEN 'agt:' || lower(p2.agent_did)
                ELSE                  'rem:' || p2.remote_key END = :b
        LIMIT 1
    """), {"a": actor_key, "b": target_key})).first()
    return row is not None
