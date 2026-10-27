"""D6-058 and D6-060 (agentvault2-d6, 2026-10-25): an answer names the unit of the figure it gives.

D6-058: both FX pool routes keep the AVT/BVT pool's key order, so on a frame whose unit is not AVT their x is the PEER
frame's reserve. The admin FX desk labelled x with this frame's unit (EU showed ASIA's ACU reserve as ECU, its own ECU
reserve as ACU and the spot's unit inverted) and the agent route's note said "AVT numeraire". The answers now name each
figure's unit (x_currency, y_currency, mtm_currency); the keys stay.
D6-060: the cross-registry slash and settlement messages said AVT whatever the frame's unit, and the fiat rail's refusal
on every registry that is not the fiat genesis registry said "Federated registries cannot mint AVT ... Acquire AVT".

RED control: against V0640's tree (54e0255d) the pool routes name no unit (the drives fail on the missing keys and the
missing helper), the disputes module's message literals say AVT, and the fiat refusal says AVT.
"""
from __future__ import annotations

import ast
import asyncio
import pathlib
import re
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from agentvault_registry.routers import federation_disputes as FD
from agentvault_registry.routers import fiat_onramp as F
from agentvault_registry.routers import teg_integration as T

_AVT = re.compile(r"\bAVT\b")
_LOG_CALLS = {"debug", "info", "warning", "error", "exception", "critical", "warn"}


def _run(coro):
    # a fresh loop of its own: asyncio.run() would leave the NEXT test file without one
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _route(fn):
    # the rate limiter's decorator sits on the route; the function under it is what this drives
    return getattr(fn, "__wrapped__", fn)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._rows))


class _Db:
    """Answers every select with the one ACTIVE frame peer: both pool routes read the peer list once."""

    def __init__(self, rows):
        self.rows = rows

    async def execute(self, *_a, **_k):
        return _Result(self.rows)


ASIA = SimpleNamespace(peer_type="frame", name="asia", status="ACTIVE")


@pytest.fixture
def eu_beside_asia(monkeypatch):
    """EU (ECU) in pool mode beside ASIA (ACU): ASIA's reserve 1000 ACU, EU's own 900 ECU."""
    monkeypatch.setenv("FRAME_CURRENCY", "ECU")
    monkeypatch.setenv("FX_RATE_MODE", "pool")
    monkeypatch.setenv("TEG_API_BASE_URL", "http://eu-teg:8080")
    monkeypatch.setattr(T, "_fx_enabled", lambda: True)

    async def peer_ccy(db, target_peer=None):
        return "ACU"

    async def asia_base(*_a, **_k):
        return "https://asia-teg:8443"

    async def reserve(base, _key):
        return Decimal("1000") if "asia" in base else Decimal("900")

    async def receiver_home(db, did):
        return "teg-layer-asia", "registry-asia"

    monkeypatch.setattr(T, "_resolve_peer_currency", peer_ccy)
    monkeypatch.setattr(T, "_resolve_dest_teg_mtls_base", asia_base)
    monkeypatch.setattr(T, "_fx_priced_reserve_base", asia_base)
    monkeypatch.setattr(T, "_fx_leaf_gateway", lambda *_a, **_k: None)
    monkeypatch.setattr(T, "_fx_read_reserve", reserve)
    monkeypatch.setattr(T, "_resolve_receiver_registry", receiver_home)


def test_the_legs_follow_the_pool_keys_order():
    assert T._fx_pool_legs("AVT", "BVT") == ("AVT", "BVT"), "an AVT frame: x is its own reserve, as the keys say"
    assert T._fx_pool_legs("BVT", "AVT") == ("AVT", "BVT"), "beside an AVT frame: x is still the AVT reserve"
    assert T._fx_pool_legs("ECU", "ACU") == ("ACU", "ECU"), "off AVT: x is the PEER's reserve"


