"""§FESUITE (2026-10-10, the operator batch) — a registry says what it runs, and the console follows it.

His word: "operators will choose what they want to run ultimately in frames allowed configuration ... operators will
run contracts and liability for sure". Measured on the sandbox operators' consoles: the Cockpit and Pocket Approvals
asked liability routes that answer 404 where LIABILITY_MODE is off, Contracts and the desk asked the template library
(503 where CONTRACT_TEMPLATES_ENABLED is off), and the Federation Test page asked /sandbox/a, which dialed registry-test
(a tier torn down at §BATCH3) and answered 502. The registry-config said none of it. Now:
  * registry-config says `liability_mode`, `contract_templates_enabled` and `sandbox_proxy`, read from the SAME
    functions the routes refuse on (one predicate, two readers: the gate and the console);
  * the sandbox proxy has no default upstream: unset is "no sandbox here", said with a 503 and the reason;
  * the device-key routes (WebAuthn enrolment, the legacy enclave key, revocation) no longer wait on LIABILITY_MODE:
    the phone-approved sign-in and Pocket's fingerprint lock sign with that key, so account security works on every
    registry, as the challenges' doctrine already says.
Behavioural where the module is cheap to load, structural (the AST) where the reader is main.py's closure.
"""
from __future__ import annotations

import ast
import importlib
import pathlib

import pytest
from fastapi import HTTPException

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"


def _registry_config_fn() -> ast.AsyncFunctionDef:
    tree = ast.parse((SRC / "main.py").read_text(encoding="utf-8"))
    fns = [n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "public_registry_config"]
    assert len(fns) == 1
    return fns[0]


def test_registry_config_says_what_this_registry_runs_from_the_routes_own_functions():
    fn = _registry_config_fn()
    keys = {}
    for n in ast.walk(fn):
        if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict):
            for k, v in zip(n.value.keys, n.value.values):
                if isinstance(k, ast.Constant):
                    keys[k.value] = ast.unparse(v)
    assert keys.get("liability_mode") == "_liability_mode()", sorted(keys)
    assert keys.get("contract_templates_enabled") == "_contract_templates_enabled()"
    assert keys.get("sandbox_proxy") == "_sandbox_proxies()"
    imports = {(n.module, a.name, a.asname) for n in ast.walk(fn) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert ("agentvault_registry.routers.liability", "liability_mode", "_liability_mode") in imports
    assert ("agentvault_registry.routers.contract_templates", "templates_enabled", "_contract_templates_enabled") in imports
    assert ("agentvault_registry.routers.sandbox_proxy", "configured_sandboxes", "_sandbox_proxies") in imports


# ── liability: one reading of the mode, the gate on it ─────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,mode", [
    ("enforce", "enforce"), ("shadow", "shadow"), (" SHADOW ", "shadow"), ("off", "off"), ("", "off"),
    (None, "off"), ("nonsense", "off"),
])
def test_liability_mode_reads_one_answer(monkeypatch, raw, mode):
    from agentvault_registry.routers import liability as L
    monkeypatch.setattr(L.settings, "LIABILITY_MODE", raw, raising=False)
    assert L.liability_mode() == mode
    if mode == "off":
        with pytest.raises(HTTPException) as exc:
            L._require_enabled()
        assert exc.value.status_code == 404
    else:
        assert L._require_enabled() is None


DEVICE_KEY_ROUTES = {
    "/api/v1/liability/webauthn/options", "/api/v1/liability/webauthn/register",
    "/api/v1/liability/devices/{device_id}/webauthn/options", "/api/v1/liability/devices/{device_id}/webauthn/register",
    "/api/v1/liability/devices/{device_id}/enroll-key", "/api/v1/liability/devices/{device_id}/revoke-key",
}


def _routes() -> dict:
    tree = ast.parse((SRC / "routers" / "liability.py").read_text(encoding="utf-8"))
    out = {}
    for n in tree.body:
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for d in n.decorator_list:
            if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.args and isinstance(d.args[0], ast.Constant):
                gates = {c.func.id for c in ast.walk(n) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                         and c.func.id.startswith("_require_enabled")}
                out[f"{d.func.attr.upper()} {d.args[0].value}"] = gates
    return out


def test_the_device_key_routes_work_where_liability_is_off(monkeypatch):
    routes = _routes()
    keyed = {k: g for k, g in routes.items() if k.split(" ", 1)[1] in DEVICE_KEY_ROUTES}
    assert len(keyed) == 6, sorted(keyed)
    for k, g in keyed.items():
        assert g == {"_require_enabled_for_device_keys"}, f"{k} still waits on LIABILITY_MODE: {g}"
    from agentvault_registry.routers import liability as L
    monkeypatch.setattr(L.settings, "LIABILITY_MODE", "off", raising=False)
    assert L._require_enabled_for_device_keys() is None


def test_the_mandate_routes_still_refuse_where_liability_is_off():
    """the control: only the device keys moved; the Cockpit Card's own routes keep their gate"""
    routes = _routes()
    for k in ("GET /api/v1/liability/delegatable", "POST /api/v1/liability/mandates", "GET /api/v1/liability/posture",
              "GET /api/v1/liability/receipts", "GET /api/v1/liability/intents/pending", "POST /api/v1/liability/challenges"):
        assert routes.get(k) == {"_require_enabled"}, (k, routes.get(k))


# ── the sandbox proxy: no dead default, an honest refusal, one list of what exists ─────────────────────────

def _proxy(monkeypatch, a=None, b=None):
    for name, val in (("SANDBOX_A_INTERNAL_URL", a), ("SANDBOX_B_INTERNAL_URL", b)):
        if val is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, val)
    from agentvault_registry.routers import sandbox_proxy
    return importlib.reload(sandbox_proxy)


def test_the_sandbox_proxy_names_no_torn_down_tier():
    src = (SRC / "routers" / "sandbox_proxy.py").read_text(encoding="utf-8")
    assert "registry-test:8000" not in src and "registry-test-b:8000" not in src


def test_an_unconfigured_sandbox_is_said_and_never_dialed(monkeypatch):
    import asyncio
    m = _proxy(monkeypatch)
    assert m.SANDBOX_A_URL == "" and m.SANDBOX_B_URL == ""
    assert m.configured_sandboxes() == []
    with pytest.raises(HTTPException) as exc:
        asyncio.run(m._proxy_to_sandbox(m.SANDBOX_A_URL, "api/v1/stack-health", request=None, frame="a"))
    assert exc.value.status_code == 503
    assert "No sandbox registry A is configured on this registry" in str(exc.value.detail)


def test_the_configured_sandboxes_are_listed_in_order(monkeypatch):
    m = _proxy(monkeypatch, a="http://sbx-alpha-registry:8000/", b="http://sbx-beta-registry:8000")
    assert m.SANDBOX_A_URL == "http://sbx-alpha-registry:8000"
    assert m.configured_sandboxes() == ["a", "b"]
    m = _proxy(monkeypatch, b="http://sbx-beta-registry:8000")
    assert m.configured_sandboxes() == ["b"]
    _proxy(monkeypatch)  # leave the module as an unconfigured registry loads it
