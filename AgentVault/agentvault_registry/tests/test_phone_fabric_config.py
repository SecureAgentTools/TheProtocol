"""D6-841 (agentvault2-5b, 2026-10-25): the registry says whether its Phone Fabric is on, from the same function its rails
refuse on, so the console asks the owner rail only where it is.

Found by the console suite's lifecycle 72 in the V0641 proof on sbx-beta: GET /api/v1/phone/sessions/mine answers 503 where
PHONE_FABRIC_ENABLED is off, and once owned agents act through the session (V0641) Pocket's approvals asked it on every
visit to a registry without the fabric. registry-config said nothing about the fabric. Now it says `phone_fabric_enabled`,
read from core/phone_fabric_gate.phone_fabric_enabled (one predicate, two readers: the gate and the console). Structural (the
AST) where the reader is main.py's closure, behavioural for the predicate.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"


def _registry_config_fn() -> ast.AsyncFunctionDef:
    tree = ast.parse((SRC / "main.py").read_text(encoding="utf-8"))
    fns = [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "public_registry_config"]
    assert len(fns) == 1
    return fns[0]


def test_registry_config_says_whether_the_phone_fabric_is_on_from_the_rails_own_function():
    fn = _registry_config_fn()
    keys = {}
    for n in ast.walk(fn):
        if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict):
            for k, v in zip(n.value.keys, n.value.values):
                if isinstance(k, ast.Constant):
                    keys[k.value] = ast.unparse(v)
    assert keys.get("phone_fabric_enabled") == "_phone_fabric_enabled()", sorted(keys)
    imports = {(n.module, a.name, a.asname) for n in ast.walk(fn) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert ("agentvault_registry.core.phone_fabric_gate", "phone_fabric_enabled", "_phone_fabric_enabled") in imports


def test_the_rails_refuse_on_the_same_predicate():
    from agentvault_registry.core import phone_fabric_gate as G
    from agentvault_registry.routers import phone_fabric as P
    assert P.phone_fabric_enabled is G.phone_fabric_enabled


@pytest.mark.parametrize("raw,on", [
    ("true", True), ("TRUE", True), (" true ", True), ("false", False), ("", False), (None, False), ("1", False),
])
def test_phone_fabric_enabled_reads_the_switch_its_rails_refuse_on(monkeypatch, raw, on):
    from agentvault_registry.routers import phone_fabric as P
    if raw is None:
        monkeypatch.delenv("PHONE_FABRIC_ENABLED", raising=False)
    else:
        monkeypatch.setenv("PHONE_FABRIC_ENABLED", raw)
    assert P.phone_fabric_enabled() is on
    if not on:
        with pytest.raises(Exception) as e:
            P._require_enabled()
        assert getattr(e.value, "status_code", None) == 503
