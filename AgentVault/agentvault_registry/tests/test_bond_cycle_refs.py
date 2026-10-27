"""§MCPTEST30 (2026-10-01) — a bond cycle's money moves under ONE reference, whoever asks and however often.

Release, unlock and a re-bond deposit each persisted a reference minted per REQUEST (`uuid4`) before moving money, which
makes a retry safe (it reads the persisted ref back) but not a duplicate: two requests that load the row before either
commits each mint their own, and the treasury pays twice under two keys (or a re-bond charges the funder twice). The ref
is now derived from what the cycle already holds, so two racers ask the TEG under one key and its durable dedup
(teg_idempotency_records, the key is the primary key) moves the money once. Found by reading the rails while looking for
races the MCP tester can drive; maturity and the release cooldown are out of a run's reach, so these tests are the
measurement. A re-bond also kept the ended cycle's maturity unlock, so every bond after the first read
"already_unlocked". Every race test fails against the uuid-per-request code (its control).
"""
from __future__ import annotations

import asyncio
import copy
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://t:t@localhost:5432/t")
os.environ.setdefault("API_KEY_SECRET", "test-only-secret-value-0123456789abcdef")

from agentvault_registry.services import escrow as esc  # noqa: E402
from agentvault_registry.services import reputation_bond as rb  # noqa: E402

DID = "did:theprotocol:bondrace"


def _row(**kw):
    base = dict(id="b1", agent_did=DID, amount=Decimal("250"), status="matured",
                locked_at=datetime.now(timezone.utc) - timedelta(days=45),
                matured_at=datetime.now(timezone.utc) - timedelta(days=10),
                released_at=None, forfeited_at=None, funded_by="wallet", funder_did="did:theprotocol:w",
                escrow_ref="repbond-cycle-1", teg_transaction_id="t", release_ref=None, release_teg_transaction_id=None,
                forfeit_ref=None, forfeit_reason=None, partial_released_amount=None, partial_released_at=None,
                partial_release_ref=None, partial_release_teg_transaction_id=None, updated_at=None, created_at=None)
    base.update(kw)
    return SimpleNamespace(**base)


class _DB:
    def add(self, o):
        pass

    async def commit(self):
        await asyncio.sleep(0)

    async def refresh(self, o):
        return None


def _agent():
    return SimpleNamespace(did=DID, reputation_bond_amount=Decimal("250"), reputation_bond_status="matured")


def _wire(monkeypatch, row, racers, refs):
    """Each request loads its OWN copy of the one row, and none goes on until `racers` have loaded it (the race)."""
    loaded = []
    gate = asyncio.Event()

    async def load_bond(db, did):
        mine = copy.copy(row)
        loaded.append(mine)
        if len(loaded) >= racers:
            gate.set()
        await gate.wait()
        return mine

    async def activity_batch(db, dids):
        return {d: dict(rb._NO_ACTIVITY, transactions=12, rated_peers=4, trust_percentile=80.0,
                        trust_population=17) for d in dids}

    async def noop(*a, **k):
        return None

    async def payout(db, target, amount, ref, reason=""):
        refs.append(ref)
        return {"transaction_id": f"tx-{len(refs)}"}

    async def deposit_leg(funder, amount, ref, reason=""):
        refs.append(ref)
        return {"transaction_id": f"tx-{len(refs)}"}

    async def policy(db):
        return {}

    monkeypatch.setattr(rb, "load_bond", load_bond)
    monkeypatch.setattr(rb, "activity_batch", activity_batch)
    monkeypatch.setattr(rb, "touch_native_card", noop)
    monkeypatch.setattr(rb, "_emit", noop)
    monkeypatch.setattr(rb, "policy_json", policy)
    monkeypatch.setattr(rb, "bond_amount", lambda policy=None: Decimal("250"))
    monkeypatch.setattr(esc, "escrow_payout", payout)
    monkeypatch.setattr(esc, "escrow_deposit", deposit_leg)
    return loaded


def _twice(fn, monkeypatch, row):
    refs = []
    loaded = _wire(monkeypatch, row, 2, refs)

    async def go():
        return await asyncio.gather(fn(), fn())

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(go())
    finally:
        loop.close()
    return refs, loaded


def test_two_releases_at_once_ask_the_treasury_under_one_key(monkeypatch):
    refs, loaded = _twice(lambda: rb.release(_DB(), _agent(), actor="test", policy={}), monkeypatch, _row())
    assert len(refs) == 2, refs
    assert len(set(refs)) == 1, f"two keys for one bond's release: the treasury pays twice ({refs})"
    assert all(b.release_ref == refs[0] for b in loaded), "the ref persisted is the ref asked under"
    assert refs[0].startswith(f"repbond-release-{DID}-") and len(refs[0].rsplit("-", 1)[1]) == 10


def test_two_unlocks_at_once_ask_the_treasury_under_one_key(monkeypatch):
    refs, loaded = _twice(lambda: rb.unlock(_DB(), _agent(), actor="test", policy={}), monkeypatch, _row())
    assert len(refs) == 2 and len(set(refs)) == 1, f"two keys for one unlock: the treasury pays twice ({refs})"
    assert refs[0].startswith(f"repbond-unlock-{DID}-")


