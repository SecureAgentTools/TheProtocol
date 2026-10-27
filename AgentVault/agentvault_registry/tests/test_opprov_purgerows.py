"""§OPPROV (2026-09-27, his words "fix operators provisioning"): a purge's step 4.5, the operator's rows elsewhere.

Measured on sbx-alpha (V0469, the socket route): the purge of the throwaway operator opprovs drained, removed the stack
and the edge, deleted this frame's peer row, and logged "cross-frame peer/app/ES rows purged for opprovs", yet sbx-beta
kept its copy (discovered, INACTIVE). On the socket route step 4.5 only ran `_purge_op_rows_all_frames`, psql inside the
databases TEARDOWN_FRAME_REG_DBS names, and that list names this frame's own database alone (one entry: a frame does not
write into another frame's database, rightly). The runner route already asked every ACTIVE peer frame to purge its own
copies through its API (`_purge_op_rows_by_api`, §F6 WP6.2 slice 2); the same call, run from sbx-alpha by hand, deleted
sbx-beta's copy (200, deleted 1). Both routes now run that one rule; the socket route keeps its own-database psql.
RED control: on the pre-fix code `_purge_rows_elsewhere` does not exist.
"""
import asyncio

import pytest

from agentvault_registry.services import cloud_provisioner as cp


@pytest.fixture
def halves(monkeypatch):
    ran = []

    def psql(safe, display):
        ran.append(("psql", safe, display))

    async def by_api(db, safe):
        ran.append(("api", safe))
        return {"peers": {"Sandbox Beta": {"http": 200, "deleted": 1}}, "store_suspended": [], "store_errors": []}

    monkeypatch.setattr(cp, "_purge_op_rows_all_frames", psql)
    monkeypatch.setattr(cp, "_purge_op_rows_by_api", by_api)
    return ran


def test_the_socket_route_cleans_its_own_databases_and_asks_every_peer(halves):
    out = asyncio.run(cp._purge_rows_elsewhere(object(), "opprovs", "opprovs", via_runner=False))
    assert halves == [("psql", "opprovs", "opprovs"), ("api", "opprovs")]
    assert out["route"] == "socket" and out["own_databases"].startswith("purged")
    assert out["peers"]["Sandbox Beta"] == {"http": 200, "deleted": 1}


def test_the_runner_route_asks_every_peer_and_runs_no_psql(halves):
    out = asyncio.run(cp._purge_rows_elsewhere(object(), "opprovs", "opprovs", via_runner=True))
    assert halves == [("api", "opprovs")] and out["route"] == "runner" and "own_databases" not in out


def test_a_failed_own_database_purge_is_reported_and_the_peers_are_still_asked(monkeypatch, halves):
    def broken(safe, display):
        raise RuntimeError("docker did not answer")
    monkeypatch.setattr(cp, "_purge_op_rows_all_frames", broken)
    out = asyncio.run(cp._purge_rows_elsewhere(object(), "opprovs", "opprovs", via_runner=False))
    assert out["own_databases"].startswith("failed: docker did not answer") and halves == [("api", "opprovs")]


def test_the_teardown_runs_step_4_5_through_the_one_rule():
    import ast
    import inspect
    src = inspect.getsource(cp.teardown_cloud_operator)
    calls = {n.func.id for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "_purge_rows_elsewhere" in calls
    assert "_purge_op_rows_by_api" not in calls, "the peers' purge is asked through _purge_rows_elsewhere, for both routes"
    assert "cross-frame peer/app/ES rows purged" not in src, "the log line that claimed a cross-frame purge that never ran"
