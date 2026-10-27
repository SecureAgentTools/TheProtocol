"""§SHOWCASEDID (2026-09-26): the public showcase call pays the agent its catalog names.

Measured on EU once it had a payer: ip and password completed and settled, weather and timezone answered 402. The call
looked the target up by NAME across every agent card (natives and MIRRORED foreign cards alike) and paid the first
match: for weather and timezone that was ASIA's mirrored agent, so EU's own agent refused a token made out to another
agent. The catalog already names the exact DID (§FRAMELIC row 148 made the LIST read it); the call path never did.

Also here: a catalog written for a frame (SHOWCASE_CATALOG_JSON) is priced in that frame's currency, so the reply says
ECU/ACU rather than AVT; and the charge fields are bound before the payment branch, since the reply reads them.

These are source gates (the handler lives inside the app factory). RED control: the tree before the fix fails all four.
"""
from __future__ import annotations

import ast
import os
import pathlib

_HERE = pathlib.Path(__file__).resolve()
_PKG = pathlib.Path(os.environ["OPDIST_SRC"]) if os.environ.get("OPDIST_SRC") else (
    _HERE.parents[1] / "src" / "agentvault_registry")
MAIN = _PKG / "main.py"


def _fn(name):
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    for n in ast.walk(tree):
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == name:
            return n
    raise AssertionError(f"{name} not found")


def _src(node):
    return ast.get_source_segment(MAIN.read_text(encoding="utf-8"), node)


def test_the_call_pays_the_catalog_did_first():
    src = _src(_fn("showcase_call"))
    assert "target_did = _SHOWCASE_DIDS.get(service) or _svc_did_map.get(service)" in src, \
        "the catalog's DID must decide the payee before any name lookup"


def test_the_name_fallback_never_reaches_a_mirrored_card():
    src = _src(_fn("showcase_call"))
    assert ".where(_CardModel.agent_did.in_(_sq_select(_AgentModel.did)))" in src, \
        "the fallback must consider this frame's own agents only (a mirrored card has no agents row here)"


def test_a_frames_own_catalog_is_charged_in_its_own_currency():
    text = MAIN.read_text(encoding="utf-8")
    assert '_showcase_state["catalog_local"] = True' in text, "the catalog loader must say its prices are local"
    src = _src(_fn("showcase_call"))
    assert 'if _showcase_state.get("catalog_local"):' in src and "charge_ccy = _local" in src


def test_the_charge_fields_are_bound_before_the_payment_branch():
    fn = _fn("showcase_call")
    src = _src(fn)
    bind = src.find('charge_ccy = "AVT"')
    branch = src.find("if _showcase_jwt_cache:")
    assert bind != -1 and branch != -1 and bind < branch, "the reply reads charge_ccy on every path"
    assert src.count('charge_ccy = "AVT"') == 1, "one binding, before the branch"