def test_two_rebond_deposits_at_once_charge_under_one_key(monkeypatch):
    ended = _row(status="released", released_at=datetime.now(timezone.utc) - timedelta(days=1),
                 release_ref="repbond-release-x", partial_released_at=datetime.now(timezone.utc) - timedelta(days=3),
                 partial_released_amount=Decimal("150"), partial_release_ref="repbond-unlock-x",
                 partial_release_teg_transaction_id="tx-old")
    agent = SimpleNamespace(did=DID, reputation_bond_amount=Decimal("0"), reputation_bond_status="released")
    refs, loaded = _twice(lambda: rb.deposit(_DB(), agent, funder_did=DID, funded_by="self", actor="test", policy={}),
                          monkeypatch, ended)
    assert len(refs) == 2 and len(set(refs)) == 1, f"two keys for one re-bond: the funder is charged twice ({refs})"
    assert refs[0] != "repbond-cycle-1" and refs[0].startswith(f"repbond-{DID}-"), "a new cycle, a new key"


def test_a_rebond_clears_the_ended_cycles_unlock(monkeypatch):
    ended = _row(status="released", released_at=datetime.now(timezone.utc) - timedelta(days=1),
                 partial_released_at=datetime.now(timezone.utc) - timedelta(days=3),
                 partial_released_amount=Decimal("150"), partial_release_ref="repbond-unlock-x",
                 partial_release_teg_transaction_id="tx-old")
    refs = []
    loaded = _wire(monkeypatch, ended, 1, refs)
    agent = SimpleNamespace(did=DID, reputation_bond_amount=Decimal("0"), reputation_bond_status="released")
    loop = asyncio.new_event_loop()
    try:
        bond = loop.run_until_complete(rb.deposit(_DB(), agent, funder_did=DID, funded_by="self", actor="test",
                                                  policy={}))
    finally:
        loop.close()
    assert bond.status == "locked" and refs == [bond.escrow_ref]
    for f in ("partial_released_amount", "partial_released_at", "partial_release_ref",
              "partial_release_teg_transaction_id"):
        assert getattr(bond, f) is None, f"{f} survived the re-bond"
    bond.status, bond.matured_at = "matured", datetime.now(timezone.utc) - timedelta(days=30)
    th = {"releases_percent": 60}
    assert rb.unlock_block(bond, th)["reason"] != "already_unlocked", "the new bond's unlock is its own"


def test_a_retry_reads_the_persisted_ref_even_one_minted_per_request(monkeypatch):
    """A payout that failed after its ref was persisted (by this code or the uuid code before it) is retried under
    THAT ref, never a new one, so a payout the TEG did make is answered from its record."""
    refs = []
    _wire(monkeypatch, _row(release_ref="repbond-release-old-0123456789"), 1, refs)
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(rb.release(_DB(), _agent(), actor="test", policy={}))
    finally:
        loop.close()
    assert refs == ["repbond-release-old-0123456789"]


def test_cycles_and_agents_never_share_a_key():
    a = rb._cycle_ref(f"repbond-release-{DID}", "b1", "repbond-cycle-1", "2026-09-01T00:00:00+00:00")
    assert a == rb._cycle_ref(f"repbond-release-{DID}", "b1", "repbond-cycle-1", "2026-09-01T00:00:00+00:00")
    assert a != rb._cycle_ref(f"repbond-release-{DID}", "b1", "repbond-cycle-2", "2026-09-01T00:00:00+00:00")
    assert a != rb._cycle_ref("repbond-release-did:theprotocol:other", "b1", "repbond-cycle-1",
                              "2026-09-01T00:00:00+00:00")
    assert a != rb._cycle_ref(f"repbond-unlock-{DID}", "b1", "repbond-cycle-1", "2026-09-01T00:00:00+00:00")
    assert rb._cycle_ref("p", None, "x") == rb._cycle_ref("p", "", "x"), "an unset part reads as empty, by design"
    assert rb._cycle_ref("p", None, "x") != rb._cycle_ref("p", "None", "x")


def test_every_field_a_cycle_writes_is_reset_by_both_rebond_paths():
    """The class behind the unlock defect: §BONDFILL-3 added four fields the unlock writes and neither re-bond path
    learned them. Whatever release, unlock, forfeit or the maturity stamp writes on a bond belongs to ONE cycle, so both
    paths that open a new cycle must write it too. Read from the module's assignments (`bond.<field> = ...`), never its
    comments. Against d21e5817's reputation_bond.py it names the four partial_* fields for both paths."""
    import ast
    import pathlib

    tree = ast.parse(pathlib.Path(rb.__file__).read_text())
    writes = {}
    for fn in (n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
        names = set()
        for node in ast.walk(fn):
            targets = node.targets if isinstance(node, ast.Assign) else (
                [node.target] if isinstance(node, (ast.AugAssign, ast.AnnAssign)) else [])
            names |= {t.attr for t in targets if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name)
                      and t.value.id == "bond"}
        writes[fn.name] = names
    cycle = set().union(*(writes[f] for f in ("release", "unlock", "forfeit", "stamp_matured")))
    assert {"partial_released_at", "release_ref", "forfeited_at", "matured_at"} <= cycle, "the census reads the writes"
    for opener in ("deposit", "backstop"):
        missing = sorted(cycle - writes[opener])
        assert not missing, f"{opener} opens a new cycle and leaves the last one's {missing}"
