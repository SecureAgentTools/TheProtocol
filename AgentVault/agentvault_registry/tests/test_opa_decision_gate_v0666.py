"""V0666 OPA phase 2 step 1, close R1 (gwo_fb0b8c005e61af124e579601; DESIGN_2026-11-15_OPA_BACKSTOP.md sections 2, 3, 8, 10).

THE GATE ON DISCARDED DECISIONS. An OPA decision binds only where its caller uses the answer: shadow_check returns
`python AND opa` under OPA_ENFORCE, but a site that awaits it as a bare statement throws that answer away, so enforce
changes nothing there (the census, 2026-11-15). This gate reads every call to shadow_check in the registry's source:
  - a call's rule is a string literal (a rule a reader cannot name is not a rule anyone can review)
  - a call that discards its answer is listed in tests/opa_gate/exceptions.json with its reason, and every listed site
    still discards (a wired site leaves the manifest in the same change): a NEW discarding site fails here until it uses
    the answer or is listed
  - the sites that use the answer are exactly the three access checks today
  - OPA is queried directly only by opa_shadow.py and the admin routes (routers/admin_opa.py)
NOTHING ENFORCES ANYTHING NEW (step 1 is pure code): OPA_ENFORCE stays off by default and every site behaves as before;
the pins below fail if either moves. The gate's own files are on the forbidden list (catch B), so no governed change can
edit its guard or list itself as an exception.
RED on 480e1e216: tests/opa_gate/exceptions.json does not exist.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
MANIFEST = Path(__file__).resolve().parent / "opa_gate" / "exceptions.json"
ACCESS_CHECKS = {("security.py", "agentvault/developer/allow"), ("security.py", "agentvault/admin/allow"),
                 ("security.py", "agentvault/agent/allow")}
DIRECT_QUERY_ALLOWED = {"opa_shadow.py", "routers/admin_opa.py"}


def decision_sites(text: str, rel: str):
    """[(rel, rule or None, discarded, line)] for every shadow_check call in TEXT."""
    tree = ast.parse(text)
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
        if name != "shadow_check":
            continue
        arg = node.args[0] if node.args else next((k.value for k in node.keywords if k.arg == "policy_path"), None)
        rule = arg.value if isinstance(arg, ast.Constant) and isinstance(arg.value, str) else None
        up = parents.get(node)
        if isinstance(up, ast.Await):
            up = parents.get(up)
        out.append((rel, rule, isinstance(up, ast.Expr), node.lineno))
    return out


def _all_sites():
    sites = []
    for f in sorted(SRC.rglob("*.py")):
        rel = f.relative_to(SRC).as_posix()
        if rel.startswith(("tests/", "api_tests/")) or "/tests/" in rel:
            continue
        text = f.read_text(encoding="utf-8")
        if "shadow_check" in text:
            sites += [s for s in decision_sites(text, rel) if rel != "opa_shadow.py" or s[1] is not None]
    return sites


def _manifest():
    doc = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert doc["schema"] == "theprotocol.opa-decision-exceptions/1"
    return doc


# --- the detector, proved on code whose answer is known -------------------------------------------------------------

def test_the_detector_tells_a_discarded_answer_from_a_used_one():
    code = '''
async def a():
    await shadow_check("r/discard", {}, True, "l")
async def b():
    await opa.shadow_check("r/attr", {}, True, "l")
async def c():
    ok = await shadow_check("r/assign", {}, True, "l")
async def d():
    if not await shadow_check("r/if", {}, True, "l"):
        raise X
async def e():
    return await shadow_check("r/return", {}, True, "l")
async def f(p):
    await shadow_check(p, {}, True, "l")
'''
    got = {(rule, disc) for _rel, rule, disc, _ln in decision_sites(code, "x.py")}
    assert got == {("r/discard", True), ("r/attr", True), ("r/assign", False), ("r/if", False), ("r/return", False),
                   (None, True)}


# --- the gate ---------------------------------------------------------------------------------------------------------

def test_every_decision_names_its_rule_as_a_literal():
    unnamed = [s for s in _all_sites() if s[1] is None]
    assert not unnamed, f"a shadow_check whose rule is not a string literal: {unnamed}"


def test_every_discarding_site_is_listed_and_every_listed_site_still_discards():
    discarding = {(rel, rule) for rel, rule, disc, _ln in _all_sites() if disc}
    listed = {(s["file"], s["rule"]) for s in _manifest()["sites"]}
    new = discarding - listed
    assert not new, (f"a decision site throws OPA's answer away and is not in {MANIFEST.name}: {sorted(new)}. Use the "
                     "answer (it binds under OPA_ENFORCE), or list the site with its reason")
    wired = listed - discarding
    assert not wired, f"listed but no longer discarding (wired or gone): take it out of {MANIFEST.name}: {sorted(wired)}"


def test_each_listed_site_says_why():
    for s in _manifest()["sites"]:
        assert s.get("reason", "").strip(), s
        assert s["rule"].startswith("agentvault/invariants/"), s


def test_opa_is_queried_directly_only_by_the_shadow_module_and_the_admin_routes():
    users = set()
    for f in SRC.rglob("*.py"):
        rel = f.relative_to(SRC).as_posix()
        if rel.startswith("tests/") or "/tests/" in rel or rel == "opa_client.py":
            continue
        if "query_opa(" in f.read_text(encoding="utf-8"):
            users.add(rel)
    assert users <= DIRECT_QUERY_ALLOWED, f"a direct OPA query outside the shadow module: {sorted(users - DIRECT_QUERY_ALLOWED)}"


# --- nothing enforces anything new -------------------------------------------------------------------------------------

def test_the_sites_that_use_the_answer_are_exactly_the_three_access_checks():
    using = {(rel, rule) for rel, rule, disc, _ln in _all_sites() if not disc}
    assert using == ACCESS_CHECKS, f"the sites that bind under OPA_ENFORCE moved: {sorted(using ^ ACCESS_CHECKS)}"


def test_the_manifest_holds_the_nine_sites_of_the_census():
    assert len(_manifest()["sites"]) == 9


def test_opa_enforce_stays_off_unless_set(monkeypatch):
    from agentvault_registry import opa_shadow
    monkeypatch.delenv("OPA_ENFORCE", raising=False)
    monkeypatch.setenv("OPA_ENABLED", "true")
    assert opa_shadow.opa_enforce() is False
