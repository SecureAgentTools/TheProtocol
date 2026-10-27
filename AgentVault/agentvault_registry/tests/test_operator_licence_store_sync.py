"""§F6 stage 5 (2026-09-27): the operator-level revoke, suspend and reinstate carry the licence's new status to the store.

The licence routes always synced their status changes to the store's federation_operators row; the operator-level
cascades in operator_applications.py changed the licence in the registry's database only, so the store kept a revoked
operator's row "active" (sbx-beta, b1opd on V0473). Each now syncs after its commit, best-effort.
"""
import ast
import os
import types

import pytest

from agentvault_registry.routers import operator_applications as oa
from agentvault_registry.routers import federation_licenses as fl

SRC = os.path.join(os.path.dirname(oa.__file__), "operator_applications.py")


@pytest.fixture
def seen(monkeypatch):
    calls = []

    async def fake_sync(**kw):
        calls.append(kw)
        return True

    monkeypatch.setattr(fl, "_sync_license_to_eventstore", fake_sync)
    return calls


def _licence():
    return types.SimpleNamespace(id="lic-1", operator_name="b1opd", license_key_hash="h" * 64)


async def test_a_status_change_reaches_the_store_with_the_licence_it_names(seen):
    await oa._sync_operator_licence_status(_licence(), "revoked")
    assert seen == [{"license_id": "lic-1", "operator_name": "b1opd", "license_key_hash": "h" * 64,
                     "op_status": "revoked"}]


async def test_no_licence_changed_means_no_sync(seen):
    """Control: an operator with no licence (a phantom, or one already revoked) sends nothing."""
    await oa._sync_operator_licence_status(None, "revoked")
    assert seen == []


async def test_a_failing_sync_never_undoes_the_revoke(monkeypatch):
    async def boom(**kw):
        raise RuntimeError("store unreachable")

    monkeypatch.setattr(fl, "_sync_license_to_eventstore", boom)
    await oa._sync_operator_licence_status(_licence(), "suspended")   # must not raise


@pytest.mark.parametrize("route,status", [("revoke_operator_access", "revoked"), ("suspend_operator", "suspended"),
                                          ("reinstate_operator", "active")])
def test_each_route_syncs_its_status_after_its_commit(route, status):
    """Wired on the AST: the route calls the sync with its status, and only after `await db.commit()`."""
    src = open(SRC).read()
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.AsyncFunctionDef) and n.name == route)
    commits = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Await) and isinstance(n.value, ast.Call)
               and ast.unparse(n.value.func) == "db.commit"]
    syncs = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and ast.unparse(n.func) == "_sync_operator_licence_status"]
    assert commits and len(syncs) == 1, (commits, len(syncs))
    call = syncs[0]
    assert isinstance(call.args[1], ast.Constant) and call.args[1].value == status
    assert call.lineno > min(commits), "the sync runs after the licence change is committed"
