"""§FEFRAME W4 residue (V0521, his words 2026-10-01 "improvements also approved"): the retired frames' letters are
gone from the admin ledger reads and the diagnostics targets.

- routers/admin_health.py: `frame` means this registry ("local", empty, or its own name). A letter used to resolve as
  a FOREIGN frame through EVENT_STORE_{A,B,C}_URL, which no current node sets, and answered EMPTY; every EU/ASIA
  registry also called itself "A" by the default. Now anything but this registry is refused by name (404).
- services/diagnostics: MAINFRAME_TARGETS carried five retired mainframes (inert: only a node named like an entry
  enumerated one), and every operator target was labelled frame "A". The list is empty and an operator carries this
  registry's own name ("T" stays for a frame-test's chained operator).
agentvault2-30 confirmed 2026-10-01 that no MCP tester contract or api-tester flow sends a frame letter.
"""
import ast
import inspect

import pytest
from fastapi import HTTPException

from agentvault_registry.routers import admin_health
from agentvault_registry.services.diagnostics import targets
from agentvault_registry.services.diagnostics.schemas import TargetSummary


@pytest.fixture
def named(monkeypatch):
    monkeypatch.setenv("REGISTRY_FEDERATION_NAME", "Asia")
    monkeypatch.setenv("EVENT_STORE_URL", "https://asia-es.example:8443")
    monkeypatch.setenv("EVENT_STORE_API_KEY", "k")
    # what the letters used to read: set them, and prove they no longer route anything
    monkeypatch.setenv("EVENT_STORE_A_URL", "http://retired-frame-a:8200")
    monkeypatch.setenv("LOCAL_FRAME", "A")


def test_local_means_this_registry_only(named):
    for f in ("local", "LOCAL", "", "asia", "ASIA", " Asia "):
        assert admin_health._is_local_frame(f), f
    for f in ("A", "B", "C", "a", "eu", "registry-a"):
        assert not admin_health._is_local_frame(f), f


def test_a_letter_is_refused_by_name_not_answered_empty(named):
    with pytest.raises(HTTPException) as e:
        admin_health._resolve_event_store("A")
    assert e.value.status_code == 404
    assert "'A' is not this registry" in str(e.value.detail)


def test_this_registry_reads_its_own_store(named):
    assert admin_health._resolve_event_store("local") == ("https://asia-es.example:8443", "k")
    assert admin_health._resolve_event_store("asia") == ("https://asia-es.example:8443", "k")
    assert admin_health._reported_frame("local") == "asia"


def test_without_a_name_only_the_sentinel_is_local(monkeypatch):
    monkeypatch.delenv("REGISTRY_FEDERATION_NAME", raising=False)
    monkeypatch.delenv("REGISTRY_NAME", raising=False)
    assert admin_health._is_local_frame("local") and admin_health._is_local_frame("")
    assert not admin_health._is_local_frame("A")
    assert admin_health._reported_frame("") == "local"


def test_no_letter_lookup_survives_in_the_router():
    """Read on the AST, not the text: the docstrings above name what went (a text gate finds its own documentation)."""
    tree = ast.parse(inspect.getsource(admin_health))
    env_reads, built_names, functions = set(), [], {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
            f = n.func
            if (isinstance(f, ast.Attribute) and f.attr in ("getenv", "get")):
                env_reads.add(n.args[0].value)
        if isinstance(n, ast.JoinedStr):
            text = "".join(v.value for v in n.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
            if "EVENT_STORE_" in text and "_URL" in text:
                built_names.append(ast.unparse(n))
    assert not ({"LOCAL_FRAME", "FRAME_ID", "SPIRE_TRUST_DOMAIN"} & env_reads), env_reads
    assert built_names == [], built_names
    assert "_local_frame" not in functions
    # the control: the reader does see this module's own env reads
    assert "EVENT_STORE_URL" in env_reads and "REGISTRY_FEDERATION_NAME" in env_reads


def test_diagnostics_names_no_retired_mainframe():
    assert targets.MAINFRAME_TARGETS == []


def test_an_operator_target_carries_this_registry_not_a_letter(named):
    assert targets._operator_target("shenzhen", None, None)["frame"] == "asia"
    assert targets._operator_target("api-test-operator-3", None, None)["frame"] == "T"
    # the schema takes a name now (the Literal of letters would 500 the whole rail)
    TargetSummary(operator_id="op-shenzhen", display_name="shenzhen", frame="asia", role="operator")
