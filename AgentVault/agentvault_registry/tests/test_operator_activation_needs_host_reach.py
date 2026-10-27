"""§OPDIST — the operator rail refuses on a frame that cannot finish, BEFORE it spends the one-time code.

An operator's bundle and stack are built through the HOST Docker API. Every frame the runner builds is hardened
without /var/run/docker.sock on purpose, because a docker socket is root on the host, so those frames cannot
provision their own operators; EU and ASIA can only do it because they carry the socket.

`standup_driver.py` has refused that combination for months ("--with-operator needs --grant-host-reach"). The PRODUCT
RAIL had no equivalent, so Operator Management on a hardened frame reached apply, approve and ACTIVATE — consuming the
one-time activation code and issuing a real dpt_ pull token — and only failed at provision, after those side effects.
Measured on lantern 2026-09-16 by agentvault2-85: "Provisioning failed: Bundle not found at None."

Structural, because the property is an ORDER: the refusal has to come before the first mutation, not merely exist.
"""
from __future__ import annotations

import ast
import importlib.util
import os
import pathlib

import pytest

_HERE = pathlib.Path(__file__).resolve()
_SRC = pathlib.Path(os.environ["OPDIST_SRC"]) if os.environ.get("OPDIST_SRC") else (
    _HERE.parents[1] / "src" / "agentvault_registry")


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, _SRC / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _install_runner(monkeypatch, *, socket_exists: bool, answer=None):
    """Put a frame_runner_client in place the way a real image has one.

    The loader above reads host_reach.py as a standalone file, so `agentvault_registry.services` is not importable in
    this context and the predicate would report that instead of the socket's own answer: a true sentence about the
    TEST, which is not the state any frame is ever in. Injecting the module keeps the test measuring the thing it is
    about (what the runner says), and the not-importable branch gets its own test below.
    """
    import sys
    import types
    frc = types.ModuleType("agentvault_registry.services.frame_runner_client")
    frc.socket_path = lambda: "/run/theprotocol/frame-runner.sock"
    frc.operator_socket_path = frc.socket_path   # a registry that mounts the operator directory alone: one socket
    frc._exchange = lambda path, req, timeout: (answer if answer is not None else {"ok": True})
    pkg = types.ModuleType("agentvault_registry.services")
    pkg.frame_runner_client = frc
    monkeypatch.setitem(sys.modules, "agentvault_registry.services", pkg)
    monkeypatch.setitem(sys.modules, "agentvault_registry.services.frame_runner_client", frc)
    return frc


def test_no_socket_is_refused_and_says_why(monkeypatch):
    cp = _load("core/host_reach.py", "_opdist_hr")
    _install_runner(monkeypatch, socket_exists=False)
    monkeypatch.setattr(cp.os.path, "exists", lambda p: False)
    ok, why = cp.host_reach_available()
    assert ok is False
    # BOTH routes must be named: "no docker socket" stopped being the whole truth the day the runner could do it
    assert "docker.sock" in why and "hardened" in why
    assert "frame runner socket" in why, "a refusal naming one route sends the reader to the wrong fix"


def test_a_socket_whose_daemon_does_not_answer_is_also_refused(monkeypatch):
    """A mounted socket is not the property; the daemon answering is. A socket with no permission behind it fails in
    exactly the way this exists to catch, so presence alone must not be read as capability."""
    cp = _load("core/host_reach.py", "_opdist_hr2")
    _install_runner(monkeypatch, socket_exists=True, answer={"refused": "op 'operator_ping' is not served on this socket"})
    monkeypatch.setattr(cp.os.path, "exists", lambda p: True)
    _isdir = cp.os.path.isdir
    monkeypatch.setattr(cp.os.path, "isdir", lambda p: True if p == "/host-stack" else _isdir(p))   # full host reach

    class _Boom:
        def __init__(self, *a, **k):
            raise OSError("permission denied")

    import sys
    import types
    fake = types.ModuleType("docker")
    fake.DockerClient = _Boom
    monkeypatch.setitem(sys.modules, "docker", fake)
    ok, why = cp.host_reach_available()
    assert ok is False and "did not answer" in why


