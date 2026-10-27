"""§MCPTEST30 (V0641, D6-831, agentvault2-66 2026-10-25): the public showcase makes, and offers, only the paid calls
this frame can pay for, and relays only to a frame it names.

Measured 2026-10-25 (read-only): sbx-alpha listed its WeatherAgent (0.5 SBXA) with no showcase payer of its own; a
console run's showcase call skipped authorize, the agent answered 402, and showcase_call relayed the call to
SHOWCASE_RELAY_URL's default, https://api.theprotocol.cloud: production EU paid its own WeatherAgent 0.5 ECU and the
sandbox page said "WeatherAgent 0.5 SBXA SETTLED". Pinned:
- no relay unless a deployment names one (services/showcase_visitor.relay_base; the default is empty);
- call_refusals: a paid entry whose payee authorize would refuse gets authorize's sentence (403); a frame with neither
  a payer nor a named relay refuses every paid entry (503); a free entry needs neither check;
- main.py's wiring (source gates: the handlers live inside the app factory): the call refuses before it dials the
  agent, an authorize refusal is the answer before the agent is dialled without a token, the relay reads relay_base,
  the catalogue carries `callable` and `reason`, and the session and onboard refusals no longer promise a relay.
"""
from __future__ import annotations

import ast
import asyncio
import os
import pathlib

import pytest

from agentvault_registry.services import showcase_visitor as sv

_HERE = pathlib.Path(__file__).resolve()
_PKG = pathlib.Path(os.environ["OPDIST_SRC"]) if os.environ.get("OPDIST_SRC") else (
    _HERE.parents[1] / "src" / "agentvault_registry")
MAIN = _PKG / "main.py"


def _run(c):
    return asyncio.run(c)


def test_no_relay_unless_one_is_named(monkeypatch):
    monkeypatch.delenv("SHOWCASE_RELAY_URL", raising=False)
    assert sv.relay_base() == "", "a frame that names no relay has none (it was production EU)"
    monkeypatch.setenv("SHOWCASE_RELAY_URL", "")
    assert sv.relay_base() == ""
    monkeypatch.setenv("SHOWCASE_RELAY_URL", " https://frame.example.test/ ")
    assert sv.relay_base() == "https://frame.example.test"


def test_the_calls_tail_says_what_a_frame_without_identity_can_do():
    assert "relayed to https://frame.example.test" in sv.calls_tail("https://frame.example.test")
    t = sv.calls_tail("")
    assert "cannot be made here" in t and "relayed" not in t


@pytest.mark.parametrize("price,paid", [("0.5", True), ("0", False), (None, False), ("", False), ("abc", True)])
def test_entry_paid(price, paid):
    assert sv.entry_paid({"price": price}) is paid


_AGENTS = {"weather": {"price": "0.5"}, "ip": {"price": "0"}, "dns": {"price": "1.0"}, "units": {"price": "0.1"}}
_DIDS = {"weather": "did:theprotocol:w", "ip": "did:theprotocol:i", "dns": "did:theprotocol:d", "units": None}


def _refusals(*, refused=(), has_payer=True, relay=""):
    asked = []

    async def _payee(db, did):
        asked.append(did)
        return f"{did} holds no reputation bond." if did in refused else None

    out = _run(sv.call_refusals(None, list(_AGENTS), agents=_AGENTS, dids=_DIDS, has_payer=has_payer, relay=relay,
                                payee_refusal=_payee))
    return out, asked


def test_a_refused_payee_is_refused_with_authorizes_sentence():
    out, asked = _refusals(refused=("did:theprotocol:w",))
    assert out == {"weather": (403, "did:theprotocol:w holds no reputation bond.")}
    assert sorted(asked) == ["did:theprotocol:d", "did:theprotocol:w"], "only paid entries with a DID are asked"


def test_without_a_payer_and_a_relay_no_paid_call_is_offered():
    out, _ = _refusals(refused=("did:theprotocol:w",), has_payer=False)
    assert out["weather"] == (403, "did:theprotocol:w holds no reputation bond."), "the payee's own refusal first"
    assert out["dns"] == (503, sv.NO_PAYER) and out["units"] == (503, sv.NO_PAYER)
    assert "ip" not in out, "a free entry needs no payer"


@pytest.mark.parametrize("has_payer,relay", [(True, ""), (False, "https://frame.example.test")])
def test_a_payer_or_a_named_relay_can_pay(has_payer, relay):
    out, _ = _refusals(has_payer=has_payer, relay=relay)
    assert out == {}


# ── main.py's wiring ──────────────────────────────────────────────────────────

def _text():
    return MAIN.read_text(encoding="utf-8")


def _fn(name):
    tree = ast.parse(_text())
    for n in ast.walk(tree):
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == name:
            return ast.get_source_segment(_text(), n)
    raise AssertionError(f"{name} not found")


def test_the_relay_default_is_gone():
    t = _text()
    assert '_os.getenv("SHOWCASE_RELAY_URL", "https://' not in t, "no frame relays to a default"
    assert "relay_base = _showcase_relay_base()" in _fn("showcase_call")
    assert "return _sv.relay_base()" in _fn("_showcase_relay_base")


def test_the_call_refuses_before_it_dials():
    src = _fn("showcase_call")
    check = src.find("await _showcase_call_refusals([service])")
    assert check != -1, "the call asks the same refusals the catalogue shows"
    assert check < src.find("payload = {") and check < src.find("# ── Step 1"), "before the agent is dialled"
    assert '"callable": False' in src


def test_an_authorize_refusal_is_the_answer_to_a_paid_call():
    src = _fn("showcase_call")
    guard = src.find("if pay_refused is not None and _showcase_entry_paid(agent_info):")
    assert guard != -1 and guard < src.find("# ── Step 3"), "this frame's refusal, before the agent is dialled tokenless"
    assert "pay_refused = (pay_resp.status_code," in src


def test_the_refusals_ask_authorizes_payee_question():
    src = _fn("_showcase_call_refusals")
    assert "from agentvault_registry.routers.a2a_payment import payee_refusal as _payee_refusal" in src
    assert "payee_refusal=_payee_refusal" in src and "_sv.call_refusals(" in src


def test_the_catalogue_says_which_entries_can_be_called():
    src = _fn("showcase_list_agents")
    assert "await _showcase_call_refusals(list(_SHOWCASE_AGENTS))" in src
    assert 'entry["callable"] = key not in _refused' in src and 'entry["reason"] =' in src


def test_no_refusal_promises_a_relay_it_does_not_have():
    t = _text()
    assert "relayed to the hosting frame" not in t
    assert _fn("showcase_session").count("_showcase_calls_tail()") == 1
    assert _fn("showcase_onboard").count("_showcase_calls_tail()") == 1
