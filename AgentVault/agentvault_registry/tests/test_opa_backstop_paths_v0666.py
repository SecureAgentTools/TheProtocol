"""V0666 OPA phase 2 step 1, close R1 (gwo_fb0b8c005e61af124e579601; his "ok. approved.", room seq 4948, of
sessionlogs2026/DESIGN_2026-11-15_OPA_BACKSTOP.md sections 3, 8, 9 and 10).

The backstop's files are forbidden to every governed change and every code distribution line by an explicit rule, not
by the narrow default open set (a default is not a gate: CODE_CHANGE_OPEN_PATHS can widen it). Forbidden whatever the open
set says:
  - the Rego policies: identity-fabric/ and every .rego file
  - the code that asks OPA and keeps its answer: opa_shadow.py, opa_client.py, security.py, middleware/, core/*_gate.py
  - the simulator whose replay is a policy change's proof: routers/admin_opa.py
  - the guard itself (catch B, section 10): services/code_changes.py (this list), services/code_change_checker.py,
    services/code_distributions.py, routers/code_changes.py, routers/code_distributions.py, the AST gate's test, its
    exceptions manifest, and this test
A change naming one is refused with its sentence; a checker record that touches one is refused; a distribution line cannot
open one. Who changes them: the platform maintainer, on an approval card, never a vote.
RED on 480e1e216: _FORBIDDEN names secrets, keys and build files only.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentvault_registry.services import code_changes as cc

# Layout-independent: the registry root holds tests/ and src/ both where the repository keeps them (agentvault_registry/) and where CI
# stages them (/w/tests, /w/src), so it is parents[1] in both. The repository root is its parent only in the first layout; in CI's it is
# the staging directory itself (never "/": a census that globs "/" passes by accident).
REGISTRY_ROOT = Path(__file__).resolve().parents[1]
SRC = REGISTRY_ROOT / "src" / "agentvault_registry"
REPO_ROOT = REGISTRY_ROOT.parent if REGISTRY_ROOT.name == "agentvault_registry" else REGISTRY_ROOT


def repo_path(f: Path) -> str:
    """A file of the registry as the repository names it: agentvault_registry/<path under the registry root>."""
    return "agentvault_registry/" + f.relative_to(REGISTRY_ROOT).as_posix()

P = "agentvault_registry/src/agentvault_registry/"

BACKSTOP = [
    "identity-fabric/policies/agentvault_admin.rego",
    "identity-fabric/opa/config.yaml",
    "scripts/distribution/nginx-templates/opa/policies/agentvault_invariants.rego",
    P + "opa_shadow.py",
    P + "opa_client.py",
    P + "security.py",
    P + "middleware/readonly_mode.py",
    P + "middleware/a_new_middleware.py",
    P + "core/staking_gate.py",
    P + "core/a_new_gate.py",
    P + "routers/admin_opa.py",
    P + "verifier/runner.py",
    P + "verifier/policies/agentvault_verifier.rego",
    P + "verifier/opa_verifier_alerts.yml",
    "agentvault_registry/tests/test_opa_verifier_v0666.py",
    "agentvault_registry/tests/test_opa_verifier_rego_v0666.py",
    "agentvault_registry/tests/test_opa_verifier_db_v0666.py",
    "agentvault_registry/tests/_opa_verifier_facts.py",
    P + "services/code_changes.py",
    P + "services/code_change_checker.py",
    P + "services/code_distributions.py",
    P + "routers/code_changes.py",
    P + "routers/code_distributions.py",
    "agentvault_registry/tests/test_opa_decision_gate_v0666.py",
    "agentvault_registry/tests/opa_gate/exceptions.json",
    "agentvault_registry/tests/test_opa_backstop_paths_v0666.py",
]


@pytest.mark.parametrize("path", BACKSTOP)
def test_each_backstop_file_is_forbidden(path):
    assert cc.is_forbidden(path), path
    assert cc.is_backstop(path), path


@pytest.mark.parametrize("path", [P + "static/new_registry_frontend/src/views/CodeChanges.vue",
                                  P + "static/new_registry_frontend/src/assets/docs/oracle/06_governance.md",
                                  P + "routers/exchange.py", P + "core/registry_identity.py",
                                  P + "static/new_registry_frontend/src/services/securityHeaders.ts"])
def test_what_is_not_the_backstop_stays_as_it_was(path):
    assert not cc.is_backstop(path), path


def test_every_policy_and_gate_file_on_disk_is_forbidden():
    assert REPO_ROOT != Path("/")
    regos = [p for p in REPO_ROOT.rglob("*.rego") if "node_modules" not in p.parts]
    gates = list((SRC / "core").glob("*_gate.py"))
    mids = [p for p in (SRC / "middleware").glob("*.py")]
    assert gates and mids
    for f in regos:
        assert cc.is_forbidden(f.relative_to(REPO_ROOT).as_posix()), f
    for f in gates + mids:
        assert cc.is_forbidden(repo_path(f)), f


def test_every_verifier_file_and_test_on_disk_is_forbidden():
    files = [p for p in (SRC / "verifier").rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    files += list((REGISTRY_ROOT / "tests").glob("test_opa_verifier*.py"))
    files += [REGISTRY_ROOT / "tests" / "_opa_verifier_facts.py"]
    assert len(files) >= 12 and any(f.suffix == ".rego" for f in files) and any(f.name.startswith("test_opa_verifier") for f in files)
    for f in files:
        rel = repo_path(f)
        assert cc.is_forbidden(rel) and cc.is_backstop(rel), rel


def test_a_change_naming_one_is_refused_with_its_sentence_however_wide_the_open_set(monkeypatch):
    monkeypatch.setenv("CODE_CHANGE_OPEN_PATHS", json.dumps({cc.REPOSITORY: ["agentvault_registry/", "identity-fabric/"]}))
    for path in BACKSTOP:
        pc = cc.check_paths(cc.REPOSITORY, [path])
        assert not pc.ok, path
        assert pc.reason == (f"a forbidden path: {path} (the policy backstop: OPA's policies, the code that asks them and "
                             f"this rail's own guard change only on the platform maintainer's approval card, never by a vote)")
    # a widened open set still opens what is not the backstop
    assert cc.check_paths(cc.REPOSITORY, [P + "routers/exchange.py"]).ok


def test_the_old_forbidden_sentence_stays_for_secrets_keys_and_build_files():
    pc = cc.check_paths(cc.REPOSITORY, [cc.CONSOLE_PREFIX + "package.json"])
    assert not pc.ok and pc.reason.endswith("(secrets, keys, build and dependency files are never voted on)")


def test_a_checker_record_that_touches_one_is_refused(monkeypatch):
    monkeypatch.setenv("CODE_CHANGE_OPEN_PATHS", json.dumps({cc.REPOSITORY: ["agentvault_registry/"]}))
    record = {"commit": "0" * 40, "ci": {"status": "success"}, "touched": [P + "security.py"], "secret_findings": 0}
    ok, reasons = cc.acceptance_verdict(cc.REPOSITORY, record, [P + "security.py"])
    assert not ok and reasons == [f"{P}security.py is a forbidden path"]
    record["touched"] = [P + "routers/exchange.py"]                  # the control: a widened set accepts the rest
    assert cc.acceptance_verdict(cc.REPOSITORY, record, [P + "routers/exchange.py"]) == (True, [])


def test_a_distribution_line_cannot_open_one_nor_merge_a_change_to_one(monkeypatch):
    from agentvault_registry.services import code_distributions as cd
    monkeypatch.setenv("CODE_CHANGE_OPEN_PATHS", json.dumps({cc.REPOSITORY: ["agentvault_registry/"]}))
    with pytest.raises(cc.CodeChangeRefusal) as e:
        cd.check_open_paths([P + "middleware/"])
    assert e.value.code == "open_paths" and "policy backstop" in e.value.sentence
    line = {"open_paths": ["agentvault_registry/"]}
    assert "policy backstop" in (cd.paths_inside_line([P + "opa_client.py"], line) or "")
    assert cd.paths_inside_line([P + "routers/exchange.py"], line) is None      # the control
