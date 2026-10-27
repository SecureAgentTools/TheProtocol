"""`health --strict` asks routes a registry serves (CB-287).

The ledger probe asked <parent>/api/v1/projections/supply-audit, an event-store path no registry serves (EU and ASIA
answer 404), so --strict was red against every frame. The registry's own public read of its ledger is
/api/v1/public/supply-invariant, which always answers 200 and says OK, BREACH or UNKNOWN: only OK is green. The parent
is a mock transport here.
"""
import sys
from pathlib import Path

import httpx
import pytest

pytest.importorskip("typer")
from typer.testing import CliRunner  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tp_operator import http_client  # noqa: E402
from tp_operator.main import app  # noqa: E402


def _parent(monkeypatch, ledger_status):
    asked = []

    def handler(request):
        asked.append(request.url.path)
        if request.url.path == "/api/v1/public/supply-invariant":
            return httpx.Response(200, json={"delta": 0.0 if ledger_status == "OK" else None, "status": ledger_status})
        if request.url.path in ("/health", "/api/v1/federation/info"):
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(404, json={"detail": "Not Found"})

    real = httpx.Client

    def factory(*a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        return real(*a, **kw)

    monkeypatch.setattr(http_client.httpx, "Client", factory)
    return asked


@pytest.fixture
def stack(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    for var in ("CI", "GITHUB_ACTIONS", "GITLAB_CI", "TP_OPERATOR_JSON", "TP_OPERATOR_MAINFRAME_URL",
                "TP_OPERATOR_REMOTE_AUDIT"):
        monkeypatch.delenv(var, raising=False)
    d = tmp_path / "cloud-op-x"
    d.mkdir()
    (d / "docker-compose.operator.yml").write_text("services: {}\n")
    env = d / ".env.operator"
    env.write_text("REGISTRY_NAME=cloud-op-x\nCENTRAL_REGISTRY_URL=https://parent.example.invalid\n")
    return env


def test_strict_is_green_against_a_parent_whose_ledger_reads_ok(stack, monkeypatch):
    asked = _parent(monkeypatch, "OK")
    r = CliRunner().invoke(app, ["--config", str(stack), "--no-color", "health", "--strict"])
    assert r.exit_code == 0, r.output
    assert "/api/v1/public/supply-invariant" in asked and "/api/v1/projections/supply-audit" not in asked


@pytest.mark.parametrize("ledger", ["BREACH", "UNKNOWN"])
def test_a_ledger_that_is_not_ok_is_red_although_the_route_answers_200(stack, monkeypatch, ledger):
    _parent(monkeypatch, ledger)
    r = CliRunner().invoke(app, ["--config", str(stack), "--no-color", "health", "--include-eventstore"])
    assert r.exit_code == 2 and f"fail ({ledger})" in r.output
