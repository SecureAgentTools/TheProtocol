"""§SPAWN-ANCHOR — mutation-verified integration test for the purse resolver.

Runs against a REAL Postgres (see scratchpad/test_spawn_anchor_harness.sh), so it
exercises the actual JSONB caveat filter ``(caveats ->> 'birth') = 'true'`` and the
birth-token issuer-chain walk — not a mock. Asserts the five load-bearing behaviours:

  1. anchored child (birth token issuer=parent) → purse = parent      (redirect works)
  2. non-anchored capability                     → purse = acting self (no false redirect)
  3. SPAWN_WALLET_ANCHOR_MODE=off + anchored cap → purse = acting self (byte-inert off)
  4. grandchild anchored under an anchored child → purse = grandparent (walks the chain)
  5. issuer with no wallet-holding agent row      → purse = acting self (fail-CLOSED)

Mutation-verify: the harness re-runs this against a mutated module where
``_cap_is_anchored`` always returns False; test 1 must then FAIL — proving the suite
kills a broken resolver rather than passing vacuously.

Exit 0 = all pass; exit 1 = any assertion failed (prints which).
"""
import asyncio
import datetime as dt
import os
import sys
from types import SimpleNamespace

import pytest

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

# §CHATCOHERE-CI (2026-09-01) — this used to be a bare `os.environ[...]`, which
# raises KeyError at IMPORT time. Under pytest that is a COLLECTION error, and a
# collection error does not fail one file: it INTERRUPTS the whole run. The other
# 262 registry tests never executed because this one wanted a database.
#
# A test that needs infrastructure the runner does not have must SKIP and say why.
# The harness (scratchpad/test_spawn_anchor_harness.sh) sets ANCHOR_TEST_DB and is
# unaffected — nothing about the DB-backed behaviour changed.
DB = os.environ.get("ANCHOR_TEST_DB")  # postgresql+asyncpg://...
if not DB:
    pytest.skip(
        "needs a REAL Postgres: set ANCHOR_TEST_DB "
        "(scratchpad/test_spawn_anchor_harness.sh). Skipped, never silently passed.",
        allow_module_level=True,
    )

PARENT = "did:theprotocol:parent"
CHILD = "did:theprotocol:child"
GRAND = "did:theprotocol:grandchild"
GHOST = "did:theprotocol:ghostparent"


def _req(cap):
    return SimpleNamespace(state=SimpleNamespace(ironkey_capability=cap))


def _birth_cap(issuer, anchored):
    cav = {"birth": True}
    if anchored:
        cav["anchored"] = True
    return {"id": 1, "issuer_did": issuer, "caveats": cav}


async def main() -> int:
    from agentvault_registry.models import Base, Agent, Developer, AgentCapabilityToken
    from agentvault_registry.crud.agent import get_agent_by_did
    from agentvault_registry.services import spawn_anchor as SA

    engine = create_async_engine(DB)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    # ── schema: self-reset then full metadata create_all (dependency-ordered; a table
    #    subset pulls in FK targets like fiat_purchases, so build the whole thing). The
    #    DROP SCHEMA makes every run — real and mutant — start from a clean DB. ──
    from sqlalchemy import text as _text
    async with engine.begin() as conn:
        await conn.execute(_text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(_text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)

    # ── seed: one developer, one wallet-holding parent agent, two anchored birth tokens ──
    async with Session() as s:
        dev = Developer(name="anchor-test-dev", email="anchor@test.local", hashed_password="x")
        s.add(dev)
        await s.flush()
        # All three have IDENTITY rows (agents) — anchoring removes only the TEG WALLET
        # (agent_teg_profiles), never the registry identity. The FK on the capability-token
        # issuer/holder to agents.did enforces exactly this. parent holds a wallet; child +
        # grandchild are anchored (walletless) but still real agents.
        for did, cid in ((PARENT, "cid-parent"), (CHILD, "cid-child"), (GRAND, "cid-grand")):
            s.add(Agent(did=did, client_id=cid, hashed_client_secret="x", creator_developer_id=dev.id))
        await s.flush()
        exp = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)

        def tok(issuer, holder, anchored, pfx):
            cav = {"birth": True}
            if anchored:
                cav["anchored"] = True
            return AgentCapabilityToken(
                token_hash=f"h-{pfx}", token_prefix=pfx[:12], issuer_agent_did=issuer,
                holder_agent_did=holder, caveats=cav, status="issued", expires_at=exp)

        s.add(tok(PARENT, CHILD, True, "bt-child"))     # parent → child (anchored)
        s.add(tok(CHILD, GRAND, True, "bt-grand"))      # child  → grandchild (anchored)
        await s.commit()

    child = SimpleNamespace(did=CHILD, id=90001)         # acting, walletless (no agents row)
    grand = SimpleNamespace(did=GRAND, id=90002)
    failures = []

    async def check(label, cond, got):
        if cond:
            print(f"  PASS  {label}")
        else:
            print(f"  FAIL  {label}  got={got}")
            failures.append(label)

    async with Session() as s:
        parent = await get_agent_by_did(s, PARENT)
        assert parent is not None, "seed parent missing"

        os.environ["SPAWN_WALLET_ANCHOR_MODE"] = "on"

        # 1 — anchored child → purse = parent
        pa, pd = await SA.resolve_spend_purse_agent(s, child, _req(_birth_cap(PARENT, True)))
        await check("1 anchored child → parent purse", pd == PARENT and pa.id == parent.id, (pd, getattr(pa, "id", None)))

        # 2 — non-anchored cap → purse = acting self
        pa, pd = await SA.resolve_spend_purse_agent(s, child, _req(_birth_cap(PARENT, False)))
        await check("2 non-anchored → acting self", pd == CHILD and pa is child, pd)

        # 3 — mode off → acting self even with an anchored cap
        os.environ["SPAWN_WALLET_ANCHOR_MODE"] = "off"
        pa, pd = await SA.resolve_spend_purse_agent(s, child, _req(_birth_cap(PARENT, True)))
        await check("3 mode=off → acting self (byte-inert)", pd == CHILD and pa is child, pd)
        os.environ["SPAWN_WALLET_ANCHOR_MODE"] = "on"

        # 4 — grandchild anchored under anchored child → walk to grandparent (wallet holder)
        pa, pd = await SA.resolve_spend_purse_agent(s, grand, _req(_birth_cap(CHILD, True)))
        await check("4 grandchild → grandparent purse (chain walk)", pd == PARENT and pa.id == parent.id, (pd, getattr(pa, "id", None)))

        # 5 — anchored cap whose issuer has no wallet-holding agent row → fail-closed to self
        pa, pd = await SA.resolve_spend_purse_agent(s, child, _req(_birth_cap(GHOST, True)))
        await check("5 no wallet-holder → fail-closed to self", pd == CHILD and pa is child, pd)

        # direct unit coverage of the two helpers (extra kill surface)
        await check("6 _cap_is_anchored true-case", SA._cap_is_anchored(_birth_cap(PARENT, True)) is True, None)
        await check("7 _cap_is_anchored false-case", SA._cap_is_anchored(_birth_cap(PARENT, False)) is False, None)
        wh = await SA._walk_to_wallet_holder(s, CHILD)
        await check("8 _walk_to_wallet_holder(child) → parent", wh == PARENT, wh)

    await engine.dispose()
    if failures:
        print(f"\nRESULT: {len(failures)} FAILED: {failures}")
        return 1
    print("\nRESULT: ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
