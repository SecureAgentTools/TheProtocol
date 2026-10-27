"""§F6 (2026-09-27, his words "i approve to finish f6 implementation on sandbox"): a registry with NO docker socket is
F6's posture (the frame runner does its host work), not a fault. Stage 3 takes the socket off sbx-beta's registry and
gates on 24 hours of its log with zero docker failures, and two paths would have failed that gate by warning every
time they ran without one:

- the operator port allocator: "Host port probe via docker SDK failed" once and "port bind probe inconclusive" per
  candidate block. It now says ONCE, at INFO, what decides without a socket (this frame's live blocks, the teardown
  cool-down, its own range; the runner's one-shot binds for real), and never touches the docker SDK;
- the licence drift monitor's dual-frame topology check (IS_CENTRAL_REGISTRY frames, every cycle): "Could not connect
  to docker socket". It now stands down at DEBUG.

A socket that EXISTS and fails is still a warning in both (host reach the registry is meant to have, broken): the
controls below.
"""
import logging
import sys
import types

import pytest

from agentvault_registry.background_tasks import license_drift_monitor as ldm
from agentvault_registry.services import cloud_provisioner as cp


class _Result:
    def __init__(self, bases):
        self.bases = list(bases)

    def all(self):
        return [(b,) for b in self.bases]


class _DB:
    def __init__(self, live=(), torn_recently=()):
        self.live, self.torn = list(live), list(torn_recently)

    async def execute(self, stmt):
        return _Result(self.torn if "cloud_torn_down_at >=" in str(stmt) else self.live)


def _docker_must_not_be_used(monkeypatch):
    mod = types.ModuleType("docker")

    def _refuse(*_a, **_k):
        raise AssertionError("the docker SDK was used on a registry with no docker socket")
    mod.from_env = _refuse
    mod.DockerClient = _refuse
    monkeypatch.setitem(sys.modules, "docker", mod)


def _docker_that_fails(monkeypatch):
    mod = types.ModuleType("docker")

    def _fail(*_a, **_k):
        raise RuntimeError("Error while fetching server API version: connection refused")
    mod.from_env = _fail
    mod.DockerClient = _fail
    mod.errors = types.SimpleNamespace(ImageNotFound=type("ImageNotFound", (Exception,), {}))
    monkeypatch.setitem(sys.modules, "docker", mod)


def _range(monkeypatch, lo, hi):
    monkeypatch.setattr(cp, "CLOUD_PORT_MIN", lo)
    monkeypatch.setattr(cp, "CLOUD_PORT_MAX", hi)
    monkeypatch.setenv("CLOUD_PORT_TEARDOWN_COOLDOWN_MINUTES", "120")


async def test_the_allocator_without_a_socket_says_so_once_and_never_touches_docker(monkeypatch, tmp_path, caplog):
    _range(monkeypatch, 33700, 34499)                                  # sbx-beta's range since V0469
    monkeypatch.setattr(cp, "DOCKER_SOCKET", str(tmp_path / "docker.sock"))   # absent
    _docker_must_not_be_used(monkeypatch)
    caplog.set_level(logging.INFO, logger=cp.logger.name)
    base = await cp.allocate_port_block(_DB(live=[33700], torn_recently=[33800]))
    assert base == 33900, "its own live block and the cool-down still decide"
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings == [], [r.getMessage() for r in warnings]
    said = [r.getMessage() for r in caplog.records if "no docker socket on this registry" in r.getMessage()]
    assert len(said) == 1 and "the runner's one-shot binds for real" in said[0]


async def test_control_the_allocator_with_a_failing_socket_still_warns(monkeypatch, tmp_path, caplog):
    sock = tmp_path / "docker.sock"
    sock.write_text("")                                                # present
    _range(monkeypatch, 33700, 34499)
    monkeypatch.setattr(cp, "DOCKER_SOCKET", str(sock))
    _docker_that_fails(monkeypatch)
    caplog.set_level(logging.INFO, logger=cp.logger.name)
    assert await cp.allocate_port_block(_DB(live=[33700])) == 33800
    msgs = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("Host port probe via docker SDK failed" in m for m in msgs), msgs
    assert not any("no docker socket on this registry" in r.getMessage() for r in caplog.records)


async def test_the_drift_topology_check_without_a_socket_stands_down_quietly(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(ldm, "DOCKER_SOCKET", str(tmp_path / "docker.sock"))   # absent
    _docker_must_not_be_used(monkeypatch)
    caplog.set_level(logging.DEBUG, logger=ldm.logger.name)
    assert await ldm._check_operator_network_topology() == []
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
    assert any("dual-frame operator topology check is not run here" in r.getMessage() for r in caplog.records)


async def test_control_the_drift_topology_check_with_a_failing_socket_still_warns(monkeypatch, tmp_path, caplog):
    sock = tmp_path / "docker.sock"
    sock.write_text("")
    monkeypatch.setattr(ldm, "DOCKER_SOCKET", str(sock))
    _docker_that_fails(monkeypatch)
    caplog.set_level(logging.DEBUG, logger=ldm.logger.name)
    assert await ldm._check_operator_network_topology() == []
    assert any("Could not connect to docker socket" in r.getMessage() for r in caplog.records
               if r.levelno >= logging.WARNING)


@pytest.mark.parametrize("module", [cp, ldm])
def test_both_read_the_one_socket_path(module):
    assert module.DOCKER_SOCKET == "/var/run/docker.sock"
