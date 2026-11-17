"""V0663 (agent workflows): a workflow is a parent record over Guild orders.

The rails are the Guild's: every step is an ordinary Guild order posted by the workflow's owner, escrowed by the Guild when it
posts (rule 14: no new money path). So the escrow is PER ORDER: funds lock step by step, not all at once. This module adds
(1) the records, (2) the ruleset check at bid and award (`gate`, deny-only, before any escrow), and (3) `advance`, which reads
each step's order, records the hash of a settled step's output and its receipt, and posts the next step. Nothing here moves
money itself and nothing runs on a timer: the owner (or the console) calls advance.

Pure rules, the receipt chain and the ruleset hash: services/workflow_rules.py.
"""
from __future__ import annotations

import json
import os
import re
import secrets
from decimal import Decimal
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from agentvault_registry.services import workflow_rules as wr

MAX_STEPS = 12
_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
_ENDED = ("cancelled", "refunded", "expired")


def _j(v: Any) -> Any:
    """A JSON column read through a raw statement may arrive as text."""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return None
    return v


def _bad(msg: str, code: int = status.HTTP_422_UNPROCESSABLE_ENTITY) -> HTTPException:
    return HTTPException(code, detail=msg)


async def _load_workflow(db: AsyncSession, wid: str) -> dict:
    row = (await db.execute(text("SELECT * FROM agent_workflows WHERE id=:i"), {"i": wid})).mappings().first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Workflow not found")
    w = dict(row)
    w["ruleset"] = _j(w["ruleset"]) or {}
    return w


async def _load_steps(db: AsyncSession, wid: str) -> list[dict]:
    rows = (await db.execute(text("SELECT * FROM agent_workflow_steps WHERE workflow_id=:i ORDER BY position"),
                             {"i": wid})).mappings().all()
    out = []
    for r in rows:
        s = dict(r)
        s["ruleset"] = _j(s["ruleset"]) or {}
        out.append(s)
    return out


def _step_view(s: dict, order: Optional[dict]) -> dict:
    return {
        "key": s["step_key"], "position": s["position"], "role": s["role"], "spec": s["spec"],
        "acceptance": s["acceptance"], "budget": str(s["budget"]), "deadline_seconds": s["deadline_seconds"],
        "ruleset": s["ruleset"], "input_from": s["input_from"], "order_id": s["order_id"],
        "order_status": (order or {}).get("status"), "output_hash": s["output_hash"], "receipt": s["receipt"],
        "needs_attention": bool(order and order.get("status") in _ENDED and not s["receipt"]),
    }


async def _orders_of(db: AsyncSession, steps: list[dict]) -> dict[str, dict]:
    ids = [s["order_id"] for s in steps if s["order_id"]]
    out: dict[str, dict] = {}
    for oid in ids:
        r = (await db.execute(text("SELECT id, status, worker_did, deliverable FROM guild_work_orders WHERE id=:o"),
                              {"o": oid})).mappings().first()
        if r:
            d = dict(r)
            d["deliverable"] = _j(d["deliverable"])
            out[oid] = d
    return out


def chain_of(steps: list[dict]) -> list[dict]:
    """The receipt chain of the steps that have settled, in order, recomputed from the stored output hashes."""
    done = []
    for s in steps:
        if not s["output_hash"]:
            break
        done.append((s["step_key"], s["output_hash"]))
    return wr.build_chain(done)


def _template_block(w: dict, title: Optional[str]) -> Optional[dict]:
    """V0664: which template a workflow was made from (services/workflow_templates.instantiate writes the three columns,
    migration 0228), or None for one made by hand. The title is the template's now (None once it is gone)."""
    if not w.get("template_id"):
        return None
    v = w.get("template_version")
    return {"id": w["template_id"], "version": int(v) if v is not None else None,
            "content_hash": w.get("template_content_hash"), "title": title}


async def _template_title(db: AsyncSession, tid: Optional[str]) -> Optional[str]:
    if not tid:
        return None
    return (await db.execute(text("SELECT title FROM workflow_templates WHERE id=:i"), {"i": tid})).scalar()


