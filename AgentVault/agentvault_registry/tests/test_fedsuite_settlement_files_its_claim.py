"""V0657 (a) item 2 moved a dispute's compensation to the complainant's explicit claim, made when filing
(`amount_claimed` on POST /disputes/); an amount named in evidence is no longer read (crud_disputes.process_compensation).
The federation suite's two cross-frame settlement legs still named their amount only in evidence, so on V0657 the origin
ruled with "not applied (0 AVT)", no settlement started, and both legs went red at the_origin_rules_for_the_complainant
(V0657's pair proof, 2026-11-07, room seq 1929).

The rule pinned here, on the AST of every federation-suite test: a test that calls `submitDispute` and later asks the
ruling for a settlement (`pending_remote_slash`) files its claim with `amount_claimed` in that same call.
"""
import ast
import pathlib

import agentvault_registry.api_tests.federation_suite.tests as _suite_tests

# the package as the image installs it (a path from this file breaks where the tests are mounted beside the source)
SUITE = pathlib.Path(_suite_tests.__file__).resolve().parent


def _submit_dispute_dicts(tree):
    """Every dict literal passed as the arguments of a `_call(rig, <frame>, "submitDispute", {...})`."""
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or len(node.args) < 4:
            continue
        name = node.args[2]
        if isinstance(name, ast.Constant) and name.value == "submitDispute" and isinstance(node.args[3], ast.Dict):
            out.append(node.args[3])
    return out


def _keys(d):
    return {k.value for k in d.keys if isinstance(k, ast.Constant)}


def _settlement_tests():
    found = []
    for path in sorted(SUITE.glob("test_*.py")):
        text = path.read_text()
        if "pending_remote_slash" not in text:
            continue
        calls = _submit_dispute_dicts(ast.parse(text))
        if calls:
            found.append((path.name, calls))
    return found


def test_the_population_is_not_empty():
    # the two cross-frame settlement legs; an empty population would make the rule below pass on nothing
    names = {n for n, _ in _settlement_tests()}
    assert {"test_cross_registry_settlement_approve.py", "test_cross_registry_settlement_reject.py"} <= names, names


def test_a_settlement_leg_files_its_claim():
    missing = [f"{name}: submitDispute without amount_claimed"
               for name, calls in _settlement_tests() for d in calls if "amount_claimed" not in _keys(d)]
    assert not missing, missing


def test_the_rule_sees_a_leg_without_its_claim():
    # control: the same check over a call shaped like the legs' before V0657 must report it
    tree = ast.parse('async def f():\n    await _call(rig, _A, "submitDispute", '
                     '{"agent_jwt": j, "defendant_did": d, "description": "x"})\n')
    (d,) = _submit_dispute_dicts(tree)
    assert "amount_claimed" not in _keys(d)
