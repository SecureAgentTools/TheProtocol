"""§MCPTEST30 (V0639): an operator run has the account the self-account lifecycle acts on.

lifecycle_self_account_on_throwaway runs 2FA, password change, logout and deletion on `bag.self_subject`, an account the
sweep owns, never on the runner; without one every such tool is NOT MEASURED. The frame's bootstrap mints it
(_bootstrap_fixtures); the operator sweep built its bag without one, so on both sandbox operators authValidate2FA,
authRecover2FA and verify2FA passed on a refusal alone in the wide list (2026-10-24 13:39-13:46Z). Pinned: the operator
sweep mints one through _mint_throwaway_developer with the operator's own invite when its bag has none, and the wide
operator list takes the lifecycle.
"""
from __future__ import annotations

import ast
import inspect

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle import test_flow_mcp_lifecycle as F


def _sweep():
    return ast.parse("class X:\n" + inspect.getsource(F.TestFlowMcpLifecycle._run_cloudop_mcp_sweep))


def test_the_operator_sweep_mints_the_self_subject_with_its_invite():
    sets = [n for n in ast.walk(_sweep()) if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Attribute) and t.attr == "self_subject" for t in n.targets)]
    assert len(sets) == 1
    call = sets[0].value.value if isinstance(sets[0].value, ast.Await) else None
    assert isinstance(call, ast.Call) and getattr(call.func, "id", "") == "_mint_throwaway_developer"
    assert ast.unparse(call.args[1]) == "'self'"
    assert any(k.arg == "invite" and ast.unparse(k.value) == "_cop_invite" for k in call.keywords)


def test_the_wide_operator_list_takes_the_self_account_lifecycle():
    names = {lc["name"] for lc in F.cloudop_lifecycle_list()}
    assert "self_account_on_throwaway" in names