async def view(db: AsyncSession, wid: str) -> dict:
    w = await _load_workflow(db, wid)
    steps = await _load_steps(db, wid)
    orders = await _orders_of(db, steps)
    chain = chain_of(steps)
    ok, why = wr.verify_chain(chain)
    stored_ok = all(link["receipt"] == s["receipt"] for link, s in zip(chain, steps))
    return {
        "id": w["id"], "owner_did": w["owner_did"], "title": w["title"], "status": w["status"],
        "ruleset": w["ruleset"], "ruleset_hash": w["ruleset_hash"], "total_budget": str(w["total_budget"]),
        "currency": w["currency"],
        "template": _template_block(w, await _template_title(db, w.get("template_id"))),
        "escrow_note": "Funds lock step by step: each step's Guild order escrows its own bounty when it posts.",
        "steps": [_step_view(s, orders.get(s["order_id"])) for s in steps],
        "chain": chain, "chain_ok": bool(ok and stored_ok), "chain_problem": why if not ok else (None if stored_ok else "a stored receipt differs from the recomputed one"),
    }


async def create(db: AsyncSession, owner_did: str, body: dict) -> dict:
    title = str(body.get("title") or "").strip()
    if not title or len(title) > 200:
        raise _bad("title is required (at most 200 characters)")
    raw_steps = body.get("steps")
    if not isinstance(raw_steps, list) or not 1 <= len(raw_steps) <= MAX_STEPS:
        raise _bad(f"steps must be a list of 1 to {MAX_STEPS}")
    try:
        total = Decimal(str(body.get("total_budget")))
    except Exception:  # noqa: BLE001
        raise _bad("total_budget must be a number") from None
    if total <= 0:
        raise _bad("total_budget must be above zero")
    keys = []
    for i, s in enumerate(raw_steps):
        k = str((s or {}).get("key") or "").strip()
        if not _KEY_RE.match(k):
            raise _bad(f"step {i + 1}: key must be 1 to 40 lowercase letters, digits, - or _")
        if k in keys:
            raise _bad(f"step {i + 1}: key {k} is used twice")
        keys.append(k)
    try:
        wf_rules = wr.normalize(body.get("ruleset"), step_keys=keys)
    except wr.RulesetError as e:
        raise _bad(f"ruleset: {e}") from None
    spend = Decimal(0)
    prepared = []
    for i, s in enumerate(raw_steps):
        role = str(s.get("role") or "").strip()
        if not role or len(role) > 80:
            raise _bad(f"step {keys[i]}: role is required (at most 80 characters)")
        try:
            budget = Decimal(str(s.get("budget")))
        except Exception:  # noqa: BLE001
            raise _bad(f"step {keys[i]}: budget must be a number") from None
        if budget <= 0:
            raise _bad(f"step {keys[i]}: budget must be above zero")
        spend += budget
        dl = s.get("deadline_seconds")
        if dl is not None and (not isinstance(dl, int) or isinstance(dl, bool) or not 60 <= dl <= 2592000):
            raise _bad(f"step {keys[i]}: deadline_seconds is 60 to 2592000")
        src = s.get("input_from")
        if src is not None and src not in keys[:i]:
            raise _bad(f"step {keys[i]}: input_from must name an earlier step")
        try:
            step_rules = wr.normalize(s.get("ruleset"), step_keys=keys, own_key=keys[i])
        except wr.RulesetError as e:
            raise _bad(f"step {keys[i]} ruleset: {e}") from None
        prepared.append((i, keys[i], role, (s.get("spec") or None), (s.get("acceptance") or None), budget, dl,
                         step_rules, src))
    if spend > total:
        raise _bad(f"the steps' budgets add up to {spend}, above total_budget {total}")
    wid = "wf_" + secrets.token_hex(12)
    currency = str(body.get("currency") or os.getenv("FRAME_CURRENCY", "AVT"))[:12]
    await db.execute(text("""INSERT INTO agent_workflows (id, owner_did, title, ruleset, ruleset_hash, total_budget, currency, status)
                             VALUES (:i,:o,:t,:r,:h,:b,:c,'draft')"""),
                     {"i": wid, "o": owner_did, "t": title, "r": json.dumps(wf_rules, sort_keys=True),
                      "h": wr.ruleset_hash(wf_rules), "b": total, "c": currency})
    for i, key, role, spec, acc, budget, dl, step_rules, src in prepared:
        await db.execute(text("""INSERT INTO agent_workflow_steps (workflow_id, position, step_key, role, spec, acceptance, budget,
                                 deadline_seconds, ruleset, input_from) VALUES (:w,:p,:k,:r,:s,:a,:b,:d,:rs,:f)"""),
                         {"w": wid, "p": i, "k": key, "r": role, "s": spec, "a": acc, "b": budget, "d": dl,
                          "rs": json.dumps(step_rules, sort_keys=True), "f": src})
    await db.commit()
    return await view(db, wid)


