"""§F6 WP6.0 (2026-09-26): HOST_REACH_PREFER names the route an operator's host work takes when a registry holds both.

Since the runner's operator socket was mounted on ASIA and sbx-beta (EU and sbx-alpha had the whole runner directory
already), all four registries hold BOTH routes: the docker socket with the host stack, and the frame runner. Unset, the
order stays today's byte for byte (this registry itself, then the runner); "runner" and "direct" take ONE route and fail
closed with that route's own sentence, never falling back to the other; anything else refuses. Every rule has its
control: the same state under another setting answers differently.
"""
from __future__ import annotations

import importlib.util
import os
import pathlib

import pytest

_HERE = pathlib.Path(__file__).resolve()
_SRC = pathlib.Path(os.environ["OPDIST_SRC"]) if os.environ.get("OPDIST_SRC") else (
    _HERE.parents[1] / "src" / "agentvault_registry")


@pytest.fixture
def hr(monkeypatch):
    spec = importlib.util.spec_from_file_location("_f6_host_route", _SRC / "core" / "host_reach.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.delenv("HOST_REACH_PREFER", raising=False)
    return mod


def _state(monkeypatch, hr, *, direct: bool, runner: bool):
    monkeypatch.setattr(hr, "docker_socket_available", lambda: (direct, "DIRECT-WHY"))
    monkeypatch.setattr(hr, "runner_available", lambda: (runner, "RUNNER-WHY"))


@pytest.mark.parametrize("direct,runner,want", [(True, True, "direct"), (True, False, "direct"),
                                                (False, True, "runner"), (False, False, None)])
def test_unset_keeps_todays_order(monkeypatch, hr, direct, runner, want):
    _state(monkeypatch, hr, direct=direct, runner=runner)
    route, why = hr.host_route()
    assert route == want
    if want is None:
        assert why == "DIRECT-WHY; and RUNNER-WHY"             # both reasons, as host_reach_available always said
    assert hr.host_reach_available() == (want is not None, why)


def test_runner_is_taken_when_both_exist_and_never_falls_back(monkeypatch, hr):
    _state(monkeypatch, hr, direct=True, runner=True)
    monkeypatch.setenv("HOST_REACH_PREFER", "runner")
    assert hr.host_route()[0] == "runner"
    _state(monkeypatch, hr, direct=True, runner=False)
    route, why = hr.host_route()
    assert route is None and "HOST_REACH_PREFER=runner" in why and "RUNNER-WHY" in why and "fail closed" in why
    assert "DIRECT-WHY" not in why                             # the socket's answer is not consulted as a fallback
    assert hr.host_reach_available()[0] is False
    monkeypatch.delenv("HOST_REACH_PREFER")                    # the control: unset, the same state takes the socket
    assert hr.host_route()[0] == "direct"


def test_direct_is_taken_alone_and_fails_closed_the_same_way(monkeypatch, hr):
    _state(monkeypatch, hr, direct=False, runner=True)
    monkeypatch.setenv("HOST_REACH_PREFER", "direct")
    route, why = hr.host_route()
    assert route is None and "HOST_REACH_PREFER=direct" in why and "DIRECT-WHY" in why and "RUNNER-WHY" not in why
    monkeypatch.delenv("HOST_REACH_PREFER")
    assert hr.host_route()[0] == "runner"


def test_a_value_this_code_does_not_know_is_refused_and_case_does_not_matter(monkeypatch, hr):
    _state(monkeypatch, hr, direct=True, runner=True)
    monkeypatch.setenv("HOST_REACH_PREFER", "socket")
    route, why = hr.host_route()
    assert route is None and "neither 'runner' nor 'direct'" in why
    monkeypatch.setenv("HOST_REACH_PREFER", " Runner ")
    assert hr.host_route()[0] == "runner"


def test_the_route_choosers_ask_host_route():
    """The three places that choose a route read the one predicate, so a knob set on the frame reaches all of them."""
    apps = (_SRC / "routers" / "operator_applications.py").read_text(encoding="utf-8")
    prov = (_SRC / "services" / "cloud_provisioner.py").read_text(encoding="utf-8")
    assert "host_route()" in apps and "docker_socket_available" not in apps
    assert prov.count("from agentvault_registry.core.host_reach import host_route") == 2   # provision and teardown
    assert "docker_socket_available" not in prov
    assert "host_reach_available()" in apps                    # the guard before the one-time code is spent stays


def test_the_docstring_no_longer_says_only_eu_and_asia_hold_the_stack():
    src = (_SRC / "core" / "host_reach.py").read_text(encoding="utf-8")
    assert "(EU and ASIA do)" not in src and "the sandbox pair" in src
