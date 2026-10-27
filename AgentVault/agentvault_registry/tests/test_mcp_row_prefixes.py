"""§MCPTEST30 (V0636): every probe family's row prefix is kept by the runner and placed by the console.

The runner keeps a lifecycle row that names no tool only when its name starts with one of _SYNTHETIC_ROW_PREFIXES; any
other such row is dropped without a word. `zk v2: ` was missing from that tuple, so the 15 rows of the zk v2
attestation lifecycle were dropped on every run since V0612 (found by agentvault2-66: the 2026-10-23 03:00Z nightly
held 0 of them in 1244 rows). And the console places a row in a family by its prefix (probeFamilies.ts), so a prefix it
does not know falls into "Admin · Other". Every prefix constant the probe modules define is read here, by AST, and
must be in both.
"""
from __future__ import annotations

import ast
import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
CONTRACTS = SRC / "api_tests" / "contracts"
RUNNER = SRC / "api_tests" / "categories" / "flow_mcp_lifecycle" / "test_flow_mcp_lifecycle.py"
FAMILIES = SRC / "static" / "new_registry_frontend" / "src" / "services" / "mcpTester" / "probeFamilies.ts"
_CONST = re.compile(r"^_?[A-Z][A-Z0-9_]*$")


def _prefix_constants():
    """{prefix: "module.NAME"} for every module-level string constant (an upper-case name) that ends in ': '."""
    out = {}
    for f in sorted(CONTRACTS.glob("*.py")):
        for node in ast.parse(f.read_text()).body:
            if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)):
                continue
            v = node.value.value
            if not (v.endswith(": ") and 2 < len(v) < 30):
                continue
            for t in node.targets:
                if isinstance(t, ast.Name) and _CONST.match(t.id):
                    out.setdefault(v, f"{f.stem}.{t.id}")
    return out


def _runner_prefixes():
    for node in ast.parse(RUNNER.read_text()).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_SYNTHETIC_ROW_PREFIXES"
                                                for t in node.targets):
            return {e.value for e in node.value.elts}
    raise AssertionError("_SYNTHETIC_ROW_PREFIXES not found in the runner")


def test_the_census_finds_the_known_prefixes():
    found = _prefix_constants()
    for p in ("hygiene: ", "zk v2: ", "admin_effect: ", "refusal: ", "commons: "):
        assert p in found, p


def test_the_runner_keeps_every_probe_familys_rows():
    kept = _runner_prefixes()
    missing = {p: where for p, where in _prefix_constants().items() if p not in kept}
    assert not missing, f"rows of these families are dropped unread: {missing}"


def test_the_console_places_every_probe_familys_rows():
    ids = set(re.findall(r"family\('([a-z0-9_]+)'", FAMILIES.read_text()))
    unplaced = {p: where for p, where in _prefix_constants().items() if p[:-2].replace(" ", "_") not in ids}
    assert not unplaced, f"the console has no family for: {unplaced}"