async def list_for(db: AsyncSession, owner_did: str, limit: int = 50) -> list[dict]:
    rows = (await db.execute(text("""SELECT w.id, w.title, w.status, w.total_budget, w.currency, w.created_at, w.template_id,
                                             w.template_version, w.template_content_hash, t.title AS template_title
                                      FROM agent_workflows w LEFT JOIN workflow_templates t ON t.id = w.template_id
                                      WHERE w.owner_did=:o ORDER BY w.created_at DESC LIMIT :l"""),
                             {"o": owner_did, "l": max(1, min(limit, 200))})).mappings().all()
    return [{"id": r["id"], "title": r["title"], "status": r["status"], "total_budget": str(r["total_budget"]),
             "currency": r["currency"], "created_at": str(r["created_at"]),
             "template": _template_block(dict(r), r["template_title"])} for r in rows]


def _owned(w: dict, agent_did: str) -> None:
    if w["owner_did"] != agent_did:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Only the workflow's owner can do this")


async def _owners_by_step(db: AsyncSession, steps: list[dict], orders: dict[str, dict]) -> dict[str, Any]:
    """The owner of each step's awarded worker: it depends on the steps, not on who is asking, so a read of many bidders asks once."""
    owners: dict[str, Any] = {}
    for s in steps:
        o = orders.get(s["order_id"] or "")
        wd = (o or {}).get("worker_did")
        if wd:
            owners[s["step_key"]] = (await db.execute(text("SELECT creator_developer_id FROM agents WHERE did=:d"),
                                                      {"d": wd})).scalar()
    return owners


async def _facts(db: AsyncSession, bidder_did: str, price: Optional[float], steps: list[dict], orders: dict[str, dict],
                 owners: Optional[dict[str, Any]] = None) -> dict:
    from agentvault_registry.services import reputation_bond as _rb
    a = (await db.execute(text("SELECT reputation_score, organization_id, creator_developer_id FROM agents WHERE did=:d"),
                          {"d": bidder_did})).mappings().first()
    proven = (await db.execute(text("SELECT count(*) FROM guild_work_orders WHERE worker_did=:d AND status='settled'"),
                               {"d": bidder_did})).scalar() or 0
    if owners is None:
        owners = await _owners_by_step(db, steps, orders)
    return {"bonded": await _rb.is_bonded_did(db, bidder_did),
            "reputation": float(a["reputation_score"]) if a and a["reputation_score"] is not None else None,
            "proven_orders": int(proven), "price": price,
            "org_id": str(a["organization_id"]) if a and a["organization_id"] else None,
            "owner": a["creator_developer_id"] if a else None, "owners_by_step": owners}


async def gate(db: AsyncSession, order_id: str, bidder_did: str, price: Optional[float], *, stage: str) -> None:
    """Deny-only, before any escrow: refuse a bid (stage 'bid') or an award (stage 'award') on an order that carries a workflow
    step when the bidder fails the step's rules (the workflow's, tightened by the step's). An order that is no step's: no-op."""
    row = (await db.execute(text("SELECT workflow_id, step_key FROM agent_workflow_steps WHERE order_id=:o"),
                            {"o": order_id})).mappings().first()
    if not row:
        return
    w = await _load_workflow(db, row["workflow_id"])
    steps = await _load_steps(db, row["workflow_id"])
    step = next(s for s in steps if s["step_key"] == row["step_key"])
    rules = wr.merge(w["ruleset"], step["ruleset"])
    if not rules:
        return
    orders = await _orders_of(db, [s for s in steps if s["step_key"] != step["step_key"]])
    fails = wr.evaluate(rules, await _facts(db, bidder_did, price, steps, orders))
    if fails:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=wr.refusal_sentence(fails))


