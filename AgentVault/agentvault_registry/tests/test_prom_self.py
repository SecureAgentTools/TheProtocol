"""core/prom_self.py: an admin status route reads its OWN series in the shared Prometheus (§FESUITE, with agentvault2-bb;
2026-10-02). One Prometheus scrapes production and the sandbox alike, so an unscoped sum showed a sandbox console the
whole host's numbers (sbx-alpha's canary judge read 37.6% from Frame A's production paths)."""
import ast
import pathlib

import pytest

import agentvault_registry
from agentvault_registry.core.prom_self import sel, self_job

ROUTERS = pathlib.Path(agentvault_registry.__file__).resolve().parent / "routers"

# Each registry's own env (the two keys frame_slug reads), measured 2026-10-02 on every running registry container, and
# the job its scrape target carries (monitoring/prometheus.yml, /etc/prometheus/targets/*.json).
FLEET = [
    ({"TEG_LAYER_URL": "https://sbx-alpha-nginx-teg:8443", "REGISTRY_NAME": "Sandbox Alpha"}, "sbx-alpha-registry", "sbx-alpha-teg"),
    ({"TEG_LAYER_URL": "https://sbx-beta-nginx-teg:8443", "REGISTRY_NAME": "Sandbox Beta"}, "sbx-beta-registry", "sbx-beta-teg"),
    ({"TEG_LAYER_URL": "https://eu-nginx-teg:8443", "REGISTRY_NAME": "EU"}, "eu-registry", "eu-teg"),
    ({"TEG_LAYER_URL": "https://asia-nginx-teg:8443", "REGISTRY_NAME": "ASIA"}, "asia-registry", "asia-teg"),
    ({"TEG_LAYER_URL": "http://teg-layer:8080", "REGISTRY_NAME": "cloud-op-amsterdam"}, "amsterdam-registry", "amsterdam-teg"),
    ({"TEG_LAYER_URL": "http://teg-layer:8080", "REGISTRY_NAME": "cloud-op-sbxalphaop"}, "sbxalphaop-registry", "sbxalphaop-teg"),
    ({"REGISTRY_NAME": "Registry-A"}, "registry-a", "teg-layer-a"),
    ({}, "registry-a", "teg-layer-a"),
]


@pytest.mark.parametrize("env,registry_job,teg_job", FLEET)
def test_self_job_is_the_scrape_job_of_this_registry_and_of_its_tegs(env, registry_job, teg_job):
    assert self_job("registry", env) == registry_job
    assert self_job("teg", env) == teg_job


def test_a_deployment_that_names_its_jobs_otherwise_says_so():
    env = {"REGISTRY_NAME": "EU", "METRICS_SELF_JOB": "eu-registry-blue", "METRICS_SELF_TEG_JOB": "eu-teg-blue"}
    assert self_job("registry", env) == "eu-registry-blue"
    assert self_job("teg", env) == "eu-teg-blue"


def test_sel_builds_the_selector_with_the_job_first():
    env = {"REGISTRY_NAME": "EU"}
    assert sel("canary_transfer_total", env=env) == 'canary_transfer_total{job="eu-registry"}'
    assert sel("x_total", component="teg", env=env, outcome="ok") == 'x_total{job="eu-teg",outcome="ok"}'
    with pytest.raises(ValueError):
        self_job("store", env)


def _calls_sel(node: ast.AST) -> bool:
    return any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "sel" for c in ast.walk(node))


def unscoped_queries(src: str) -> list:
    """Every string that reaches _prom_instant without sel(): a literal argument, or a name assigned a plain string."""
    tree = ast.parse(src)
    passed = {n.args[1].id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
              and n.func.id == "_prom_instant" and len(n.args) >= 2 and isinstance(n.args[1], ast.Name)}
    bad = []
    for n in ast.walk(tree):
        value = None
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_prom_instant" and len(n.args) >= 2:
            value = n.args[1]
        elif isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) and n.targets[0].id in passed:
            value = n.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            bad.append(value.value)
        elif isinstance(value, ast.JoinedStr) and not _calls_sel(value):
            bad.append(ast.unparse(value))
    return bad


def test_every_admin_prometheus_query_reads_only_this_registrys_series():
    files = sorted(p for p in ROUTERS.glob("*.py") if "def _prom_instant" in p.read_text())
    assert len(files) >= 10, [p.name for p in files]
    offenders = {p.name: q for p in files for q in [unscoped_queries(p.read_text())] if q}
    assert offenders == {}, offenders


def test_the_gate_sees_an_unscoped_query():
    src = ("async def _prom_instant(c, q):\n    return []\n"
           "async def f(c):\n"
           "    a_q = 'sum(increase(x_total[24h]))'\n"
           "    b_q = f'sum(increase({sel(\"y_total\")}[24h]))'\n"
           "    await _prom_instant(c, a_q)\n"
           "    await _prom_instant(c, b_q)\n"
           "    await _prom_instant(c, 'z')\n")
    assert unscoped_queries(src) == ["sum(increase(x_total[24h]))", "z"]
