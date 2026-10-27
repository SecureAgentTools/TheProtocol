"""§MTLSHOPS (2026-09-15, b5): a fresh frame's SPIRE entries exist before a compose up that has to converge.

Since T2 and S5 a fresh frame has services that wait service_healthy on an SVID (the kit and auditor cert-writers,
redpanda-tls), and `compose up -d` waits on such a dependency with no end. The driver registered the entries only after a
reconcile that needs every service running, so no fresh standup could complete. These drive the helper, main()'s fresh
path and post_boot's reconcile with fakes. STANDUP_DRIVER_UNDER_TEST points them at another copy of the driver (the red
run against a driver without the fix). Contract R32 pins the same order for CI.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import subprocess as _real_subprocess
import sys
import types

import pytest

HERE = pathlib.Path(__file__).resolve().parents[1]
DRIVER = pathlib.Path(os.environ.get("STANDUP_DRIVER_UNDER_TEST") or HERE / "standup_driver.py")
NAME = "sbx"
SPIRE_UP = ["up", "-d", f"{NAME}-spire-server", f"{NAME}-spire-agent"]


class _Died(Exception):
    pass


class _Stop(Exception):
    """post_boot reached the registry health wait: what this file measures happened before it."""


@pytest.fixture()
def drv():
    spec = importlib.util.spec_from_file_location("standup_driver_entries_first", DRIVER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Stack:
    """A frame whose opa waits on the kit cert-writer's SVID: opa stays Created until a full compose up runs after the
    entries exist, the way compose leaves the dependant of a dependency that never turns healthy (the order lab)."""

    SERVICES = [f"{NAME}-spire-server", f"{NAME}-spire-agent", f"{NAME}-kit-cert-writer", f"{NAME}-opa"]

    def __init__(self, registered=False, answers=None, spire_rc=0):
        self.events, self.calls = [], []
        self.registered = self.opa_up = registered
        self.answers, self.spire_rc = list(answers or []), spire_rc

    # the provisioner's half
    def register_test_frame_spire_entries(self, ctx):
        self.events.append("register")
        ok, detail = self.answers.pop(0) if self.answers else (True, "parent=d0ed9f784c8a... added 7/7 entries")
        self.registered = self.registered or (ok and "FAILED" not in detail)
        return ok, detail

    def generate_spire_x509pop_certs(self, ctx):
        return True, "x509pop certs"

    def write_stack_files(self, ctx):
        return True, "stack files"

    def provision_frame_test(self, ctx, timeout_seconds=240):
        self.events.append("provision_frame_test")
        return types.SimpleNamespace(containers_started=23)

    # docker
    def run(self, argv, **kw):
        self.calls.append(list(argv))
        rc = 0
        if "docker:cli" in argv and list(argv[-4:]) == SPIRE_UP:
            self.events.append("compose up spire")
            rc = self.spire_rc
        elif "docker:cli" in argv and "up -d" in " ".join(argv):
            self.events.append("compose up all")
            self.opa_up = self.opa_up or self.registered
        return _real_subprocess.CompletedProcess(argv, rc, "", "")

    def states(self, name, project=None):
        return {s: ("running", None) if s != f"{NAME}-opa" or self.opa_up else ("created", None) for s in self.SERVICES}


def _fakes(drv, monkeypatch, stack):
    fake = types.ModuleType("subprocess")
    fake.__dict__.update(_real_subprocess.__dict__)
    fake.run = stack.run
    monkeypatch.setattr(drv, "subprocess", fake)
    monkeypatch.setattr(drv.time, "sleep", lambda s: None)

    def died(msg, code=1):
        raise _Died(msg)

    monkeypatch.setattr(drv, "die", died)


def _ctx(path="/opt/theprotocol/stack/sbx-1789500000"):
    return types.SimpleNamespace(stack_dir_host=path, stack_dir_container=path)


# ── the helper ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_helper_starts_only_the_spire_server_and_agent_then_registers(drv, monkeypatch):
    stack = Stack()
    _fakes(drv, monkeypatch, stack)
    ok, detail = drv.register_entries_before_compose(_ctx(), stack, types.SimpleNamespace(name=NAME), pause=0)
    assert ok and "added 7/7" in detail
    assert stack.events == ["compose up spire", "register"]
    (up,) = stack.calls
    assert up[:3] == ["docker", "run", "--rm"] and "docker:cli" in up and up[-4:] == SPIRE_UP


def test_the_helper_waits_for_the_agent_to_attest(drv, monkeypatch):
    waiting = (False, "agent not yet attested; out=")
    stack = Stack(answers=[waiting, waiting, (True, "added 7/7 entries")])
    _fakes(drv, monkeypatch, stack)
    ok, _ = drv.register_entries_before_compose(_ctx(), stack, types.SimpleNamespace(name=NAME), pause=0)
    assert ok and stack.events == ["compose up spire", "register", "register", "register"]


REFUSED = (True, "parent=d0ed9f784c8a... added 6/7 entries, 1 FAILED: spiffe://sbx.test/service/kit rc=1: 'x'")


def test_an_entry_the_server_refused_refuses_at_once_naming_it(drv, monkeypatch):
    stack = Stack(answers=[REFUSED, REFUSED])
    _fakes(drv, monkeypatch, stack)
    ok, detail = drv.register_entries_before_compose(_ctx(), stack, types.SimpleNamespace(name=NAME), pause=0)
    assert not ok and stack.events == ["compose up spire", "register"]
    assert detail.startswith("the SPIRE server refused an entry") and "spiffe://sbx.test/service/kit" in detail


def test_an_agent_that_never_attests_refuses_after_its_tries(drv, monkeypatch):
    stack = Stack(answers=[(False, "agent not yet attested; out=")] * 3)
    _fakes(drv, monkeypatch, stack)
    ok, detail = drv.register_entries_before_compose(_ctx(), stack, types.SimpleNamespace(name=NAME), attempts=3, pause=0)
    assert not ok and "not registered after 3 tries" in detail and stack.events.count("register") == 3


def test_a_spire_start_that_failed_registers_nothing(drv, monkeypatch):
    stack = Stack(spire_rc=1)
    _fakes(drv, monkeypatch, stack)
    ok, detail = drv.register_entries_before_compose(_ctx(), stack, types.SimpleNamespace(name=NAME), pause=0)
    assert not ok and "answered rc 1" in detail and "register" not in stack.events


# ── main(): a fresh standup ────────────────────────────────────────────────────────────────────────────────────────────

def test_a_fresh_standup_registers_the_entries_before_its_first_full_compose_up(drv, monkeypatch, tmp_path):
    stack = Stack()
    _fakes(drv, monkeypatch, stack)
    sd = tmp_path / f"{NAME}-1789500000"
    sd.mkdir()
    ctx = types.SimpleNamespace(stack_dir_host=str(sd), stack_dir_container=str(sd), port_ntfy=8199, port_grafana=3000,
                                port_auditor=8045)
    monkeypatch.setattr(drv, "validate_args", lambda a: [])
    monkeypatch.setattr(drv, "derive_run_values", lambda a, interactive=True: [])
    monkeypatch.setattr(drv, "kit_directory_default", lambda a: None)
    monkeypatch.setattr(drv, "preflight", lambda a: None)
    monkeypatch.setattr(drv, "load_provisioner", lambda: stack)
    monkeypatch.setattr(drv, "build_ctx", lambda a, ts, p: ctx)
    monkeypatch.setattr(drv, "mutate_rendered", lambda c, a: None)
    monkeypatch.setattr(drv, "post_boot", lambda a, c, m, **kw: stack.events.append("post_boot"))
    monkeypatch.setattr(sys, "argv", ["standup_driver.py", "--name", NAME])
    drv.main()
    assert stack.events == ["compose up spire", "register", "provision_frame_test", "post_boot"]
    assert json.loads((sd / "hetzner-demo-run.json").read_text())["spire_entries_before_compose"] is True


def _fresh_main(drv, monkeypatch, tmp_path, stack):
    _fakes(drv, monkeypatch, stack)
    sd = tmp_path / f"{NAME}-1789500000"
    sd.mkdir()
    ctx = types.SimpleNamespace(stack_dir_host=str(sd), stack_dir_container=str(sd), port_ntfy=8199, port_grafana=3000,
                                port_auditor=8045)
    for fn, fake in (("validate_args", lambda a: []), ("derive_run_values", lambda a, interactive=True: []),
                     ("kit_directory_default", lambda a: None), ("preflight", lambda a: None),
                     ("load_provisioner", lambda: stack), ("build_ctx", lambda a, ts, p: ctx),
                     ("mutate_rendered", lambda c, a: None),
                     ("post_boot", lambda a, c, m, **kw: stack.events.append("post_boot"))):
        monkeypatch.setattr(drv, fn, fake)
    monkeypatch.setattr(sys, "argv", ["standup_driver.py", "--name", NAME])
    drv.main()


def test_a_fresh_standup_whose_entry_is_refused_stops_before_any_workload_starts(drv, monkeypatch, tmp_path):
    stack = Stack(answers=[REFUSED])
    with pytest.raises(_Died) as died:
        _fresh_main(drv, monkeypatch, tmp_path, stack)
    assert str(died.value).startswith("spire entries before compose up: the SPIRE server refused an entry")
    assert "spiffe://sbx.test/service/kit" in str(died.value)
    assert stack.events == ["compose up spire", "register"]   # no provision_frame_test: no workload was started


def test_a_resume_of_another_generation_is_refused_before_any_spire_write(drv, monkeypatch, tmp_path):
    """85's condition 2: on a resume the R31 guard answers before the pre-registration could write to SPIRE."""
    stack = Stack()
    _fakes(drv, monkeypatch, stack)
    sd = tmp_path / "lantern-1789436785"
    sd.mkdir()
    (sd / "hetzner-demo-run.json").write_text(json.dumps({"name": "lantern", "ts": 1789436785}))
    (sd / "docker-compose.frame-test.yml").write_text("services:\n  lantern-registry:\n    image: r\n")
    (sd / ".env.frame-test").write_text("FIRST_ADMIN_EMAIL=a@b.c\n")
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "docker-compose.frame-test.yml.tmpl").write_text(
        "# frame-template-generation: mtlshops-t2\nservices:\n  {{REGISTRY_NAME}}-registry:\n    image: r\n")
    monkeypatch.setattr(drv, "TEMPLATES", str(templates))
    for fn, fake in (("validate_args", lambda a: []), ("derive_run_values", lambda a, interactive=True: []),
                     ("kit_directory_default", lambda a: None), ("load_provisioner", lambda: stack)):
        monkeypatch.setattr(drv, fn, fake)
    monkeypatch.setattr(sys, "argv", ["standup_driver.py", "--name", "lantern", "--resume-stack-dir", str(sd),
                                      "--resume-from", "compose"])
    with pytest.raises(_Died) as died:
        drv.main()
    assert str(died.value).startswith("lantern cannot be resumed")
    assert stack.events == [] and stack.calls == []


