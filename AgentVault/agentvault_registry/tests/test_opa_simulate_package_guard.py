"""§MTLSHOPS (2026-09-15) — the OPA policy simulation refuses a module in OPA's own `system` package.

`POST /admin/opa/simulate` uploads a candidate module under a scratch id, replays decisions against it and deletes it.
OPA ORs the rules of every module in one package together, so once OPA authorizes its API by path through
`data.system.authz` (the frame template's native mTLS for OPA), a scratch `package system.authz` carrying
`allow { true }` would open that API for the seconds it exists. The guard is a pure function, checked before the upload.
RED control: the tree before this change has no `refuses_system_package`, so every test here fails there.
"""
from __future__ import annotations

import ast
import inspect

from agentvault_registry.routers import admin_opa as ao


def test_the_package_statement_is_read():
    assert ao.rego_package("package agentvault.invariants\n\ndefault ok := true\n") == "agentvault.invariants"
    assert ao.rego_package("# a comment\n  package system.authz\nallow { true }\n") == "system.authz"
    assert ao.rego_package("default ok := true\n") is None


def test_system_packages_are_refused():
    for rego in ("package system\nx := 1\n", "package system.authz\nallow { true }\n",
                 'package system["authz"]\nallow { true }\n', "# header\n\npackage system.log\nmask := []\n"):
        assert ao.refuses_system_package(rego), rego


def test_other_packages_pass_including_the_prefix_trap():
    for rego in ("package agentvault.invariants\nok := true\n", "package systemic.checks\nok := true\n",
                 "# package system\npackage agentvault.authz\nallow := true\n", "no package at all\n"):
        assert not ao.refuses_system_package(rego), rego


def test_the_guard_runs_before_the_upload():
    fn = ast.parse(inspect.getsource(ao.opa_simulate))
    guard = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Call)
             and getattr(n.func, "id", None) == "refuses_system_package"]
    upload = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Attribute) and n.func.attr == "put"]
    assert guard and upload and min(guard) < min(upload), (guard, upload)
