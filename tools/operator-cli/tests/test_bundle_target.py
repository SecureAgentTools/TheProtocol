"""The bundle commands call the stack's OWN registry, and --dry-run makes no write (CB-298).

They called the PARENT frame (mainframe_url, or https://api.theprotocol.cloud on a standalone stack), where an operator's
developer key means nothing and none of its agents live, and ignored --dry-run. The registry is now the one the compose
publishes on this host (TP_OPERATOR_REGISTRY_URL overrides). The registry is a mock transport here.
"""
import sys
from pathlib import Path

import httpx
import pytest

pytest.importorskip("typer")
from typer.testing import CliRunner  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tp_operator.commands import bundle  # noqa: E402
from tp_operator.config import OperatorContext  # noqa: E402
from tp_operator.main import app  # noqa: E402


def _ctx(tmp_path, ports_line, env=None):
    (tmp_path / "docker-compose.operator.yml").write_text(
        f"services:\n  registry:\n    ports:\n      - {ports_line}\n  nginx-federation:\n    ports:\n"
        f"      - \"9443:8443\"\n")
    return OperatorContext(name="x", dir=tmp_path, env_path=tmp_path / ".env.operator", env=env or {})


def test_the_own_registry_is_the_port_the_compose_publishes_on_this_host(tmp_path, monkeypatch):
    monkeypatch.delenv("TP_OPERATOR_REGISTRY_URL", raising=False)
    assert _ctx(tmp_path, '"8750:8000"').registry_url == "http://127.0.0.1:8750"
    assert _ctx(tmp_path, '"172.17.0.1:8750:8000"').registry_url == "http://172.17.0.1:8750"
    assert _ctx(tmp_path, '"${REGISTRY_HTTP_PORT:-8000}:8000"').registry_url == "http://127.0.0.1:8000"
    assert _ctx(tmp_path, '"${REGISTRY_HTTP_PORT:-8000}:8000"',
                {"REGISTRY_HTTP_PORT": "8123"}).registry_url == "http://127.0.0.1:8123"
    monkeypatch.setenv("TP_OPERATOR_REGISTRY_URL", "https://registry.example.invalid/")
    assert _ctx(tmp_path, '"8750:8000"').registry_url == "https://registry.example.invalid"


@pytest.fixture
def stack(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    for var in ("CI", "GITHUB_ACTIONS", "GITLAB_CI", "TP_OPERATOR_JSON", "TP_OPERATOR_REMOTE_AUDIT",
                "TP_OPERATOR_REGISTRY_URL", "TP_OPERATOR_MAINFRAME_URL"):
        monkeypatch.delenv(var, raising=False)
    d = tmp_path / "cloud-op-x"
    d.mkdir()
    (d / "docker-compose.operator.yml").write_text('services:\n  registry:\n    ports:\n      - "8750:8000"\n')
    env = d / ".env.operator"
    env.write_text("REGISTRY_NAME=cloud-op-x\nCENTRAL_REGISTRY_URL=https://parent.example.invalid\n")
    asked = []
    real = httpx.Client

    def factory(*a, **kw):
        def handler(request):
            asked.append(str(request.url))
            return httpx.Response(200, json={"total": 0, "bundles": [], "id": "b1", "bundle_id": "b1"})
        kw["transport"] = httpx.MockTransport(handler)
        return real(*a, **kw)

    monkeypatch.setattr(bundle.httpx, "Client", factory)
    return env, asked


def test_bundle_list_asks_the_stacks_own_registry_not_the_parent(stack):
    env, asked = stack
    r = CliRunner().invoke(app, ["--config", str(env), "--json", "bundle", "list", "--api-key", "avreg_x"])
    assert r.exit_code == 0, r.output
    assert asked and all(u.startswith("http://127.0.0.1:8750/api/v1/bundles") for u in asked), asked


@pytest.mark.parametrize("argv", [["create", "--agent-did", "did:theprotocol:x"], ["restore", "{tpb}"],
                                  ["download", "b1"]])
def test_dry_run_makes_no_call(stack, tmp_path, argv):
    env, asked = stack
    tpb = tmp_path / "x.tpb"
    tpb.write_bytes(b"x")
    argv = [a.replace("{tpb}", str(tpb)) for a in argv]
    r = CliRunner().invoke(app, ["--config", str(env), "--dry-run", "bundle", *argv, "--api-key", "avreg_x"])
    assert r.exit_code == 0, r.output
    assert "DRY-RUN" in r.output and "127.0.0.1:8750" in r.output and asked == []
