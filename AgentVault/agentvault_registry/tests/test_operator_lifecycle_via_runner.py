"""§F6 WP6.2 (2026-09-26): an operator's restart and logs through the frame runner, behind OPERATOR_LIFECYCLE_VIA.

Unset (or "local") keeps today's docker:cli sidecar, which needs the host Docker socket. "runner" asks the runner's
operator socket (ops operator_restart / operator_logs) and FAILS CLOSED: a refusal, a missing socket or an unknown flag
value is a RuntimeError with the reason, and the docker path is never taken (a fake docker that raises proves it). The
answers keep the shapes the four routes already return.
"""
import asyncio
import sys
import types

import pytest

from agentvault_registry.services import cloud_provisioner as cp
from agentvault_registry.services import spire_ops_client as soc

APP = types.SimpleNamespace(name="SbxOp")        # the registry's own row name; the runner gets its safe name


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    """asyncio.run() closes its loop and leaves the thread with none; the NEXT file's get_event_loop() would raise."""
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


@pytest.fixture
def docker_sidecar(monkeypatch, tmp_path):
    """The local route's docker SDK, recorded; the operator's stack dir exists under a temporary /host-stack."""
    state = types.SimpleNamespace(runs=[], boom=False)

    class ContainerError(Exception):
        pass

    class Containers:
        def run(self, image, **kw):
            if state.boom:
                raise AssertionError("the docker path was taken in runner mode")
            state.runs.append((image, kw))
            return b"sidecar output\n"

    fake = types.ModuleType("docker")
    fake.from_env = lambda: types.SimpleNamespace(containers=Containers())
    fake.errors = types.SimpleNamespace(ContainerError=ContainerError)
    monkeypatch.setitem(sys.modules, "docker", fake)
    (tmp_path / "cloud-op-sbxop").mkdir()
    monkeypatch.setattr(cp, "HOST_STACK_MOUNT", str(tmp_path))
    return state


@pytest.fixture
def runner_ops(monkeypatch, docker_sidecar):
    monkeypatch.setenv(cp.OPERATOR_LIFECYCLE_VIA_ENV, "runner")
    docker_sidecar.boom = True
    calls, answers = [], {}

    def fake_call(op, *, timeout=30.0, **fields):
        calls.append((op, fields, timeout))
        a = answers.get(op)
        if isinstance(a, Exception):
            raise a
        return a if a is not None else {"rc": 0, "output_tail": "Restarting\n", "output": "line 1\nline 2\n"}
    monkeypatch.setattr(soc, "call", fake_call)
    return calls, answers


def test_unset_keeps_todays_sidecar(monkeypatch, docker_sidecar):
    monkeypatch.delenv(cp.OPERATOR_LIFECYCLE_VIA_ENV, raising=False)
    monkeypatch.setattr(soc, "call", lambda *a, **k: pytest.fail("the runner was asked with the flag unset"))
    out = asyncio.run(cp.restart_cloud_service(APP, "registry"))
    assert out["restarted"] is True and set(out) == {"service", "restarted", "output_tail", "duration_ms"}
    image, kw = docker_sidecar.runs[-1]
    assert image == "docker:cli" and kw["command"].endswith("restart registry'")
    out = asyncio.run(cp.fetch_cloud_logs(APP, "teg-layer", 50))
    assert "--tail=50 teg-layer" in docker_sidecar.runs[-1][1]["command"] and out["output"] == "sidecar output\n"


def test_runner_restart_is_one_op_with_the_safe_name_and_todays_shape(runner_ops):
    calls, _ = runner_ops
    out = asyncio.run(cp.restart_cloud_service(APP, "registry"))
    op, fields, timeout = calls[-1]
    assert (op, fields) == ("operator_restart", {"operator": "sbxop", "service": "registry"})
    assert timeout > 300          # above the runner's own ceiling, so the runner's answer arrives before ours gives up
    assert set(out) == {"service", "restarted", "output_tail", "duration_ms"}
    assert out["restarted"] is True and out["service"] == "registry" and out["output_tail"] == "Restarting\n"


def test_runner_logs_are_one_op_and_todays_shape(runner_ops):
    calls, answers = runner_ops
    out = asyncio.run(cp.fetch_cloud_logs(APP, "all", 30))
    assert calls[-1][:2] == ("operator_logs", {"operator": "sbxop", "service": "all", "tail": 30})
    assert set(out) == {"service", "tail", "output", "lines", "duration_ms", "fetched_at"}
    assert out["output"] == "line 1\nline 2\n" and out["lines"] == 2
    answers["operator_logs"] = {"rc": 1, "output": "no such service yet\n"}    # compose's non-zero still shows what it said
    assert asyncio.run(cp.fetch_cloud_logs(APP, "registry", 30))["output"] == "no such service yet\n"


def test_a_failed_restart_is_a_failure(runner_ops):
    _, answers = runner_ops
    answers["operator_restart"] = {"rc": 1, "output_tail": "no such service: cert-writer"}
    with pytest.raises(RuntimeError, match=r"exit 1\): no such service"):
        asyncio.run(cp.restart_cloud_service(APP, "cert-writer"))


def test_a_refusal_fails_closed_with_the_runners_sentence(runner_ops):
    calls, answers = runner_ops
    for op in ("operator_restart", "operator_logs"):
        answers[op] = soc.SpireOpsUnavailable("the frame runner refused op: operator 'sbxop' is not an operator of the "
                                              "calling frame sbx-alpha")
    with pytest.raises(RuntimeError, match="not an operator of the calling frame"):
        asyncio.run(cp.restart_cloud_service(APP, "registry"))
    with pytest.raises(RuntimeError, match="not an operator of the calling frame"):
        asyncio.run(cp.fetch_cloud_logs(APP, "registry", 30))


def test_the_closed_sets_refuse_before_any_route(runner_ops):
    calls, _ = runner_ops
    with pytest.raises(ValueError):
        asyncio.run(cp.restart_cloud_service(APP, "registry; rm -rf /"))
    with pytest.raises(ValueError):
        asyncio.run(cp.fetch_cloud_logs(APP, "registry", 5000))
    assert calls == []


def test_a_flag_value_this_code_does_not_know_is_refused(monkeypatch, docker_sidecar):
    monkeypatch.setenv(cp.OPERATOR_LIFECYCLE_VIA_ENV, "sidecar")
    docker_sidecar.boom = True
    monkeypatch.setattr(soc, "call", lambda *a, **k: pytest.fail("the runner was asked under an unknown flag"))
    with pytest.raises(RuntimeError, match="neither 'local' nor 'runner'"):
        asyncio.run(cp.restart_cloud_service(APP, "registry"))
    with pytest.raises(RuntimeError, match="neither 'local' nor 'runner'"):
        asyncio.run(cp.fetch_cloud_logs(APP, "registry", 30))
