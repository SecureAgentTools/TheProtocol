"""One operator package in the kit (CB-112, CB-227).

scripts/distribution/docker-compose.operator.yml said in its own comment that it was DIVERGENT and older than the copy
a frame's bundle ships (nginx-templates): no nginx-teg, uvicorn trusting every forwarded-for address. build.sh and
operator-setup.sh's federated mode used it, and onboard-operator.sh shipped nginx/nginx-federation-operator.conf, a
federation sidecar that forwarded the peer's certificate without the X-Registry-Proxy-Auth marker, so a registry deployed
from it counted no forwarded certificate and its federation mTLS authenticated nobody (a tracked sample of its output,
operator-package/fed-test, carried that conf too). All are retired; the scripts that package an operator copy the
bundle's files.
"""
import re
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]


def test_the_kits_only_operator_compose_is_the_bundles():
    assert not (HERE / "docker-compose.operator.yml").exists(), "an older operator compose sits beside the bundle's"
    assert (HERE / "nginx-templates" / "docker-compose.operator.yml").exists()


def test_no_terminator_in_the_kit_forwards_a_certificate_without_its_marker():
    confs = [p for p in HERE.rglob("*.conf") if "X-SSL-Client-Cert" in p.read_text(errors="replace")]
    assert confs, "the rule cannot see its subject"
    bare = [str(p.relative_to(HERE)) for p in confs
            if not re.search(r"proxy_set_header\s+X-(Registry|TEG)-Proxy-Auth\b", p.read_text(errors="replace"))]
    assert not bare, f"forward the peer's certificate with no proxy marker: {bare}"


def test_the_packaging_scripts_copy_files_that_exist():
    build = (HERE / "build.sh").read_text()
    for rel in re.findall(r'cp "\$\{SCRIPT_DIR\}/([^"]+)"', build):
        assert (HERE / rel).exists(), f"build.sh copies {rel}, which is not in the kit"
    onboard = (HERE / "onboard-operator.sh").read_text()
    assert not re.search(r'(?m)^\s*cp .*nginx-federation-operator\.conf', onboard)
    for group in re.findall(r'for f in ([^;]+); do\n\s+cp "\$\{TEMPLATES\}/\$\{f\}"', onboard):
        for name in group.split():
            assert (HERE / "nginx-templates" / name).exists(), f"onboard-operator.sh copies {name}, which is missing"
    setup = (HERE / "operator-setup.sh").read_text()
    assert not re.search(r'(?m)^\s*COMPOSE="docker-compose\.operator\.yml"', setup), "the federated mode runs the old file"