async def candidates(db: AsyncSession, wid: str, step_key: str, limit: int = 50) -> dict:
    """Which agents on THIS registry pass the step's rules (the workflow's, tightened by the step's). A price rule is not
    evaluated here (no price yet). Agents of other registries are not read in this slice."""
    w = await _load_workflow(db, wid)
    steps = await _load_steps(db, wid)
    step = next((s for s in steps if s["step_key"] == step_key), None)
    if not step:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No such step")
    rules = wr.merge(w["ruleset"], step["ruleset"])
    orders = await _orders_of(db, [s for s in steps if s["step_key"] != step_key])
    owners = await _owners_by_step(db, steps, orders)
    rows = (await db.execute(text("""SELECT did, reputation_score, organization_id, creator_developer_id, reputation_bond_status
                                     FROM agents WHERE status='active' AND did <> :o
                                     ORDER BY reputation_score DESC NULLS LAST LIMIT 200"""), {"o": w["owner_did"]})).mappings().all()
    # Security read W4: the facts of all the candidates in two reads (the agent rows above, one grouped count here), not four
    # reads each (about a thousand queries a call). The facts are the ones `_facts` reads for one bidder.
    from agentvault_registry.services import reputation_bond as _rb
    dids = [r["did"] for r in rows]
    proven: dict[str, int] = {}
    if dids:
        stmt = text("SELECT worker_did, count(*) AS n FROM guild_work_orders WHERE status='settled' AND worker_did IN :d "
                    "GROUP BY worker_did").bindparams(bindparam("d", expanding=True))
        proven = {r["worker_did"]: int(r["n"]) for r in (await db.execute(stmt, {"d": dids})).mappings().all()}
    passing, refused = [], 0
    no_price = {k: v for k, v in rules.items() if k != "max_price"}
    for r in rows:
        bond = r["reputation_bond_status"]
        facts = {"bonded": _rb.is_bonded_status(bond) if bond is not None else await _rb.is_bonded_did(db, r["did"]),
                 "reputation": float(r["reputation_score"]) if r["reputation_score"] is not None else None,
                 "proven_orders": proven.get(r["did"], 0), "price": 0.0,
                 "org_id": str(r["organization_id"]) if r["organization_id"] else None,
                 "owner": r["creator_developer_id"], "owners_by_step": owners}
        fails = wr.evaluate(no_price, facts)
        if fails:
            refused += 1
        elif len(passing) < limit:
            passing.append(r["did"])
    return {"step": step_key, "rules": rules, "scope": "agents of this registry only", "passing": passing,
            "refused": refused, "considered": len(rows)}


POSTING_LOCK_S = 120


def _lock_key(step_id: Any) -> str:
    return f"workflows:posting:{step_id}"


async def _redis():
    try:
        from agentvault_registry.background_tasks.leader import get_redis
        return await get_redis()
    except Exception:  # noqa: BLE001
        return None


