"""§MONEY-R51 (2026-09-04, his word "widen the rule") — ONE path-anchored rule for which trusted SPIFFE
identities are internal callers of the TEG.

The old rule was three substrings ("/service/registry-", "/service/teg-", "/operator/") copied into
five files. A frame the frame provisioner stands up names its registry `/service/registry` and its
svid-writer identity `/service/<name>-registry`, so once TEG_MTLS_REQUIRED=true its own registry was
refused by its own TEG and by every peer's cross-TEG router: no operator could be treasury-seeded.

The predicate is executed out of internal_auth.py's AST (the module imports fastapi + cryptography).
RED control: `R51_SRC_DIR=<dir holding the PRE-FIX teg_core_service tree>` turns every test red.
"""
from __future__ import annotations

import ast
import os
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
SRC = pathlib.Path(os.environ.get("R51_SRC_DIR", HERE.parent / "src" / "teg_core_service"))
INTERNAL_AUTH = SRC / "core" / "internal_auth.py"
SITES = [
    SRC / "core" / "internal_auth.py",
    SRC / "api" / "cross_teg_router.py",
    SRC / "api" / "v1" / "endpoints_tokenomics.py",
    SRC / "api" / "v1" / "endpoints_reputation_signal.py",
    SRC / "api" / "v1" / "endpoints_tokenomics_enhanced.py",
]

TD_A = "spiffe://agentvault.com"
TD_S = "spiffe://sandbox-a.theprotocol.cloud"
# registry-a's SPIRE server, read-only, 2026-09-04 (every /service/ entry except the event store)
PROD_IDS = [f"{TD_A}/service/{n}" for n in (
    "registry-a", "registry-b", "registry-test", "registry-test-b",
    "teg-a", "teg-core-a", "teg-core-b", "teg-core-test-a", "teg-core-test-b",
)] + ["spiffe://frame-b.theprotocol.cloud/service/registry-frame-b", "spiffe://frame-b.theprotocol.cloud/service/teg-layer-frame-b"]
# what the frame provisioner mints (frame_test_provisioner.register_test_frame_spire_entries)
FRESH_FRAME_IDS = [f"{TD_S}/service/teg-layer", f"{TD_S}/service/registry", f"{TD_S}/service/sbx-alpha-registry"]
OPERATOR_IDS = [f"{TD_S}/operator/sbxalphaop/teg", f"{TD_S}/operator/sbxalphaop/registry",
                f"{TD_S}/operator/sbxalphaop/svid-writer", f"{TD_A}/operator/op-berlin/svid-writer", f"{TD_A}/operator/x"]
NOT_SERVICES = [f"{TD_A}/service/event-store", f"{TD_S}/agent/did-theprotocol-04e166c0-1c0d-77ef-ae00",
                f"{TD_S}/spire/agent/x509pop/4605f28668400214f85bba13ba375b226f907007", f"{TD_A}/spire/server"]


def _old_rule(spiffe_id: str) -> bool:
    """The rule every one of the five sites carried before R51 (substring, anywhere)."""
    return "/service/teg-" in spiffe_id or "/service/registry-" in spiffe_id or "/operator/" in spiffe_id


def _predicate():
    tree = ast.parse(INTERNAL_AUTH.read_text(encoding="utf-8"))
    ns: dict = {"Optional": object}
    picked = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_SERVICE_PREFIXES" for t in node.targets):
            picked.append(node)
        if isinstance(node, ast.FunctionDef) and node.name == "is_internal_service_identity":
            picked.append(node)
    exec(compile(ast.Module(body=picked, type_ignores=[]), str(INTERNAL_AUTH), "exec"), ns)
    return ns["is_internal_service_identity"]


def test_every_prod_identity_is_still_accepted():
    ok = _predicate()
    rejected = [i for i in PROD_IDS if not ok(i)]
    assert rejected == [], rejected


def test_a_provisioned_frames_identities_are_accepted():
    """The R51 defect: /service/registry and /service/<name>-registry were refused."""
    ok = _predicate()
    rejected = [i for i in FRESH_FRAME_IDS if not ok(i)]
    assert rejected == [], rejected


def test_cloud_operator_identities_are_accepted():
    ok = _predicate()
    rejected = [i for i in OPERATOR_IDS if not ok(i)]
    assert rejected == [], rejected


def test_non_service_identities_are_rejected():
    ok = _predicate()
    accepted = [i for i in NOT_SERVICES if ok(i)]
    assert accepted == [], accepted


def test_the_rule_is_anchored_not_a_substring():
    ok = _predicate()
    accepted = [i for i in (
        f"{TD_A}/x/service/teg-a",          # the class word appears, but not as the first segment
        f"{TD_A}/service/-registry",        # an empty name before the suffix
        f"{TD_A}/service/registryx", f"{TD_A}/service/tegx", f"{TD_A}/service/x-registryx",
        f"{TD_A}/service/", f"{TD_A}/service", f"{TD_A}/operator/", f"{TD_A}/operator", TD_A, f"{TD_A}/",
    ) if ok(i)]
    assert accepted == [], accepted


def test_rejects_none_empty_and_non_spiffe_schemes():
    ok = _predicate()
    assert not ok(None) and not ok("") and not ok("http://agentvault.com/service/teg-a")
    assert not ok("/service/teg-a") and not ok("spiffe:///service/teg-a")


def test_new_rule_is_a_superset_of_the_old_one_on_every_minted_shape():
    """Nothing that authenticated before R51 stops authenticating: the old substring rule and the
    new anchored rule agree on every prod and operator identity, and the new one adds exactly the
    provisioned-frame shapes the old one refused."""
    ok = _predicate()
    for i in PROD_IDS + OPERATOR_IDS:
        assert _old_rule(i) and ok(i), i
    newly = [i for i in FRESH_FRAME_IDS if ok(i) and not _old_rule(i)]
    assert newly == [f"{TD_S}/service/registry", f"{TD_S}/service/sbx-alpha-registry"], newly


def test_all_five_sites_ask_the_one_predicate_and_the_old_question_is_gone():
    """§FANOUTFIX rule: a widening that adds a predicate must reach every site still asking the old
    question. The three endpoint files import the rule INSIDE a try/except that falls through to the
    admin key, so a misspelt import there would disable mTLS acceptance silently — hence the names
    they import are checked against internal_auth's definitions."""
    defs = {n.name for n in ast.parse(INTERNAL_AUTH.read_text(encoding="utf-8")).body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "is_internal_service_identity" in defs
    for site in SITES:
        src = site.read_text(encoding="utf-8")
        assert "_ACCEPTED_SPIFFE_CLASSES" not in src, site.name
        assert '"/service/teg-" in' not in src and '"/service/registry-" in' not in src, site.name
        assert "is_internal_service_identity(" in src, site.name
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("internal_auth"):
                missing = [a.name for a in node.names if a.name not in defs and not a.name.startswith("_")]
                assert missing == [], (site.name, missing)
