"""§MCPTEST30 (V0561, agentvault2-09): the Command Center as EU, ASIA and Sandbox Beta showed it on 2026-10-03.

Their target lists were empty (no Docker socket since F6, or fleet scope off), and the console drew a red 0% ring and
"No active alerts" over the empty list; the targets route now says WHY it is empty. The leader-election check answered
"ok" for every target that was not the retired registry-a: a green tick that measured nothing, now "unknown" (which the
target aggregate treats as neutral, so it costs the aggregate nothing).
"""
import pytest
from fastapi import HTTPException

from agentvault_registry.routers import admin_diagnostics as ad
from agentvault_registry.services.diagnostics import targets as T
from agentvault_registry.services.diagnostics.checks import leader_election


# ── why the list holds no operator, and why container checks cannot run (V0562 split them) ──

def test_an_empty_operator_list_has_one_cause_left():
    assert T.why_no_targets() == ("no_operators", "no operator belongs to this frame: it holds no cloud operator peer row")


def test_scope_off_is_named_first_for_the_container_checks(monkeypatch):
    monkeypatch.setenv("DIAGNOSTICS_FLEET_SCOPE", "local")
    code, sentence = T.why_no_containers()
    assert code == "scope_off" and "DIAGNOSTICS_FLEET_SCOPE is not fleet" in sentence


def test_no_socket_is_named_when_scope_is_on(monkeypatch):
    monkeypatch.setenv("DIAGNOSTICS_FLEET_SCOPE", "fleet")
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.setattr(T.os.path, "exists", lambda p: False if p == "/var/run/docker.sock" else True)
    code, sentence = T.why_no_containers()
    assert code == "no_socket" and "no Docker socket" in sentence


def test_a_socket_and_scope_leave_nothing_to_explain(monkeypatch):
    monkeypatch.setenv("DIAGNOSTICS_FLEET_SCOPE", "fleet")
    monkeypatch.setenv("DOCKER_HOST", "unix:///var/run/docker.sock")
    assert T.why_no_containers() is None


@pytest.mark.asyncio
async def test_the_targets_route_carries_the_reason_only_when_no_operator(monkeypatch):
    monkeypatch.setenv("DIAGNOSTICS_FLEET_SCOPE", "local")

    async def _none(_db):
        return []
    monkeypatch.setattr(ad, "list_targets", _none)
    out = await ad.get_targets(db=None)
    assert out["count"] == 0 and out["reason_code"] == "no_operators" and out["containers_reason_code"] == "scope_off"

    async def _one(_db):
        return [{"operator_id": "op-x", "display_name": "x", "frame": "sandbox alpha", "role": "operator", "containers": {}}]

    async def _no_cache(check_id, target):
        return None
    monkeypatch.setattr(ad, "list_targets", _one)
    monkeypatch.setattr(ad.cache, "get_cached", _no_cache)
    out = await ad.get_targets(db=None)
    assert out["count"] == 1 and out["reason"] is None and out["reason_code"] is None


# ── the leader check that measured nothing ───────────────────────────────────

@pytest.mark.asyncio
async def test_an_operators_leader_keys_are_not_measured_and_say_so(monkeypatch):
    class _Redis:
        async def keys(self, _p):
            raise AssertionError("an operator's leader keys are not in this registry's Redis: nothing may be read")

    async def _redis():
        return _Redis()
    monkeypatch.setattr(leader_election, "get_redis", _redis)
    r = await leader_election.run({"operator_id": "op-sbxalphaop", "role": "operator"}, probe=None)
    assert r.status == "unknown" and r.summary.startswith("not measured")


def test_unknown_is_neutral_in_the_target_aggregate():
    assert ad._aggregate_status(["ok", "unknown"]) == "healthy"
    assert ad._aggregate_status(["unknown"]) == "unknown"
    assert ad._aggregate_status(["ok", "fail", "unknown"]) == "down"


# ── run-all names a target that does not exist ───────────────────────────────

@pytest.mark.asyncio
async def test_run_all_on_an_unknown_target_is_a_404(monkeypatch):
    async def _no(_db, _tid):
        return None
    monkeypatch.setattr(ad, "get_target", _no)

    class _Admin:
        email = "admin@test.sandbox"
    with pytest.raises(HTTPException) as e:
        await ad.run_all(ad.RunAllRequest(target="op-nobody"), current_admin=_Admin(), db=None)
    assert e.value.status_code == 404 and "op-nobody" in e.value.detail
