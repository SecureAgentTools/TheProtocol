"""The compose commands the CLI builds (CB-226): a recreate of ONE service never touches its dependencies.

`restart <service> --apply-env-changes` recreates the service so an edited env takes effect. Without --no-deps compose
also recreates everything the service depends on (the registry's databases, Redis, pgbouncer), the most repeated
mistake in this project's operations. The whole stack (no service named) keeps the plain form.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tp_operator import docker_runner as dr  # noqa: E402
from tp_operator.config import OperatorContext  # noqa: E402


def _ctx(tmp_path):
    (tmp_path / "docker-compose.operator.yml").write_text("services: {}\n")
    env = tmp_path / ".env.operator"
    env.write_text("REGISTRY_NAME=cloud-op-x\n")
    return OperatorContext(name="cloud-op-x", dir=tmp_path, env_path=env, env={})


def _capture(monkeypatch):
    seen = []

    def fake_run(cmd, **kw):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(dr, "run", fake_run)
    return seen


def test_recreating_one_service_never_recreates_its_dependencies(tmp_path, monkeypatch):
    seen = _capture(monkeypatch)
    rc, _ = dr.compose_restart(_ctx(tmp_path), "registry", force_recreate=True)
    assert rc == 0
    cmd = seen[-1]
    up = cmd.index("up")
    assert cmd[up:] == ["up", "-d", "--no-deps", "--no-build", "--force-recreate", "registry"], cmd


def test_the_whole_stack_and_a_plain_restart_keep_their_forms(tmp_path, monkeypatch):
    seen = _capture(monkeypatch)
    ctx = _ctx(tmp_path)
    dr.compose_restart(ctx, None, force_recreate=True)
    assert seen[-1][seen[-1].index("up"):] == ["up", "-d", "--force-recreate"]
    dr.compose_restart(ctx, "registry")
    assert seen[-1][-2:] == ["restart", "registry"] and "--no-deps" not in seen[-1]
