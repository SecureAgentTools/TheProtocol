"""D6-788: --timeout reaches `license verify` and `sync`, as it reaches every other call.

Since CB-228 and CB-289 both commands ask the parent through the registry container (parent_call) with a fixed timeout,
20 s and 60 s, so the global --timeout, which every HTTP call honours (timeout_or), no longer reached them. The parent
call is replaced by a recorder: these pin the timeout the commands hand it, not a host.
"""
import sys
from pathlib import Path

import pytest

pytest.importorskip("typer")
from typer.testing import CliRunner  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tp_operator import parent_call  # noqa: E402
from tp_operator.main import app  # noqa: E402


@pytest.fixture
def stack(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
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


@pytest.fixture
def asked(monkeypatch):
    seen = []

    def _call(ctx, method, console_path, lane_path, *, params=None, json_body=None, timeout=30.0):
        seen.append(timeout)
        return {"status": 200, "lane": "federation", "body": {"ok": True}}
    monkeypatch.setattr(parent_call, "call_parent", _call)
    return seen


@pytest.mark.parametrize("command,default", [(["license", "verify"], 20.0), (["sync"], 60.0)])
def test_the_global_timeout_reaches_the_parent_call(stack, asked, command, default):
    r = CliRunner().invoke(app, ["--config", str(stack), "--timeout", "7", *command])
    assert r.exit_code == 0, r.output
    assert asked == [7.0]


@pytest.mark.parametrize("command,default", [(["license", "verify"], 20.0), (["sync"], 60.0)])
def test_without_it_each_keeps_its_own(stack, asked, command, default):
    r = CliRunner().invoke(app, ["--config", str(stack), *command])
    assert r.exit_code == 0, r.output
    assert asked == [default]
