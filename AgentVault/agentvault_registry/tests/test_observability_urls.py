"""§FRAMEKIT P3.1 — one reader for PROMETHEUS_URL; an empty value is unset, never a dial of ""."""
import ast
import os
import pathlib

from agentvault_registry.core.observability_urls import DEFAULT_PROMETHEUS_URL, prometheus_url

ROUTERS = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry" / "routers"


def test_env_wins_and_empty_means_unset(monkeypatch):
    monkeypatch.delenv("PROMETHEUS_URL", raising=False)
    assert prometheus_url() == DEFAULT_PROMETHEUS_URL
    monkeypatch.setenv("PROMETHEUS_URL", "")
    assert prometheus_url() == DEFAULT_PROMETHEUS_URL          # an env_file line `PROMETHEUS_URL=` is SET but empty
    monkeypatch.setenv("PROMETHEUS_URL", "http://tp-sidecars-prometheus:9090/")
    assert prometheus_url() == "http://tp-sidecars-prometheus:9090"


def test_no_router_reads_the_variable_with_its_own_default():
    """Twelve routers each carried a literal default (one of them a different one). The AST is the gate: no
    call `os.environ.get("PROMETHEUS_URL", ...)` / `os.getenv("PROMETHEUS_URL", ...)` survives in routers/."""
    offenders = []
    for f in sorted(ROUTERS.glob("*.py")):
        tree = ast.parse(f.read_text())
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value == "PROMETHEUS_URL":
                fn = n.func
                name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                if name in ("get", "getenv"):
                    offenders.append(f"{f.name}:{n.lineno}")
    assert offenders == [], offenders
    users = [f.name for f in ROUTERS.glob("*.py") if "prometheus_url()" in f.read_text()]
    assert len(users) >= 12 and "public_status.py" in users
