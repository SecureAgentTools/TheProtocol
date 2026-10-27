"""§MCPTEST30 (V0644, agentvault2-66 with agentvault2-aa, 2026-10-26): the registry states what it is.

No registry said "sandbox" anywhere a target publishes: registry-config had no environment, the cards say only
identity.tier, and SANDBOX_MODE runs on the two sandbox frames and not on their operators. The MCP tester's own
_is_sandbox_target() reads hints in API_TEST_TARGET_URL, a name. registry-config now says `environment`, read from
core/registry_environment.registry_environment ("production" when REGISTRY_ENVIRONMENT is unset), and an operator
inherits its frame's value. Structural (the AST) where the reader is main.py's closure, behavioural for the function and
the inheritance.
"""
from __future__ import annotations

import ast
import io
import pathlib

import pytest

from agentvault_registry.core import registry_environment as RE
from agentvault_registry.services import cloud_provisioner as cp

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"


def _registry_config_fn() -> ast.AsyncFunctionDef:
    tree = ast.parse((SRC / "main.py").read_text(encoding="utf-8"))
    fns = [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "public_registry_config"]
    assert len(fns) == 1
    return fns[0]


def test_registry_config_states_the_environment_from_the_one_function():
    fn = _registry_config_fn()
    keys = {}
    for n in ast.walk(fn):
        if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict):
            for k, v in zip(n.value.keys, n.value.values):
                if isinstance(k, ast.Constant):
                    keys[k.value] = ast.unparse(v)
    assert keys.get("environment") == "_registry_environment()", sorted(keys)
    imports = {(n.module, a.name, a.asname) for n in ast.walk(fn) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert ("agentvault_registry.core.registry_environment", "registry_environment", "_registry_environment") in imports


@pytest.mark.parametrize("raw,said", [
    (None, "production"), ("", "production"), ("   ", "production"),
    ("sandbox", "sandbox"), (" sandbox ", "sandbox"), ("Sandbox", "Sandbox"), ("production", "production"),
])
def test_an_unset_registry_says_production_and_a_set_one_its_value(monkeypatch, raw, said):
    """Unset reads "production", so a misdirected run fails closed; the case is kept, because the tester's check is exact."""
    if raw is None:
        monkeypatch.delenv("REGISTRY_ENVIRONMENT", raising=False)
    else:
        monkeypatch.setenv("REGISTRY_ENVIRONMENT", raw)
    assert RE.registry_environment() == said


def test_an_operator_inherits_its_frames_environment(monkeypatch):
    for k in cp.PARENT_POSTURE_KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("REGISTRY_ENVIRONMENT", "sandbox")
    buf = io.StringIO()
    assert cp._inherit_parent_posture(buf) == ["REGISTRY_ENVIRONMENT"]
    assert buf.getvalue() == "REGISTRY_ENVIRONMENT=sandbox\n"


def test_a_frame_that_states_nothing_hands_its_operator_nothing(monkeypatch):
    """Control: a production frame (the variable unset) writes no line, so its operator reads "production" too."""
    for k in cp.PARENT_POSTURE_KEYS:
        monkeypatch.delenv(k, raising=False)
    buf = io.StringIO()
    assert cp._inherit_parent_posture(buf) == []
    assert "REGISTRY_ENVIRONMENT" not in buf.getvalue()
