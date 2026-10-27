"""§LEDGERGATE C, the remaining callers (V0598, 2026-10-11; FINDINGS §9 S3): every registry path whose FIRST or ONLY TEG
movement the ledger gate can refuse passes the refusal on whole: 503, the sentence with its code word first, Retry-After.

Read on V0597 (fe/batch-v0597 edee13f7): the AGORA mover made any TEG non-200 a 502 "exchange mover 503: ..." and the
order and launch routes wrapped it again ("order deposit failed: ..."); the shared escrow rail (contracts, contract
templates, the guild, reputation bonds) made it "escrow deposit failed: ..." and its routes answered 402 "insufficient
balance?"; the flare shop and the CI/CD template payment answered 402; the organization treasury 502 "treasury move
failed: ..."; the treasury funding helper (payouts, the admin fund-agent rail) 503 "Treasury transfer failed: ..." after a
balance check a refusal makes pointless. Single-movement paths only: a refusal there means nothing moved. A route of
several legs keeps its own words (the console says the sentence only for a refusal passed on whole, V0598's other half).

These drive the mover, the escrow rail and the flare shop's charge with the TEG's real answer (a fake HTTP client), check
the helper and the AGORA router's mapping, and pin the mapping sites at the source. RED on edee13f7: all of them (the
helper is new, so the two controls fail there too); the controls pin what stays (a non-gate failure keeps its words, an
error with no refusal reads None).
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import json
import textwrap
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from agentvault_registry.services import ledger_unavailable as lu

SENTENCE_DETAIL = f"{lu.MARKER} {lu.SENTENCE}"


def _resp(status, body, headers=None):
    return httpx.Response(status, content=json.dumps(body).encode(),
                          headers={"content-type": "application/json", **(headers or {})})


def _gate(retry_after="25"):
    return _resp(503, {"detail": SENTENCE_DETAIL, "code": "ledger_unavailable", "status": 503,
                       "context": {"retry_after_s": 30}}, {"Retry-After": retry_after})


class _Client:
    """httpx.AsyncClient for one call: answers every POST with `resp`."""
    resp = None
    calls: list = []

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None, timeout=None):
        _Client.calls.append(url)
        return _Client.resp


@pytest.fixture()
def teg_answers(monkeypatch):
    def set_(resp):
        _Client.resp, _Client.calls = resp, []
        monkeypatch.setattr(httpx, "AsyncClient", _Client)
        return _Client
    return set_


# ── the helper ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_refusal_from_error_reads_every_shape_a_route_catches():
    from agentvault_registry.services.escrow import EscrowError
    from agentvault_registry.services.exchange_service import MoverError
    r = lu.refusal_from_error(MoverError(503, SENTENCE_DETAIL, headers={"Retry-After": "12"}))
    assert r.status_code == 503 and r.detail == SENTENCE_DETAIL and r.headers == {"Retry-After": "12"}
    r = lu.refusal_from_error(EscrowError(503, SENTENCE_DETAIL, headers={"retry-after": "7"}))
    assert r.status_code == 503 and r.headers == {"Retry-After": "7"}
    r = lu.refusal_from_error(Exception(f"treasury move failed: {SENTENCE_DETAIL}"))   # only the text kept it
    assert r.status_code == 503 and r.detail == SENTENCE_DETAIL and r.headers == {"Retry-After": "30"}


def test_control_an_error_with_no_refusal_reads_none():
    from agentvault_registry.services.escrow import EscrowError
    assert lu.refusal_from_error(EscrowError(402, "escrow deposit failed: Insufficient balance")) is None
    assert lu.refusal_from_error(HTTPException(503, "upstream timeout")) is None
    assert lu.refusal_from_error(None) is None


# ── the shared escrow rail ────────────────────────────────────────────────────────────────────────────────────────────

def test_a_refused_escrow_deposit_carries_the_refusal(teg_answers):
    from agentvault_registry.services import escrow
    client = teg_answers(_gate("25"))
    with pytest.raises(escrow.EscrowError) as ei:
        asyncio.run(escrow.escrow_deposit("did:theprotocol:payer-0001", Decimal("5"), "guildref:o1:hold"))
    assert client.calls and client.calls[0].endswith("/admin/treasury/receive")
    e = ei.value
    assert e.status_code == 503 and e.message == SENTENCE_DETAIL and e.headers == {"Retry-After": "25"}
    assert lu.refusal_from_error(e).headers == {"Retry-After": "25"}


def test_control_another_escrow_failure_keeps_its_words(teg_answers):
    from agentvault_registry.services import escrow
    teg_answers(_resp(400, {"detail": "Insufficient balance"}))
    with pytest.raises(escrow.EscrowError) as ei:
        asyncio.run(escrow.escrow_deposit("did:theprotocol:payer-0001", Decimal("5"), "guildref:o1:hold"))
    assert ei.value.status_code == 400 and ei.value.message == "escrow deposit failed: Insufficient balance"
    assert lu.refusal_from_error(ei.value) is None


# ── AGORA ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_agora_mover_passes_the_refusal_on_and_the_deposit_keeps_it_whole(teg_answers):
    from agentvault_registry.services import exchange_service as ex
    teg_answers(_gate("18"))
    with pytest.raises(ex.MoverError) as ei:
        asyncio.run(ex.mover.move("did:theprotocol:buyer-0001", ex.EXCHANGE_ESCROW_SENTINEL, Decimal("3"),
                                  "order_deposit", "ord-1:dep"))
    e = ei.value
    assert e.status_code == 503 and e.detail == SENTENCE_DETAIL and e.headers == {"Retry-After": "18"}
    out = ex._deposit_failed(e, "order deposit failed")
    assert out.status_code == 503 and out.detail == SENTENCE_DETAIL and out.headers == {"Retry-After": "18"}
    # any other mover failure keeps "order deposit failed: ..." (a control)
    other = ex._deposit_failed(ex.MoverError(400, "exchange mover 400: insufficient"), "order deposit failed")
    assert other.status_code == 400 and other.detail == "order deposit failed: exchange mover 400: insufficient"


def test_the_agora_router_carries_retry_after():
    from agentvault_registry.routers import exchange as router
    from agentvault_registry.services import exchange_service as ex
    h = router._err(ex.ExchangeError(503, SENTENCE_DETAIL, headers={"Retry-After": "9"}))
    assert h.status_code == 503 and h.detail == SENTENCE_DETAIL and h.headers == {"Retry-After": "9"}


# ── the flare shop ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_refused_flare_charge_is_503_and_its_row_failed(teg_answers):
    from agentvault_registry.routers import flare_shop
    teg_answers(_gate("21"))

    class _Db:
        def add(self, _o):
            pass

        async def commit(self):
            pass
    row = SimpleNamespace(status="pending", failure_reason=None)
    with pytest.raises(HTTPException) as ei:
        asyncio.run(flare_shop._charge_buyer(buyer=SimpleNamespace(did="did:theprotocol:buyer-0001"), amount=Decimal("2"),
                                             purchase_id="p1", tier="sentinel", db=_Db(), row=row))
    assert ei.value.status_code == 503 and ei.value.detail == SENTENCE_DETAIL and ei.value.headers == {"Retry-After": "21"}
    assert row.status == "failed" and row.failure_reason == "ledger_unavailable"


# ── the mapping sites, at the source ──────────────────────────────────────────────────────────────────────────────────

SITES = {
    # module: how many times its source asks refusal_from_error (each guarded catch, plus its import where module-level)
    "agentvault_registry.routers.contract_templates": 1,
    "agentvault_registry.routers.contracts_v2": 1,
    "agentvault_registry.routers.contracts": 2,
    "agentvault_registry.services.reputation_bond": 1,
    "agentvault_registry.routers.guild": 4,
    "agentvault_registry.routers.organizations": 3,
}


@pytest.mark.parametrize("module,calls", sorted(SITES.items()))
def test_each_escrow_and_treasury_route_asks_for_the_refusal_first(module, calls):
    import importlib
    tree = ast.parse(inspect.getsource(importlib.import_module(module)))
    asked = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "refusal_from_error"]
    assert len(asked) == calls, f"{module}: {len(asked)} calls of refusal_from_error, expected {calls}"
    # each one sits in an `except` handler, ahead of the handler's own raise
    for h in [n for n in ast.walk(tree) if isinstance(n, ast.ExceptHandler)]:
        src = ast.unparse(h)
        if "refusal_from_error(" in src:
            assert src.index("refusal_from_error(") < src.rindex("HTTPException("), src[:300]


def _fn_src(fn):
    return ast.unparse(ast.parse(textwrap.dedent(inspect.getsource(fn))))


def test_the_treasury_funding_helper_raises_the_refusal_before_its_balance_check():
    from agentvault_registry.routers import teg_integration as ti
    src = _fn_src(ti._fund_agent_from_treasury_internal)
    assert src.index("_refusal = ledger_refusal(response)") < src.index("Verifying actual balance")


def test_the_template_payment_raises_the_refusal_before_its_402():
    from agentvault_registry.services import agent_cicd_service as cicd
    src = inspect.getsource(cicd)
    assert src.index("_refusal = ledger_refusal(resp)") < src.index('detail=f"Template payment failed: {detail}"')
