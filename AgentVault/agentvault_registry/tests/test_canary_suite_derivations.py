"""§CANARYONBOARD (2026-09-23): the federation suite's canary tests derive the tier's topology instead of pinning it.

Three of them pinned the LEGACY sandbox numbers and names: `active_paths >= 10`, `active_paths >= 11`, and the two path
ids `sb-alpha->sb-delta:async` / `sb-delta->sb-alpha:async`. The clusters' sandbox frames carry 4 paths each by design
and their operators 3, so the day canaries were provisioned there the three went red about a correct topology — a gate
pinning a literal it could derive (the §FRAMELIC rule).

`active == total` is not the replacement either: a RETIRED row is legitimate. Measured 2026-09-23, EU carries 7 paths
of which 5 are active, the other two being its standup canaries, deliberately off since the day before. What is always
true is that a path which FIRED inside the window should still be armed.
"""
import ast
import inspect

from agentvault_registry.api_tests.federation_suite.rig import (
    canary_path_leaves_registry,
    canary_paths_fired_but_inactive,
)


def _code(module) -> str:
    """The module's code with every docstring removed.

    ⚠ A source-reading gate finds its own documentation first (CLAUDE.md PART 1): the first version of this test
    refused a correct module, because the docstring explaining the removal of `sb-alpha->sb-delta:async` contains that
    id. Prose beside a fix names the class; only the code says what runs.
    """
    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and body \
                and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            node.body = body[1:] or [ast.Pass()]
    return ast.unparse(ast.fix_missing_locations(tree))


def test_a_path_that_stays_on_this_registry_is_not_a_cross_path():
    assert canary_path_leaves_registry({"frame_pair": "sbx-alpha->sbx-alpha", "backend": "intra"}) is False
    assert canary_path_leaves_registry({"backend": "intra"}) is False          # no pair: the backend answers


def test_a_path_whose_far_end_is_another_registry_is_a_cross_path():
    assert canary_path_leaves_registry({"frame_pair": "sbx-alpha->sbxalphaop", "backend": "2pc"}) is True
    assert canary_path_leaves_registry({"frame_pair": "sandbox-A->sandboxdelta", "backend": "async"}) is True
    assert canary_path_leaves_registry({"backend": "2pc"}) is True             # no pair: the backend answers


def test_a_live_canary_switched_off_is_named_and_a_retired_one_is_not():
    body = {"paths": [
        {"path_id": "fired-then-off", "is_active": False, "stats_24h": {"total": 12, "passed": 12}},
        {"path_id": "retired", "is_active": False, "stats_24h": {"total": 0, "passed": 0}},
        {"path_id": "healthy", "is_active": True, "stats_24h": {"total": 24, "passed": 24}},
    ]}
    assert canary_paths_fired_but_inactive(body) == ["fired-then-off"]
    assert canary_paths_fired_but_inactive({"paths": []}) == []
    assert canary_paths_fired_but_inactive({}) == []


def test_the_three_suite_tests_no_longer_pin_the_legacy_topology():
    from agentvault_registry.api_tests.federation_suite.tests import (
        test_canary_subsystem_observability as obs,
        test_multi_hop_routing as mh,
        test_sandbox_topology_invariants as topo,
    )
    mh_code, obs_code, topo_code = _code(mh), _code(obs), _code(topo)
    assert "sb-alpha->sb-delta:async" not in mh_code and "sb-delta->sb-alpha:async" not in mh_code
    assert "canary_path_leaves_registry(" in mh_code
    assert "active_paths'] >= 10" not in obs_code and "canary_paths_fired_but_inactive(" in obs_code
    assert "active_paths'] >= 11" not in topo_code and "canary_paths_fired_but_inactive(" in topo_code
