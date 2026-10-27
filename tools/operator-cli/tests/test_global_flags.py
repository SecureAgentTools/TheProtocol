"""The options the CLI accepted and used nowhere now do what their help says (CB-286).

--quiet printed everything (it only meant plain text); --timeout and --verbose were stored and read by nothing;
`status --detail` showed no extra column; `restart` never waited, so `--no-wait` changed nothing. Docker and the network
are patched out: these pin the behaviour, not a host.
"""
import sys
from contextlib import nullcontext
from pathlib import Path

import httpx
import pytest

pytest.importorskip("typer")
from typer.testing import CliRunner  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tp_operator import docker_runner, http_client  # noqa: E402
from tp_operator.commands import restart, status  # noqa: E402
from tp_operator.main import app  # noqa: E402
from tp_operator.output import Output, detect_output_mode  # noqa: E402


@pytest.fixture
def stack(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))          # the local audit log lands here, not in the real home
    for var in ("CI", "GITHUB_ACTIONS", "GITLAB_CI", "TP_OPERATOR_JSON", "TP_OPERATOR_MAINFRAME_URL",
                "TP_OPERATOR_REMOTE_AUDIT", "NO_COLOR"):
        monkeypatch.delenv(var, raising=False)
    d = tmp_path / "cloud-op-x"
    d.mkdir()
    (d / "docker-compose.operator.yml").write_text("services: {}\n")
    env = d / ".env.operator"
    env.write_text("REGISTRY_NAME=cloud-op-x\nFEDERATION_LICENSE_KEY=tp_fed_0123456789abcdef\n"
                   "CENTRAL_REGISTRY_URL=https://parent.example.invalid\n")
    return env


def _out(result):
    return result.output + (getattr(result, "stderr", "") if result.stderr_bytes is not None else "")


def test_quiet_prints_errors_only(monkeypatch, capsys):
    for var in ("CI", "GITHUB_ACTIONS", "GITLAB_CI", "TP_OPERATOR_JSON"):
        monkeypatch.delenv(var, raising=False)
    assert detect_output_mode(force_quiet=True) == "quiet"
    out = Output("quiet")
    out.line("a line")
    out.success("done")
    out.warn("careful")
    out.table("t", ["A"], [["1"]])
    out.emit_json({"k": 1})
    out.error("broken")
    got = capsys.readouterr()
    assert got.out == "" and got.err.strip() == "ERROR: broken"


def _recording_client(monkeypatch, seen):
    real = httpx.Client

    def factory(*a, **kw):
        seen.append(kw)
        kw["transport"] = httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True}))
        return real(*a, **kw)

    monkeypatch.setattr(http_client.httpx, "Client", factory)


def test_timeout_and_verbose_reach_the_http_call(stack, monkeypatch):
    seen = []
    _recording_client(monkeypatch, seen)
    # `license verify` asks its parent through the registry container since CB-228; `peers` still dials the parent's
    # federation route over HTTP, so it is the command these two tests watch.
    r = CliRunner().invoke(app, ["--config", str(stack), "--timeout", "7", "-v", "peers"])
    assert r.exit_code == 0, _out(r)
    t = seen[-1]["timeout"]
    assert (t.read, t.connect) == (7.0, 7.0)
    assert "HTTP GET https://parent.example.invalid/api/v1/federation/network-stats -> 200" in _out(r)
    assert "tp_fed_0123456789abcdef" not in _out(r)                # the verbose line never carries the licence


def test_without_the_flags_each_call_keeps_its_own_timeout_and_prints_no_request(stack, monkeypatch):
    seen = []
    _recording_client(monkeypatch, seen)
    r = CliRunner().invoke(app, ["--config", str(stack), "peers"])
    assert r.exit_code == 0, _out(r)
    t = seen[-1]["timeout"]
    assert (t.read, t.connect) == (10.0, 5.0)
    assert "HTTP GET" not in _out(r)


def test_status_detail_adds_started_and_restarts(stack, monkeypatch):
    monkeypatch.setattr(status, "docker_info_ok", lambda: True)
    monkeypatch.setattr(status, "compose_ps_json", lambda ctx: [
        {"Service": "registry", "Name": "cloud-op-x-registry", "State": "running", "Health": "healthy", "Image": "img"}])

    def fake_run(cmd, **kw):
        assert cmd[:2] == ["docker", "inspect"] and "cloud-op-x-registry" in cmd
        import subprocess
        return subprocess.CompletedProcess(cmd, 0, "/cloud-op-x-registry\t2026-10-16T10:00:00Z\t3\n", "")

    monkeypatch.setattr(docker_runner, "run", fake_run)
    r = CliRunner().invoke(app, ["--config", str(stack), "--no-color", "status", "--detail"])
    assert r.exit_code == 0, _out(r)
    assert "STARTED\tRESTARTS" in r.output and "2026-10-16T10:00:00Z\t3" in r.output
    plain = CliRunner().invoke(app, ["--config", str(stack), "--no-color", "status"])
    assert "RESTARTS" not in plain.output


def test_restart_waits_for_healthy_unless_no_wait(stack, monkeypatch):
    monkeypatch.setattr(restart, "docker_info_ok", lambda: True)
    monkeypatch.setattr(restart, "compose_restart", lambda ctx, service, force_recreate=False: (0, ""))
    monkeypatch.setattr(restart, "acquire_lock", lambda name: nullcontext())
    waited = []
    monkeypatch.setattr(restart, "wait_healthy", lambda ctx, service, timeout_s: waited.append(service) or False)
    r = CliRunner().invoke(app, ["--config", str(stack), "--yes", "--no-color", "restart", "registry"])
    assert r.exit_code == 1 and waited == ["registry"] and "not healthy" in _out(r)
    waited.clear()
    r = CliRunner().invoke(app, ["--config", str(stack), "--yes", "--no-color", "restart", "registry", "--no-wait"])
    assert r.exit_code == 0 and waited == []


def test_wait_healthy_reads_the_named_service(monkeypatch, tmp_path):
    states = iter([[{"Service": "registry", "State": "running", "Health": "starting"}],
                   [{"Service": "registry", "State": "running", "Health": "healthy"},
                    {"Service": "redis", "State": "exited", "Health": ""}]])
    monkeypatch.setattr(docker_runner, "compose_ps_json", lambda ctx: next(states))
    assert docker_runner.wait_healthy(None, "registry", timeout_s=5, interval_s=0) is True
    monkeypatch.setattr(docker_runner, "compose_ps_json",
                        lambda ctx: [{"Service": "registry", "State": "running", "Health": "unhealthy"}])
    assert docker_runner.wait_healthy(None, "registry", timeout_s=0, interval_s=0) is False
