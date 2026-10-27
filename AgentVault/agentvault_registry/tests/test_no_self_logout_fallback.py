"""A DESTRUCTIVE CALL MUST NOT RETARGET ITSELF AT THE LOAD-BEARING ACCOUNT.

§RUNNERCRED-4 2026-09-07, measured end to end on sbx-alpha:

    14:45:20  non-admin developer JWT mint failed: 401 "Incorrect email or password"
    14:46:15  Logout revoked all sessions for developer 2   (admin@test.sandbox)
    token_version 67 → 68 across ONE flagship run, exactly one revocation

`lifecycle_auth_register_logout` means to exercise `logoutSession` against a SPARE
non-admin session. Its selector was:

    logout_jwt = getattr(bag, "developer_jwt_nonadmin", None) or bag.developer_jwt

so when the spare session failed to mint — an empty string, which is falsy — it fell
through to the ADMIN token and the sweep revoked its own load-bearing credential,
once per run. The protection inverted exactly when it was needed. Every lifecycle
holding a snapshot of that JWT then 401'd, and those rows were recorded healthy
under `expect_status="any"`.

It ran at all because the docstring asserted "POST /auth/logout is a STATELESS no-op
… does NOT revoke the JWT", which is false of `auth_secure.py:logout` — that handler
bumps `token_version` and its own docstring says this invalidates every live token
for the developer. A stale comment was the licence for the risky call.

This gate pins BOTH halves: no `or bag.developer_jwt` fallback on the logout path,
and the docstring may not claim logout is a no-op.
"""
from __future__ import annotations

import re
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
_LIFECYCLES = _SRC / "api_tests" / "contracts" / "mcp_lifecycles.py"
_AUTH = _SRC / "routers" / "auth_secure.py"


def _logout_lifecycle_body() -> str:
    """The function whose `_exec_step` CALLS logoutSession, found by the call — not by name.

    The first version of this gate hard-coded `lifecycle_auth_register_logout` and
    failed on a name that does not exist. A gate that assumes where the code lives
    measures its own assumption; locate the call and walk back to its function.
    §MCPTEST30 (2026-09-30): by the AST, not the first string occurrence — the tool name now also sits in a
    module-level tuple (SELF_ACCOUNT_TOOLS) above the lifecycle that calls it.
    """
    import ast
    src = _LIFECYCLES.read_text()
    tree = ast.parse(src)
    for fn in tree.body:
        if not isinstance(fn, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "_exec_step"
                    and len(node.args) >= 3 and isinstance(node.args[2], ast.Constant)
                    and node.args[2].value == "theprotocol_logoutSession"):
                return ast.get_source_segment(src, fn)
    raise AssertionError("no lifecycle calls logoutSession through _exec_step: the gate cannot see the call")


def test_logout_never_falls_back_to_the_admin_token() -> None:
    body = _logout_lifecycle_body()
    assert "or bag.developer_jwt" not in body, (
        "the logout step can still fall back to the admin JWT — that is how the "
        "sweep revoked its own credential once per run (developer 2, token_version "
        "67→68). No spare session must mean NO CALL, not a call on the admin")
    # §MCPTEST30: the spare session is now the run's own throwaway subject (bag.self_subject), never the
    # auth-matrix principal (logging THAT out in phase 4 would leave phase 5b probing with a revoked token)
    assert 'getattr(bag, "self_subject", None)' in body, (
        "the spare-session selector changed shape; re-read it and re-point this gate")
    assert "bag.developer_jwt_nonadmin" not in body and "bag.admin_jwt" not in body, (
        "the logout lifecycle reaches for a credential another phase depends on")


def test_the_docstring_no_longer_calls_logout_a_no_op() -> None:
    body = _logout_lifecycle_body()
    low = body.lower()
    assert "stateless no-op" not in low or "corrected" in low, (
        "the docstring still asserts logout is a stateless no-op without marking the "
        "correction — that claim is what authorised the call")
    assert "revokes" in low or "revoked" in low, (
        "the docstring must say logout REVOKES sessions; a reader who believes "
        "otherwise will reinstate the fallback")


def test_the_endpoint_really_does_revoke() -> None:
    """The control: if logout ever becomes a true no-op, this gate is obsolete.

    It reads the ROUTE, so the day someone makes logout stateless the test fails and
    the comment above gets revisited instead of quietly rotting the other way.
    """
    auth = _AUTH.read_text()
    i = auth.index("async def logout(")
    seg = auth[i:i + 2500]
    assert re.search(r"token_version\s*=\s*models\.Developer\.token_version\s*\+\s*1", seg), (
        "POST /auth/logout no longer bumps token_version — logout may have become "
        "the no-op the old docstring claimed. Re-measure before relaxing anything")
