"""§MCPTEST30 (V0640): the showcase's refusal says which of its two off states it is.

A registry with no SHOWCASE_CATALOG_JSON holds the built-in catalog, which describes another deployment, so main.py
turns the showcase off there (§CARDLINK); every showcase route then answered "The showcase is disabled on this
deployment.", the same words as a showcase switched off by SHOWCASE_ENABLED. On the sandbox frames (2026-10-24) the
console suite's buy door read as NOT MEASURED on that sentence with SHOWCASE_ENABLED unset on both. Pinned: the switched-off
refusal is unchanged; the no-catalog refusal keeps that first sentence (the API tester's classifier and the console
read it) and names the cause; main.py's four showcase refusals all say it through one helper and none keeps the old
literal; the API tester's verdict names the cause it was given.
"""
from __future__ import annotations

import ast
import pathlib

from agentvault_registry.services.showcase_visitor import SHOWCASE_OFF, showcase_off_sentence

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"


def test_a_switched_off_showcase_says_what_it_said():
    assert showcase_off_sentence(False) == SHOWCASE_OFF == "The showcase is disabled on this deployment."


def test_a_registry_with_no_catalog_of_its_own_says_so_after_the_same_first_sentence():
    s = showcase_off_sentence(True)
    assert s.startswith("The showcase is disabled on this deployment")
    assert "the showcase is disabled on this deployment" in s.lower(), "the API tester's classifier phrase"
    assert "no showcase services of its own" in s and "another deployment" in s
    assert s != showcase_off_sentence(False)


def _strings(path):
    return [n.value for n in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def test_main_says_every_showcase_refusal_through_the_helper():
    tree = ast.parse((SRC / "main.py").read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_showcase_off_sentence"]
    assert len(calls) == 4, f"the session, list, call and address refusals; read {len(calls)}"
    assert not [s for s in _strings(SRC / "main.py") if "showcase is disabled on this deployment" in s], \
        "a literal left in main.py says 'disabled' whatever the cause"


def test_the_api_testers_verdict_names_the_cause():
    texts = _strings(SRC / "routers" / "admin_api_test.py")
    assert any("no showcase services of its own" in t for t in texts), "the no-catalog marker is read"
    assert any("switched off on this frame by configuration" in t for t in texts), "the switch's verdict stays"
