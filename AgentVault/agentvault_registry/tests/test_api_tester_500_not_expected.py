"""§MCPTEST30 V0644 (agentvault2-66, 2026-10-26): the API tester reads a 500 as a failure, not as an expected one.

His rule of 2026-10-19: no softened failure class in a view. The API tester's classifiers (routers/admin_api_test.py)
carried 48 rules that marked a 500 as an expected failure. 38 of them were for routes that no longer answer one:
- the pipeline template routes (the download's §pass47 serialization bug is fixed), the pipeline and deployment routes,
  the agent logs, unstake, malpractice, proposals and agent export routes;
- docker stats, the federation dispute settlements and peer slash config, OAuth (its trust list and the rest), the
  staking reward routes and the bridge (where a status list also named a 4xx, the 4xx stays);
- the organization invitation accept ("code bug, not test issue" in its own words): fixed on 2026-07-16, a token that
  matches nothing is a 400 "Invalid or expired invitation".
Read-only on the four sandbox registries (2026-10-26 ~06:30-06:45Z): every GET among them answered 200, 404 for an
unknown id, or an honest 503 (docker stats on an operator: no docker socket), and the invitation accept with a token
that matches nothing 400 on both frames; none answered 500 (sbx-alpha's 7 templates downloaded; export, logs,
deployments for three agents per frame). A 500 there now reads as failed, and the download's contract
(api_tests/contracts/cicd.py) no longer lists 500 as expected.

Pinned on the source (the classifiers sit inside the tester's request handler): no rule that marks a 500 as expected
names one of those routes, and the rest of the class (10 rules) may only shrink (CEILING). The census reads every form
the file writes a status in (status_code, response.status_code, _sc, _sc_cm) and proves itself on a synthetic source.
RED on c7531675's admin_api_test.py (48 such rules, 38 naming those routes) and cicd.py (500 expected, a known_bug).
"""
import ast
from pathlib import Path

from agentvault_registry.api_tests.contracts import cicd

ROUTER = Path(__file__).resolve().parents[1] / "src" / "agentvault_registry" / "routers" / "admin_api_test.py"
STATUS = {"status_code", "_sc", "_sc_cm", "statusCode"}
EXPECTED = {"is_expected_failure", "_ef", "_ef_cm", "expected_failure"}
FIXED = ("/pipeline-templates", "/deployments", "/agents/{agent_did}/pipelines", "/agents/{agent_did}/logs",
         "/staking/unstake", "/contracts/malpractice", "/governance/proposals", "/agents/{agent_did}/export",
         "/admin/docker-stats", "/federation/disputes/settlements", "/federation/disputes/peer-slash-config", "/oauth/",
         "/staking/rewards/", "/bridge/", "/organizations/invitations/{token}/accept")
# the rules left that read a 500 as expected: the simulation console (4; its reads answered 200 or 503, its writes are
# not measured), the cross-TEG treasury fund (3) and the TEG lock (3), which move or hold value; each is measured on
# its own before its rule goes; this number may only go down
CEILING = 10


def _is_status(node):
    if isinstance(node, ast.Name):
        return node.id in STATUS
    if isinstance(node, ast.Attribute):
        return node.attr in STATUS
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get":
        return bool(node.args) and isinstance(node.args[0], ast.Constant) and node.args[0].value in STATUS
    if isinstance(node, ast.Subscript):
        return isinstance(node.slice, ast.Constant) and node.slice.value in STATUS
    return False


def _names_500(test):
    for n in ast.walk(test):
        if isinstance(n, ast.Compare) and _is_status(n.left):
            for op, c in zip(n.ops, n.comparators):
                if isinstance(op, ast.Eq) and isinstance(c, ast.Constant) and c.value == 500:
                    return True
                if isinstance(op, ast.In) and isinstance(c, (ast.List, ast.Tuple, ast.Set)) and any(
                        isinstance(e, ast.Constant) and e.value == 500 for e in c.elts):
                    return True
    return False


def _marks_expected(body):
    for st in body:
        for n in ast.walk(st):
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    names = [t.id] if isinstance(t, ast.Name) else [e.id for e in getattr(t, "elts", [])
                                                                    if isinstance(e, ast.Name)]
                    if isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant):
                        names.append(t.slice.value)
                    first = n.value.elts[0] if isinstance(n.value, ast.Tuple) else n.value
                    if set(names) & EXPECTED and isinstance(first, ast.Constant) and first.value is True:
                        return True
    return False


def expected_500_rules(source):
    tree = ast.parse(source)
    return sorted((n.lineno, ast.get_source_segment(source, n.test)) for n in ast.walk(tree)
                  if isinstance(n, ast.If) and _names_500(n.test) and _marks_expected(n.body))


def test_no_rule_reads_a_500_from_the_fixed_routes_as_expected():
    rules = expected_500_rules(ROUTER.read_text())
    named = [(line, test) for line, test in rules if any(route in test for route in FIXED)]
    assert named == [], f"a 500 from these routes is a failure: {named}"


def test_the_rest_of_the_class_only_shrinks():
    rules = expected_500_rules(ROUTER.read_text())
    assert len(rules) <= CEILING, f"{len(rules)} rules read a 500 as expected (ceiling {CEILING}): {rules}"


def test_the_census_sees_a_rule_of_each_shape():
    # control: the census must find every form it is looking for, or its zero above means nothing
    source = '''
if status_code == 500 and "/pipeline-templates" in original_path:
    is_expected_failure = True
elif _sc in [404, 500] and original_path == "/deployments":
    _ef, _er = True, "x"
if _sc_cm == 500 and original_path == "/agents/{agent_did}/export":
    _ef_cm, _er_cm = True, "y"
if response.status_code in [400, 500] and "/oauth/" in original_path:
    is_expected_failure = True
if result.get("statusCode") == 500:
    result["expected_failure"] = True
if status_code == 500:
    is_expected_failure = False
if status_code == 404:
    is_expected_failure = True
'''
    assert [line for line, _ in expected_500_rules(source)] == [2, 4, 6, 8, 10]


def test_the_template_download_contract_expects_no_500():
    contract = cicd.DownloadPipelineTemplate
    statuses = contract.expected_status if isinstance(contract.expected_status, list) else [contract.expected_status]
    assert 500 not in statuses
    assert not any(getattr(f, "bug_id", None) == "PASS47-PIPELINE-TEMPLATE-DOWNLOAD-500"
                   for f in getattr(contract, "failures", []))
