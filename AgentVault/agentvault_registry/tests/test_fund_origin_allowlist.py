"""§MONEY-R50 (2026-09-04, his word "r50 approved too") — the cross-TEG funding-origin allowlist a
provisioned frame renders is, by construction, the value its own guard accepts.

Before: the frame template put CROSS_TEG_FUND_ORIGIN_ALLOWLIST in the TEG's env block (no reader;
the guard is `routers/teg_integration.py`), so the registry saw the default `registry-a`; and the
value was the container name (`sbx-alpha`) through no slug rule, while the guard compares the slug
of REGISTRY_NAME (`sandbox-alpha` on a frame that carries its display name). Measured by
agentvault2-07: `403 … This registry is 'Sandbox Alpha' (slug='sandbox-alpha'); allowlist=[…]`.

RED control: `R50_TREE=<dir with the pre-fix agentvault_registry/ src and templates/>`.
"""
from __future__ import annotations

import ast
import importlib.util
import os
import pathlib

import pytest

HERE = pathlib.Path(__file__).resolve().parent
TREE = pathlib.Path(os.environ["R50_TREE"]) if os.environ.get("R50_TREE") else None
REG_SRC = (TREE / "agentvault_registry" / "src" / "agentvault_registry") if TREE else (HERE.parent / "src" / "agentvault_registry")
TEMPLATE = (TREE / "templates" / "frame-test" / "docker-compose.frame-test.yml.tmpl") if TREE else (
    HERE.parent.parent.parent / "templates" / "frame-test" / "docker-compose.frame-test.yml.tmpl")
SLUG_MOD = REG_SRC / "core" / "registry_slug.py"


def _mod():
    if not SLUG_MOD.exists():
        pytest.fail(f"core/registry_slug.py is missing in {REG_SRC} (the ONE copy of the rule)")
    spec = importlib.util.spec_from_file_location("registry_slug_under_test", SLUG_MOD)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def test_registry_slug_is_the_guards_rule():
    m = _mod()
    assert m.registry_slug("Sandbox Alpha") == "sandbox-alpha"
    assert m.registry_slug("sbx-alpha") == "sbx-alpha"
    assert m.registry_slug("Frame C") == "frame-c"
    assert m.registry_slug("Régistry Ünïcode ") == "registry-unicode"
    assert m.registry_slug(" -x- ") == "x" and m.registry_slug("") == "" and m.registry_slug(None) == ""


def test_parse_allowlist_defaults_to_registry_a_when_unset_or_empty():
    m = _mod()
    assert m.parse_fund_origin_allowlist(None) == {"registry-a"}
    assert m.parse_fund_origin_allowlist("") == {"registry-a"}
    assert m.parse_fund_origin_allowlist("   ") == {"registry-a"}
    assert m.parse_fund_origin_allowlist(" registry-a , Frame-B ,, ") == {"registry-a", "frame-b"}


def test_guard_semantics_are_unchanged_for_prod_shapes():
    m = _mod()
    assert m.fund_origin_allowed("Registry A", None) is True            # unset ⇒ registry-a
    assert m.fund_origin_allowed("Frame B", "registry-a,frame-b") is True
    assert m.fund_origin_allowed("Frame B", None) is False                # a frame absent from its own list
    assert m.fund_origin_allowed("AgentVault Registry", "registry-a") is False


def test_the_defect_the_old_value_refused_its_own_frame():
    """What 07 measured: container-name value vs display-name slug."""
    m = _mod()
    assert m.fund_origin_allowed("Sandbox Alpha", "sbx-alpha") is False
    assert m.fund_origin_allowed("Sandbox Alpha", m.fund_origin_allowlist_value("sbx-alpha", "Sandbox Alpha")) is True


def test_rendered_value_own_slug_first_both_names_then_extras_deduped():
    m = _mod()
    assert m.fund_origin_allowlist_value("sbx-alpha") == "sbx-alpha"
    assert m.fund_origin_allowlist_value("sbx-alpha", "", ["sbx-beta"]) == "sbx-alpha,sbx-beta"
    assert m.fund_origin_allowlist_value("sbx-alpha", "Sandbox Alpha", ["sbx-beta", "sbx-alpha", "", "Sandbox Alpha"]) == "sbx-alpha,sandbox-alpha,sbx-beta"
    assert m.fund_origin_allowlist_value("sbx-alpha", "sbx-alpha") == "sbx-alpha"


def test_end_to_end_a_frame_funds_under_either_name_it_may_carry():
    """Whatever the frame ends up carrying as REGISTRY_NAME — the container name the template
    renders, or the display name a standup gives it — the rendered allowlist admits it."""
    m = _mod()
    for container, display in (("sbx-alpha", "Sandbox Alpha"), ("frame-x", "Frame X"), ("op-frame", "")):
        value = m.fund_origin_allowlist_value(container, display, ["registry-a"])
        for name in (container, display or container):
            assert m.fund_origin_allowed(name, value), (name, value)
        assert m.fund_origin_allowed("Registry A", value)   # the extra origin still admitted


def test_template_renders_the_key_on_the_registry_service_only():
    # §BATCH4 item 4: the template lives in the STACK repo (templates/frame-test/); the AgentVault checkout in CI
    # cannot see it, so this test was a guaranteed FileNotFoundError there. The property is pinned where the
    # file lives (.forgejo/checks/frame_template_contract.py, CROSS_TEG_FUND_ORIGIN_ALLOWLIST) — here it SKIPS
    # by name (the CI skip ceiling counts it) instead of failing for a reason that is not the code's.
    if not TEMPLATE.is_file():
        pytest.skip(f"R50 template fixture not in this checkout ({TEMPLATE}); set R50_TREE to the stack root — "
                    "the stack repo's frame_template_contract.py pins the same key")
    text = TEMPLATE.read_text(encoding="utf-8")
    block, where = None, {}
    for ln in text.splitlines():
        if ln.startswith("  {{REGISTRY_NAME}}-") and ln.rstrip().endswith(":"):
            block = ln.strip()[len("{{REGISTRY_NAME}}-"):-1]
        if "CROSS_TEG_FUND_ORIGIN_ALLOWLIST:" in ln and not ln.lstrip().startswith("#"):
            where[block] = where.get(block, 0) + 1
    assert where == {"registry": 1}, where


def test_provisioner_and_guard_call_the_one_rule():
    prov = (REG_SRC / "services" / "frame_test_provisioner.py").read_text(encoding="utf-8")
    assert "fund_origin_allowlist_value(" in prov and "core.registry_slug import fund_origin_allowlist_value" in prov
    tree = ast.parse(prov)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_template_values")
    assert "fund_origin_allowlist_value(" in ast.get_source_segment(prov, fn)
    guard = (REG_SRC / "routers" / "teg_integration.py").read_text(encoding="utf-8")
    assert "fund_origin_allowed(registry_name, allowed_env)" in guard
    assert "core.registry_slug import" in guard
    assert not any(isinstance(n, ast.FunctionDef) and n.name == "_slug" for n in ast.parse(guard).body), "a local _slug copy survived"