async def advance(db: AsyncSession, agent, wid: str) -> dict:
    """Owner only. Record the settled steps' output hashes and receipts, then post the NEXT step's Guild order (one at a time).
    Idempotent: calling it again with nothing new changes nothing."""
    w = await _load_workflow(db, wid)
    _owned(w, agent.did)
    if w["status"] == "cancelled":
        raise _bad("The workflow is cancelled", status.HTTP_409_CONFLICT)
    steps = await _load_steps(db, wid)
    orders = await _orders_of(db, steps)
    prev_receipt = wr.GENESIS
    for s in steps:
        if s["receipt"]:
            prev_receipt = s["receipt"]
            continue
        o = orders.get(s["order_id"] or "")
        if o and o["status"] == "settled":
            h = wr.output_hash(o["deliverable"])
            r = wr.step_receipt(prev_receipt, s["step_key"], h)
            await db.execute(text("UPDATE agent_workflow_steps SET output_hash=:h, receipt=:r WHERE id=:i AND receipt IS NULL"),
                             {"h": h, "r": r, "i": s["id"]})
            s["output_hash"], s["receipt"] = h, r
            prev_receipt = r
        break  # steps run in order: nothing after an unsettled step is read
    posted = None
    nxt = next((s for s in steps if not s["receipt"]), None)
    r = await _redis()
    if nxt is not None and nxt["order_id"] is not None and nxt["order_id"] not in orders:
        # a claim whose order is not there: another call is posting it right now, or a stop left it. Cleared only when a lock
        # that nothing holds proves nobody is posting (without Redis that cannot be proved, and nothing is guessed).
        if r is None or await r.get(_lock_key(nxt["id"])) is not None:
            raise _bad("This step is being posted, or a call that was posting it stopped: try again in a minute",
                       status.HTTP_409_CONFLICT)
        await db.execute(text("UPDATE agent_workflow_steps SET order_id=NULL WHERE id=:i AND order_id=:o"),
                         {"i": nxt["id"], "o": nxt["order_id"]})
        await db.commit()
        nxt["order_id"] = None
    if nxt is not None and nxt["order_id"] is None:
        spent = sum((Decimal(str(s["budget"])) for s in steps if s["order_id"]), Decimal(0))
        if spent + Decimal(str(nxt["budget"])) > Decimal(str(w["total_budget"])):
            raise _bad("Posting this step would exceed the workflow's total budget", status.HTTP_409_CONFLICT)
        src = next((s for s in steps if s["step_key"] == nxt["input_from"]), None) if nxt["input_from"] else None
        spec = (nxt["spec"] or "").strip()
        spec += f"\n\nRole: {nxt['role']}."
        if nxt["acceptance"]:
            spec += f"\nAcceptance: {nxt['acceptance']}"
        if src is not None:
            spec += f"\nInput: the output of step {src['step_key']} (order {src['order_id']}), output hash {src['output_hash']}."
        spec += f"\nPart of workflow {w['id']} ({w['title']}), ruleset hash {w['ruleset_hash']}."
        from agentvault_registry.routers import guild as _g
        # Security read W1: the step is linked to the id the order WILL have before the order exists, so there is no moment the
        # order is open and unlinked (the ruleset gate finds its step from the first bid). A stop between the claim and the order's
        # insert leaves a claim naming an order that is not there; the next advance clears it once nothing holds the posting lock.
        oid = _g.new_order_id()
        if r is not None and not await r.set(_lock_key(nxt["id"]), "1", nx=True, ex=POSTING_LOCK_S):
            raise _bad("Another call is posting this step", status.HTTP_409_CONFLICT)
        try:
            claim = await db.execute(text("UPDATE agent_workflow_steps SET order_id=:o WHERE id=:i AND order_id IS NULL"),
                                     {"o": oid, "i": nxt["id"]})
            if getattr(claim, "rowcount", 0) == 0:
                raise _bad("Another call is posting this step", status.HTTP_409_CONFLICT)
            await db.commit()
            try:
                res = await _g._post_order(_g.OrderPostIn(
                    title=f"[{w['title']}] {nxt['role']}"[:200], spec=spec[:8000], bounty=float(nxt["budget"]),
                    currency=w["currency"], deadline_seconds=nxt["deadline_seconds"]), agent, db, order_id=oid)
            except Exception:
                await db.rollback()
                await db.execute(text("UPDATE agent_workflow_steps SET order_id=NULL WHERE id=:i AND order_id=:o"),
                                 {"i": nxt["id"], "o": oid})
                await db.commit()
                raise
        finally:
            if r is not None:
                try:
                    await r.delete(_lock_key(nxt["id"]))
                except Exception:  # noqa: BLE001 — the lock expires on its own
                    pass
        if res["order_id"] != oid:      # the Guild gave another id: the step follows the order that exists
            await db.execute(text("UPDATE agent_workflow_steps SET order_id=:o WHERE id=:i"), {"o": res["order_id"], "i": nxt["id"]})
        posted = res["order_id"]
    steps2 = await _load_steps(db, wid)
    new_status = "done" if steps2 and all(s["receipt"] for s in steps2) else "running"
    await db.execute(text("UPDATE agent_workflows SET status=:s, updated_at=now() WHERE id=:i"), {"s": new_status, "i": wid})
    await db.commit()
    out = await view(db, wid)
    out["posted_order_id"] = posted
    return out


async def cancel(db: AsyncSession, agent, wid: str) -> dict:
    w = await _load_workflow(db, wid)
    _owned(w, agent.did)
    steps = await _load_steps(db, wid)
    orders = await _orders_of(db, steps)
    live = [s["step_key"] for s in steps if s["order_id"] and (orders.get(s["order_id"]) or {}).get("status") not in ("settled", *_ENDED)]
    if live:
        raise _bad("Cancel or settle the open step order first (" + ", ".join(live) + "), then cancel the workflow",
                   status.HTTP_409_CONFLICT)
    await db.execute(text("UPDATE agent_workflows SET status='cancelled', updated_at=now() WHERE id=:i"), {"i": wid})
    await db.commit()
    return await view(db, wid)
