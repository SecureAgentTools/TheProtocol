"""§TWOAGENT (2026-09-23) — the DIRECT contract create routes a foreign provider like /engage, or refuses.

Measured EU -> ASIA: `POST /api/v1/contracts/v2` with `provider_did` = an agent homed on ASIA answered 200
`offered` with `counterparty_home_registry` empty, and ASIA's `contract_replicas` held no row 25 s later: the
provider could never see or accept the offer. /engage passes the resolved home (§XHIRE) and refuses an unroutable
one (§HIRECOHERE); the direct create now asks the same predicate.

RED on the pre-change tree: the routed and the refused cases (the local control passes on both).
"""
from __future__ import annotations

import asyncio
import types

import pytest
from fastapi import HTTPException

from agentvault_registry.routers import contracts_v2 as mod

AGENT = types.SimpleNamespace(did="did:theprotocol:eu.theprotocol.cloud:client", id=1)
FOREIGN = "did:theprotocol:asia.theprotocol.cloud:provider"
LOCAL = "did:theprotocol:eu.theprotocol.cloud:provider"


def _wire(monkeypatch, *, src_for, home_for):
    minted = {}

    async def _load_card(db, did):
        return ({}, "n", src_for.get(did), "ASIA" if src_for.get(did) else None)

    async def _home(db, src, src_name):
        h = home_for.get(src)
        return (h, None) if h else (None, f"This agent is homed on {src_name}. (unroutable)")

    async def _mint(db, **kw):
        minted.update(kw)
        return {"id": "ctr_test", "status": "offered", "total_amount": "1"}
    monkeypatch.setattr(mod, "_require_enabled", lambda: None)
    monkeypatch.setattr(mod, "_load_card", _load_card)
    monkeypatch.setattr(mod, "_foreign_contract_home", _home)
    monkeypatch.setattr(mod, "mint_contract", _mint)
    return minted


def _create(provider):
    body = mod.ContractCreateIn(title="t", contract_type="work_order", total_amount="1", provider_did=provider)
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(mod.create_contract_v2(body, None, agent=AGENT, db=None))
    finally:
        loop.close()


def test_a_foreign_provider_is_minted_with_its_home_registry(monkeypatch):
    src = "spiffe://asia.theprotocol.cloud/registry/asia"
    minted = _wire(monkeypatch, src_for={FOREIGN: src}, home_for={src: "asia"})
    _create(FOREIGN)
    assert minted["counterparty_home_registry"] == "asia"


def test_an_unroutable_foreign_provider_is_refused_not_stranded(monkeypatch):
    minted = _wire(monkeypatch, src_for={FOREIGN: "spiffe://nowhere.example/registry/x"}, home_for={})
    with pytest.raises(HTTPException) as e:
        _create(FOREIGN)
    assert e.value.status_code == 409 and "homed on" in e.value.detail
    assert minted == {}, "nothing may be minted for an offer that cannot reach its provider"


def test_a_local_provider_is_unchanged(monkeypatch):
    minted = _wire(monkeypatch, src_for={}, home_for={})
    _create(LOCAL)
    assert minted["provider_did"] == LOCAL and minted.get("counterparty_home_registry") is None


# ── the door itself (§TWOAGENT #28, then G2): a resolvable foreign home opens only where the acceptance can land ────

def _door(monkeypatch, *, mode, carries=True):
    from agentvault_registry.services import contract_xframe as xf
    monkeypatch.setattr(xf, "enabled", lambda: mode in ("shadow", "enforce"))
    monkeypatch.setattr(xf, "mode", lambda: mode)

    async def _resolved(db, v):
        return "asia"

    async def _carries(db, peer):
        return carries
    monkeypatch.setattr(xf, "resolve_peer_name", _resolved)
    monkeypatch.setattr(mod, "_peer_carries_contract_commands", _carries)
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            mod._foreign_contract_home(None, "spiffe://asia.theprotocol.cloud/registry/asia", "ASIA"))
    finally:
        loop.close()


def test_the_door_refuses_a_resolvable_foreign_home_in_shadow_and_says_why(monkeypatch):
    home, reason = _door(monkeypatch, mode="shadow")
    assert home is None and "shadow" in reason and "acceptance would not be applied" in reason


def test_the_door_opens_in_enforce_when_the_providers_registry_carries_acceptance(monkeypatch):
    assert _door(monkeypatch, mode="enforce") == ("asia", None)


def test_the_door_stays_shut_in_enforce_for_a_registry_with_no_courier(monkeypatch):
    home, reason = _door(monkeypatch, mode="enforce", carries=False)
    assert home is None and "no contract courier" in reason


def test_the_switched_off_reason_is_unchanged(monkeypatch):
    from agentvault_registry.services import contract_xframe as xf
    monkeypatch.setattr(xf, "enabled", lambda: False)
    loop = asyncio.new_event_loop()
    try:
        home, reason = loop.run_until_complete(mod._foreign_contract_home(None, "spiffe://x/registry/y", "ASIA"))
    finally:
        loop.close()
    assert home is None and "switched off" in reason