def test_the_refusal_comes_before_the_first_mutation():
    """The order IS the property: a refusal after the code is consumed leaves a burnt code and a live pull token."""
    src = (_SRC / "routers" / "operator_applications.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "activate_operator")
    guard = [n.lineno for n in ast.walk(fn)
             if isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) == "host_reach_available"]
    assert guard, "the activate route no longer checks host reach"
    # the first thing that changes state: marking the developer a federation operator
    mutation = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Assign)
                for t in n.targets if getattr(t, "attr", "") == "is_federation_operator"]
    assert mutation, "the mutation this guard protects has moved; re-derive the order"
    assert min(guard) < min(mutation), "the refusal must come BEFORE the first side effect"


def test_the_refusal_tells_the_caller_nothing_was_spent():
    """A 409 that does not say the code survives sends someone hunting for a new one they do not need."""
    src = (_SRC / "routers" / "operator_applications.py").read_text()
    assert "has NOT been" in src and "Nothing was changed" in src


def test_a_socket_without_the_host_stack_is_not_direct_reach(monkeypatch):
    """§TESTBED (2026-09-19): a SANDBOX's registry holds the docker socket for its own tester (which docker-execs into
    its own containers) and nothing else of the host. Read as "this registry can do it itself", activation built no
    bundle and still answered 200, and provisioning then failed "Bundle not found at None" (measured on larchsbx). The
    socket alone is not host reach: without the host's stack directory the frame runner does the work, and the daemon
    is not even asked."""
    hr = _load("core/host_reach.py", "_opdist_hr6")
    _install_runner(monkeypatch, socket_exists=True, answer={"ok": True, "result": {"ops": ["operator_provision"]}})
    monkeypatch.setattr(hr.os.path, "exists", lambda p: True)
    _isdir = hr.os.path.isdir
    monkeypatch.setattr(hr.os.path, "isdir", lambda p: False if p == "/host-stack" else _isdir(p))

    import sys
    import types
    asked = []

    class _Daemon:
        def __init__(self, *a, **k):
            asked.append(k.get("base_url"))

        def ping(self):
            return True

    fake = types.ModuleType("docker")
    fake.DockerClient = _Daemon
    monkeypatch.setitem(sys.modules, "docker", fake)
    direct_ok, direct_why = hr.docker_socket_available()
    assert direct_ok is False and "/host-stack" in direct_why and "frame runner" in direct_why
    assert asked == [], "the daemon answering is not the question when the stack directory is absent"
    ok, why = hr.host_reach_available()
    assert ok is True and "frame runner answers operator_ping" in why


def test_a_frame_with_no_docker_socket_but_a_runner_can_provision(monkeypatch):
    """The second term, and the reason the refusal message had to change with it.

    A runner-built frame has no docker socket ON PURPOSE and can still get the work done, because the runner does it
    in a one-shot container. A predicate that only asked about the socket would refuse every frame this architecture
    exists to serve, and its message would name a fix nobody should apply.
    """
    hr = _load("core/host_reach.py", "_opdist_hr3")
    _install_runner(monkeypatch, socket_exists=True, answer={"ok": True, "result": {"ops": ["operator_provision"]}})
    monkeypatch.setattr(hr.os.path, "exists", lambda p: "docker.sock" not in p)
    ok, why = hr.host_reach_available()
    assert ok is True and "frame runner" in why


def test_a_runner_socket_that_refuses_operator_ping_is_not_capability(monkeypatch):
    """Presence is not the property, one level up: a socket that exists and refuses everything must read unavailable."""
    hr = _load("core/host_reach.py", "_opdist_hr4")
    _install_runner(monkeypatch, socket_exists=True,
                    answer={"refused": "op 'operator_ping' is not served on this socket"})
    monkeypatch.setattr(hr.os.path, "exists", lambda p: "docker.sock" not in p)
    ok, why = hr.host_reach_available()
    assert ok is False and "not served on this socket" in why


def test_an_unimportable_runner_client_is_its_own_state(monkeypatch):
    """The third outcome the predicate owes: it could not ask. An image without the client module is not the same as
    a frame whose runner refused, and a refusal that conflates them sends the reader to the wrong fix."""
    hr = _load("core/host_reach.py", "_opdist_hr5")
    import sys
    monkeypatch.setitem(sys.modules, "agentvault_registry.services", None)  # import raises
    monkeypatch.setattr(hr.os.path, "exists", lambda p: False)
    ok, why = hr.host_reach_available()
    assert ok is False and "not importable here" in why and "docker.sock" in why


def _route_src() -> str:
    return (_SRC / "routers" / "operator_applications.py").read_text()


