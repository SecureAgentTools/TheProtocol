"""§FRAMEKIT P3.1 (2026-09-12) — the driver writes PROMETHEUS_URL / VICTORIA_METRICS_URL from the sidecar
manifest under --wire-prod, and from nowhere else. Pinned on the AST: a claim that shipped before its code
did is this driver's own history (findings row 178), so the call site is asserted, not the docstring."""
import ast
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DRIVER = os.path.join(os.path.dirname(HERE), "standup_driver.py")


def _calls_in(fn_name):
    tree = ast.parse(open(DRIVER).read())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == fn_name)
    out = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name):
            out.append(f"{n.func.value.id}.{n.func.attr}")
    return out


def test_mutate_rendered_writes_the_two_addresses_from_the_manifest_only():
    calls = _calls_in("mutate_rendered")
    assert "sidecars.metrics_env_lines" in calls and "sidecars.load" in calls
    src = open(DRIVER).read()
    # no literal observability address anywhere in the driver: the manifest is the one source
    assert "prometheus:9090" not in src and "victoriametrics:8428" not in src
    # the write is gated on the frame being wired into the host's Prometheus (a frame with no sidecars keeps the honest
    # "not configured"). §NIGHTPROV: the gate is the prometheus piece, which --wire-prod includes and --wire-only sni,bundle
    # (the nightly sandbox pair) does not
    fn_src = src[src.index("def mutate_rendered("):src.index("def ", src.index("def mutate_rendered(") + 10)]
    assert 'if wires(args, "prometheus"):' in fn_src