# ── post_boot(): the reconcile ─────────────────────────────────────────────────────────────────────────────────────────

def _post_boot(drv, monkeypatch, tmp_path, stack, meta):
    _fakes(drv, monkeypatch, stack)
    sd = tmp_path / f"{NAME}-1789500000"
    sd.mkdir(exist_ok=True)
    monkeypatch.setattr(drv, "expected_frame_services", lambda compose, env: list(Stack.SERVICES))
    monkeypatch.setattr(drv, "frame_container_states", stack.states)

    def health_wait(desc, fn, tries=60, sleep=3):
        raise _Stop(desc)

    monkeypatch.setattr(drv, "wait_for", health_wait)
    with pytest.raises(_Stop):
        drv.post_boot(types.SimpleNamespace(name=NAME, resume_until=None), _ctx(str(sd)), meta, resume_from="compose", prov=stack)
    return sd


def test_a_resume_with_no_record_registers_the_entries_before_its_reconcile(drv, monkeypatch, tmp_path):
    stack = Stack()
    sd = _post_boot(drv, monkeypatch, tmp_path, stack, {"name": NAME, "ts": 1789500000, "steps_done": []})
    # the reconcile's one full up converges, then the spire step runs the same registration again (an update)
    assert stack.events == ["compose up spire", "register", "compose up all", "register"]
    assert json.loads((sd / "hetzner-demo-run.json").read_text())["spire_entries_before_compose"] is True


def test_a_run_that_registered_before_its_compose_up_is_not_registered_again_before_the_reconcile(drv, monkeypatch, tmp_path):
    stack = Stack(registered=True)
    _post_boot(drv, monkeypatch, tmp_path, stack,
               {"name": NAME, "ts": 1789500000, "steps_done": [], "spire_entries_before_compose": True})
    assert stack.events == ["register"]   # the spire step's own pass, nothing before the reconcile