def _fn(name: str):
    tree = ast.parse(_route_src())
    return next(n for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def _fn_in(relpath: str, name: str):
    """The same question asked of any file under src, for the parts of this route that live outside the router."""
    import pathlib
    root = pathlib.Path(os.environ["OPDIST_SRC"]) if os.environ.get("OPDIST_SRC") else (
        pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry")
    tree = ast.parse((root / relpath).read_text(encoding="utf-8"))
    return next(n for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def test_the_route_is_chosen_by_the_predicate_not_by_a_flag():
    """Which half does the work is a measured property of the frame, asked the same way the guard asks it.

    A flag or an env switch would be a second copy of the answer, and the two would disagree the first time one was
    set by hand: a frame could refuse activation while believing it could provision, or the reverse.

    §F6 WP6.0 (2026-09-26): the chooser is host_route(), and the guard (host_reach_available) IS host_route() too, so
    the one knob that names a preference (HOST_REACH_PREFER) is read by both in one place and cannot make them disagree.
    It only narrows the routes and never makes an unavailable one look available (fail closed: test_host_route.py).
    """
    fn = _fn("activate_operator")
    asked = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
             and getattr(n.func, "id", getattr(n.func, "attr", "")) == "host_route"]
    assert asked, "the activate route must ask host_route() which route to take"
    hr_src = (_SRC / "core" / "host_reach.py").read_text(encoding="utf-8")
    assert "route, why = host_route()\n    return route is not None, why" in hr_src, "the guard must be host_route() itself"
    # and the runner branch must ask for the BUNDLE, not the whole operator: activation has never stood a stack up
    call = next(n for n in ast.walk(fn) if isinstance(n, ast.Call)
                and getattr(n.func, "id", "") == "_bundle_through_runner")
    assert call, "the socket-less branch goes through the runner helper"


def test_the_runner_branch_asks_for_the_bundle_phase_only():
    # The body moved into operator_provision_client.bundle_through_runner on 2026-09-16, so that provisioning
    # could keep activation's "re-generated later" promise from one implementation instead of a second copy.
    # The question is unchanged: does the activation path ask for anything but a bundle.
    fn = _fn_in("services/operator_provision_client.py", "bundle_through_runner")
    phases = [kw.value.value for n in ast.walk(fn) if isinstance(n, ast.Call)
              for kw in n.keywords if kw.arg == "phase" and isinstance(kw.value, ast.Constant)]
    assert phases == ["bundle"], (
        f"activation asks for {phases}; the full phase brings a stack up, which is not what this button does on a "
        f"frame that holds its own socket")


def test_the_row_stores_this_registrys_view_of_the_bundle_never_the_far_sides():
    """The failure this would cause is silent until someone downloads a bundle, days later.

    The one-shot writes the tar into the frame's operator-bundles directory ON THE HOST and returns that path; this
    registry sees the same file under OPERATOR_BUNDLES_DIR. Storing what came back would put a path in the row that
    nothing on this side can open — "Bundle not found at ...", the sentence this route exists to remove.
    """
    fn = _fn_in("services/operator_provision_client.py", "bundle_through_runner")
    ret = next(n for n in ast.walk(fn) if isinstance(n, ast.Return))
    assert isinstance(ret.value, ast.Dict)
    value = dict(zip([k.value for k in ret.value.keys], ret.value.values))["bundle_path"]
    assert isinstance(value, ast.Call) and getattr(value.func, "attr", "") == "join", (
        "bundle_path must be joined from this registry's own bundles dir and the returned filename")
    src = ast.unparse(value)
    assert "bundle_filename" in src and "bundles_dir" in src
    assert "result['bundle_path']" not in src and 'result["bundle_path"]' not in src


def test_both_routes_hand_the_row_writer_one_shape():
    """One mapping, one writer. While the two branches returned different shapes, every field added later had to be
    remembered twice, and the attribute reads would have raised only on the frame that has no socket — the frame
    nobody runs the suite against."""
    fn = _fn("activate_operator")
    attr_reads = [ast.unparse(n) for n in ast.walk(fn) if isinstance(n, ast.Attribute)
                  and getattr(n.value, "id", "") == "provision_result" and n.attr != "get"]
    assert attr_reads == [], f"these still read the old object shape: {attr_reads}"
    subscripts = [ast.unparse(n) for n in ast.walk(fn) if isinstance(n, ast.Subscript)
                  and getattr(n.value, "id", "") == "provision_result"]
    assert len(subscripts) >= 8, f"the rows should be written from the mapping; found {subscripts}"
