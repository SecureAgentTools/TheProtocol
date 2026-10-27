"""The provisioner's reconcile says what it saw (named in FINDINGS_2026-09-27_NIGHTPROV.md; fixed 2026-09-27, §F6 stage 5).

The closing warning ended "(host load high)" whatever it saw (the §F6 WP6.2 finding: it named load for an image-pull
failure), and a daemon it could not ask counted as "0 running". It now names the running count, every other state, how
many containers were never created and the load as a number, or says the daemon was unreadable.
"""
import ast
import os
import types

from agentvault_registry.services import cloud_provisioner as cp

SRC = os.path.join(os.path.dirname(cp.__file__), "cloud_provisioner.py")


def _client(statuses, prefix="cloud-op-opx-"):
    containers = [types.SimpleNamespace(name=f"{prefix}{i}", status=s) for i, s in enumerate(statuses)]
    containers.append(types.SimpleNamespace(name="cloud-op-other-registry", status="exited"))   # another operator
    return lambda: types.SimpleNamespace(containers=types.SimpleNamespace(list=lambda all=False, ignore_removed=False: containers))


def test_the_census_counts_every_state_of_this_operator_only():
    census, why = cp._operator_container_census("opx", _client(["running"] * 7 + ["exited", "created"]))
    assert census == {"running": 7, "exited": 1, "created": 1} and why == ""


def test_an_unreadable_daemon_is_none_never_zero():
    def boom():
        raise RuntimeError("Error while fetching server API version")
    census, why = cp._operator_container_census("opx", boom)
    assert census is None and "RuntimeError" in why


def test_a_full_stack_needs_no_line():
    assert cp._reconcile_shortfall_line("opx", {"running": 11}, "", 9, 12.0) is None


def test_a_short_stack_names_what_it_saw_and_the_load_as_a_number():
    line = cp._reconcile_shortfall_line("opx", {"running": 7, "exited": 1, "created": 1}, "", 9, 12.34)
    assert "7/9 running" in line and "created 1" in line and "exited 1" in line and "load1 12.3" in line
    assert "host load high" not in line


def test_containers_never_created_are_counted_as_such():
    line = cp._reconcile_shortfall_line("opx", {"running": 5}, "", 9, None)
    assert "5/9 running" in line and "4 not created" in line and "load unread" in line


def test_an_unreadable_daemon_says_unknown_never_zero_running():
    line = cp._reconcile_shortfall_line("opx", None, "RuntimeError: no socket", 9, 30.0)
    assert "could not be read" in line and "unknown" in line and "RuntimeError: no socket" in line
    assert "0/9" not in line and "host load high" not in line


def test_the_provisioner_uses_them_and_no_longer_guesses_load():
    """Control on the wiring: the old sentence is gone from the provisioner, and provision_cloud_operator calls both."""
    src = open(SRC).read()
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.AsyncFunctionDef) and n.name == "provision_cloud_operator")
    logged = [ast.unparse(a) for n in ast.walk(fn) if isinstance(n, ast.Call) and ast.unparse(n.func).startswith("logger.")
              for a in n.args]
    assert logged and not any("load high" in a for a in logged), "no log line in the provisioner guesses the load"
    called = {ast.unparse(n.func) for n in ast.walk(fn) if isinstance(n, ast.Call)}
    assert "_reconcile_shortfall_line" in called
    assert any("_operator_container_census" in ast.unparse(n) for n in ast.walk(fn) if isinstance(n, ast.Call))
