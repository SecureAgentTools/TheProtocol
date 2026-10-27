"""§F6 on production (2026-09-30): an operator op goes to the runner's OPERATOR socket on every mount layout.

The runner serves an operator's host work on a second socket and refuses it on the full one. A registry that mounts the
runner's whole directory (EU, sbx-alpha) sees the full socket at /run/theprotocol/frame-runner.sock and the operator
socket in /run/theprotocol/operator/; one that mounts the operator directory alone (the kit template, ASIA, sbx-beta)
sees the operator socket at the top. The provision client and the reachability ping used to dial the top on both, so
EU's operator_ping, provision, status and teardown reached the full socket and were refused.

The modules are imported the normal way, so the build's second run (-o pythonpath=) measures the IMAGE's own code.
"""
import sys
import types

import pytest

from agentvault_registry.core import host_reach as hr
from agentvault_registry.services import frame_runner_client as frc

SUBDIR = "/run/theprotocol/operator/frame-runner.sock"
TOP = "/run/theprotocol/frame-runner.sock"


@pytest.fixture
def layout(monkeypatch):
    """Set the mount layout: whether this registry sees the operator subdirectory's socket, and the two env knobs."""
    def _set(*, subdir_exists, env=None, runner_socket=None):
        for k in ("FRAME_RUNNER_OPERATOR_SOCKET", "FRAME_RUNNER_SOCKET"):
            monkeypatch.delenv(k, raising=False)
        if env:
            monkeypatch.setenv("FRAME_RUNNER_OPERATOR_SOCKET", env)
        if runner_socket:
            monkeypatch.setenv("FRAME_RUNNER_SOCKET", runner_socket)
        real_exists = frc.os.path.exists
        monkeypatch.setattr(frc.os.path, "exists", lambda p: subdir_exists if p == SUBDIR else real_exists(p))
    return _set


def test_the_rule_names_the_subdirectory_the_runner_serves(layout):
    layout(subdir_exists=True)
    assert frc.OPERATOR_SUBDIR_SOCKET == SUBDIR
    assert frc.DEFAULT_SOCKET == TOP


def test_a_whole_directory_mount_sends_operator_ops_to_the_subdirectory(layout):
    layout(subdir_exists=True)
    for op in ("operator_ping", "operator_provision", "operator_status", "operator_teardown", "operator_logs"):
        assert frc.path_for(op) == SUBDIR, op
    # a frame op stays on the full socket: the runner refuses it on the operator one
    for op in ("status", "plan", "provision", "list"):
        assert frc.path_for(op) == TOP, op


def test_an_operator_directory_mount_keeps_the_top_socket(layout):
    """ASIA, sbx-beta and the kit template: no subdirectory, so the answer is exactly the one they had before."""
    layout(subdir_exists=False)
    assert frc.path_for("operator_ping") == TOP
    assert frc.path_for("operator_provision") == frc.socket_path()


def test_the_explicit_operator_socket_wins(layout):
    layout(subdir_exists=True, env="/run/elsewhere/op.sock")
    assert frc.path_for("operator_status") == "/run/elsewhere/op.sock"
    assert frc.path_for("status") == TOP, "the env names the operator socket only"


def test_without_the_subdirectory_the_runner_socket_env_still_steers(layout):
    layout(subdir_exists=False, runner_socket="/run/custom/frame-runner.sock")
    assert frc.path_for("operator_ping") == "/run/custom/frame-runner.sock"


@pytest.mark.asyncio
async def test_call_dials_the_socket_its_op_belongs_to(layout, monkeypatch):
    layout(subdir_exists=True)
    seen = []

    def _exchange(path, request, timeout):
        seen.append((path, request["op"]))
        return {"ok": True, "result": {"op": request["op"]}}

    monkeypatch.setattr(frc, "_exchange", _exchange)
    await frc.call("operator_provision", frame="eu", spec={})
    await frc.call("status")
    assert seen == [(SUBDIR, "operator_provision"), (TOP, "status")]


def test_host_reach_pings_the_operator_socket(monkeypatch):
    """runner_available() and runner_edge() ask the socket a provision would then use, never the full one."""
    fake = types.ModuleType("agentvault_registry.services.frame_runner_client")
    fake.socket_path = lambda: "/full.sock"
    fake.operator_socket_path = lambda: "/operator.sock"
    dialled = []

    def _exchange(path, request, timeout):
        dialled.append(path)
        return {"ok": True, "result": {"edge": "caddy"}} if path == "/operator.sock" else {"refused": "not an operator socket"}

    fake._exchange = _exchange
    import agentvault_registry.services as pkg
    monkeypatch.setattr(pkg, "frame_runner_client", fake, raising=False)
    monkeypatch.setitem(sys.modules, "agentvault_registry.services.frame_runner_client", fake)
    monkeypatch.setattr(hr.os.path, "exists", lambda p: p in ("/full.sock", "/operator.sock"))
    ok, why = hr.runner_available()
    assert ok is True, why
    assert hr.runner_edge() == "caddy"
    assert dialled == ["/operator.sock", "/operator.sock"]
