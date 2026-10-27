"""§F6 stage 5 (2026-09-27): a non-purge teardown carries its licence revoke to the store's federation_operators row.

The teardown revoked the operator's licence in the registry's database only; the operator revoke that follows then found
no licence left to revoke, so its own sync never fired (sbx-beta on V0474: b1ope torn down, revoked, its store row still
"active"). The teardown result now carries the licence it revoked, and the router syncs it after its commit. A purge is
left alone: it suspends or deletes the store rows itself, and a sync after it would write a row back.
"""
import ast
import os

import pytest

from agentvault_registry.services import cloud_provisioner as cp
from agentvault_registry.routers import federation_licenses as fl

HERE = os.path.dirname(cp.__file__)
LIC = {"id": "lic-9", "operator_name": "b1ope", "license_key_hash": "h" * 64}


def _result(licence=LIC):
    return cp.CloudTeardownResult(containers_stopped=True, nginx_removed=True, peer_deactivated=True,
                                  stack_archived=True, revoked_licence=licence)


@pytest.fixture
def seen(monkeypatch):
    calls = []

    async def fake_sync(**kw):
        calls.append(kw)
        return True

    monkeypatch.setattr(fl, "_sync_license_to_eventstore", fake_sync)
    return calls


async def test_a_teardown_carries_its_revoke_to_the_store(seen):
    assert await cp.sync_teardown_licence_to_store(_result(), purge=False) is True
    assert seen == [{"license_id": "lic-9", "operator_name": "b1ope", "license_key_hash": "h" * 64,
                     "op_status": "revoked"}]


async def test_a_purge_is_left_to_its_own_store_step(seen):
    """Control: the purge suspends or deletes the rows itself; a sync after it would write a row back."""
    assert await cp.sync_teardown_licence_to_store(_result(), purge=True) is None
    assert seen == []


async def test_no_licence_revoked_means_no_sync(seen):
    assert await cp.sync_teardown_licence_to_store(_result(None), purge=False) is None
    assert seen == []


async def test_a_failing_sync_is_reported_not_raised(monkeypatch):
    async def boom(**kw):
        raise RuntimeError("store unreachable")

    monkeypatch.setattr(fl, "_sync_license_to_eventstore", boom)
    assert await cp.sync_teardown_licence_to_store(_result(), purge=False) is False


def test_the_teardown_records_the_licence_it_revokes():
    src = open(os.path.join(HERE, "cloud_provisioner.py")).read()
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.AsyncFunctionDef) and n.name == "teardown_cloud_operator")
    body = ast.unparse(fn)
    assert "revoked_licence = {" in body and "revoked_licence=revoked_licence" in body


def test_the_router_syncs_after_its_commit():
    src = open(os.path.join(os.path.dirname(HERE), "routers", "cloud_operators.py")).read()
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.AsyncFunctionDef)
              and "teardown_cloud_operator(" in ast.unparse(n) and "cloud_torn_down_at" in ast.unparse(n))
    commits = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Call) and ast.unparse(n.func) == "db.commit"]
    syncs = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and ast.unparse(n.func) == "sync_teardown_licence_to_store"]
    assert commits and len(syncs) == 1
    assert syncs[0].lineno > min(commits), "the store hears of the revoke only after it is committed here"
    assert ast.unparse(syncs[0].args[1]) == "body.purge"
