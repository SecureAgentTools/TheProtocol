"""§MTLSHOPS (a) (2026-09-15, agentvault2-85's guard): the host auditor carries no client certificate.

tls_client.live_read_plan reads a keyless https extra slot with the auditor's own certificate when one is configured: that
is the kit auditor's slot, whose store gateway verifies the certificate. The rule must never widen to the host auditor
unnoticed, because every keyless https extra slot on the host would then quietly present the host's certificate. So the
host auditor-agent service sets no AUDITOR_TLS_* and mounts nothing certificate-shaped, and its .env (read by variable NAME
only) names no AUDITOR_TLS_*.
A guard: it passes on the base and on the branch; the red copies (a compose that adds AUDITOR_TLS_CERT, one that mounts
/certs) must fail it. HOST_AUDITOR_COMPOSE points the test at another compose file.
"""
import os
import re

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPOSE = os.getenv("HOST_AUDITOR_COMPOSE") or os.path.join(HERE, "docker-compose.yml")
SERVICE = "auditor-agent"
CERT_SHAPED = re.compile(r"(^|[/_.-])(certs?|svid|spire|tls|pki)([/_.:-]|$)|\.(pem|key|crt)(:|$)", re.I)


def _service_block(text):
    m = re.search(rf"^  {re.escape(SERVICE)}:\n((?:(?:    .*)?\n)+)", text, re.M)
    assert m, f"no {SERVICE} service in {COMPOSE}"
    return m.group(1)


def test_the_host_auditor_service_sets_no_client_certificate_and_mounts_none():
    block = _service_block(open(COMPOSE).read())
    assert "AUDITOR_TLS_" not in block, "the host auditor must not configure a client certificate"
    mounts = [m.split(":")[0:2] for m in re.findall(r"^\s+- \"?([^\s#\"]+:[^\s#\"]+)\"?\s*$", block, re.M)]
    shaped = [":".join(m) for m in mounts if any(CERT_SHAPED.search(part) for part in m)]
    assert shaped == [], f"certificate-shaped mounts on the host auditor: {shaped}"


def test_the_host_auditor_env_file_names_no_client_certificate():
    env = os.path.join(os.path.dirname(COMPOSE), ".env")
    if not os.path.exists(env):
        pytest.skip(f"no {env} in this checkout (gitignored); the compose test above still runs")
    names = [line.split("=", 1)[0].strip() for line in open(env) if "=" in line and not line.lstrip().startswith("#")]
    assert not [n for n in names if n.startswith("AUDITOR_TLS_")]