def test_the_admin_pool_names_each_figures_unit(eu_beside_asia):
    out = _run(_route(T.fx_pool_admin)(request=None, db=_Db([ASIA]), _admin=None))
    assert out["available"] is True, out
    assert (out["x"], out["y"]) == (1000.0, 900.0), "x is ASIA's reserve on EU (the keys' order is unchanged)"
    assert (out["x_currency"], out["y_currency"], out["mtm_currency"]) == ("ACU", "ECU", "ACU")
    assert out["currency_pair"] == "ECU/ACU"


def test_the_agent_pool_names_each_figures_unit_and_its_note_no_avt(eu_beside_asia):
    out = _run(_route(T.fx_pool)(request=None, receiver_did="did:theprotocol:asia-receiver",
                                 current_agent=None, db=_Db([ASIA])))
    assert (out.x_avt, out.y_bvt) == ("1000", "900")
    assert (out.x_currency, out.y_currency, out.mtm_currency) == ("ACU", "ECU", "ACU")
    assert "in ACU" in out.note and not _AVT.search(out.note), out.note
    assert "—" not in out.note


def test_control_an_avt_frame_keeps_its_own_reserve_as_x(eu_beside_asia, monkeypatch):
    monkeypatch.setenv("FRAME_CURRENCY", "AVT")

    async def peer_ccy(db, target_peer=None):
        return "BVT"

    monkeypatch.setattr(T, "_resolve_peer_currency", peer_ccy)
    out = _run(_route(T.fx_pool_admin)(request=None, db=_Db([ASIA]), _admin=None))
    assert (out["x"], out["y"]) == (900.0, 1000.0), "on an AVT frame x is the local reserve"
    assert (out["x_currency"], out["y_currency"], out["mtm_currency"]) == ("AVT", "BVT", "AVT")


def _answer_literals(path: pathlib.Path):
    """(line, text) of every string literal a caller can read: docstrings, comments and log calls left out."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            skip.add(id(body[0].value))
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name in _LOG_CALLS:
                skip.update(id(sub) for sub in ast.walk(node))
    out = []
    for node in ast.walk(tree):
        if id(node) in skip:
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append((node.lineno, node.value))
        elif isinstance(node, ast.JoinedStr):
            for part in node.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    skip.add(id(part))
                    out.append((node.lineno, part.value))
    return out


def test_no_slash_or_settlement_message_names_avt():
    src = pathlib.Path(FD.__file__).with_suffix(".py")
    found = [(line, text) for line, text in _answer_literals(src) if _AVT.search(text)]
    assert not found, f"a literal AVT in a disputes message: {found}"


def test_the_disputes_messages_ask_the_frames_unit(monkeypatch):
    monkeypatch.setenv("FRAME_CURRENCY", "ACU")
    assert FD.frame_currency() == "ACU", "the module's unit is the frame's, asked in core.frame_currency"
    src = pathlib.Path(FD.__file__).with_suffix(".py").read_text(encoding="utf-8")
    assert src.count("{frame_currency()}") >= 12, "each slash and settlement message names the unit it was written in"


def test_the_fiat_refusal_off_the_genesis_registry_names_no_unit(monkeypatch):
    monkeypatch.delenv("FIAT_GENESIS_REGISTRY", raising=False)
    monkeypatch.setenv("FRAME_CURRENCY", "ECU")
    with pytest.raises(HTTPException) as e:
        F._require_runtime_ready()
    assert e.value.status_code == 403
    assert "mainframe-only by construction" in e.value.detail, "the MCP tester's contract reads this phrase"
    assert "FIAT_GENESIS_REGISTRY" in e.value.detail
    assert not _AVT.search(e.value.detail), e.value.detail


def test_control_on_the_genesis_registry_the_switch_still_decides(monkeypatch):
    monkeypatch.setenv("FIAT_GENESIS_REGISTRY", "true")
    monkeypatch.setenv("FIAT_ONRAMP_ENABLED", "false")
    with pytest.raises(HTTPException) as e:
        F._require_runtime_ready()
    assert e.value.status_code == 503, "the genesis registry refuses only for its switch"
