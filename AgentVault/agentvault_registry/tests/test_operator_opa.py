"""§OPA (2026-10-06, agentvault2-09): the operator's own OPA, through the provisioning flow.

His words: "please roll out and enable opa for the whole production cluster", then, on hearing the operators had none,
"we need this whole ... provisioner fix". The frames carried an OPA since §SOVKIT (the frame template's kit); no
operator did, so every operator registry's OPA code stayed dark. host_work now materialises the operator's OPA the way
it materialises the database's TLS: an override from the live templates, the policies, and an entry registered at
stack time, never federated, before anything starts. These pin that shape, and the one property the override cannot
show on its own: the names the registry dials and the names the certificate carries are the same names.
"""
from __future__ import annotations

import importlib.util
import os
import pathlib
import re
import sys
import types

import pytest

_HERE = pathlib.Path(__file__).resolve()
_SRC = pathlib.Path(os.environ["OPDIST_SRC"]) if os.environ.get("OPDIST_SRC") else (
    _HERE.parents[1] / "src" / "agentvault_registry")
# The real templates live in the stack, beside this checkout on the box and nowhere in CI's checkout.
_TEMPLATES = pathlib.Path(os.environ.get("OPA_TEMPLATES_DIR")
                          or "/opt/theprotocol/stack/Agentvault2/scripts/distribution/nginx-templates")


def _hw():
    spec = importlib.util.spec_from_file_location("_opa_hw", _SRC / "host_work.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _prov():
    spec = importlib.util.spec_from_file_location("_opa_prov", _SRC / "services" / "operator_provisioner.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _attestation_cert(stack_dir):
    """A real self-signed cert, so the fingerprint is derived the way the provisioner derived the original."""
    import datetime as _dt
    import hashlib as _hl
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "operator-attestation")])
    now = _dt.datetime.now(_dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - _dt.timedelta(minutes=5))
            .not_valid_after(now + _dt.timedelta(days=1)).sign(key, hashes.SHA256()))
    d = pathlib.Path(stack_dir) / "spire"
    d.mkdir(parents=True, exist_ok=True)
    (d / "agent-attestation.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return _hl.sha1(cert.public_bytes(serialization.Encoding.DER)).hexdigest()


def _templates(tmp_path, mod, policies=6, override="services: {}\n"):
    tmpl = tmp_path / "templates"
    (tmpl / "opa" / "policies").mkdir(parents=True)
    (tmpl / mod.OPA_OVERRIDE).write_text(override, encoding="utf-8")
    for i in range(policies):
        (tmpl / "opa" / "policies" / f"p{i}.rego").write_text(f"package p{i}\n", encoding="utf-8")
    (tmpl / "opa" / "system_authz.rego.tmpl").write_text(
        'package system.authz\nids := {"{{TRUST_DOMAIN}}", "/operator/{{OPERATOR}}/svid-writer"}\n', encoding="utf-8")
    return tmpl


def test_without_the_override_the_operator_runs_no_opa(tmp_path, monkeypatch):
    """Four running frames share the live templates. A frame whose templates carry no override must provision
    exactly as before: no entry, no policies, and a note saying so."""
    mod = _hw()
    called = []
    monkeypatch.setattr(mod, "_load_provisioner", lambda: types.SimpleNamespace(
        register_operator_opa_entry=lambda *a, **k: called.append(a) or 1))
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", "eu.theprotocol.cloud")
    stack = tmp_path / "cloud-op-x"
    stack.mkdir()
    (tmp_path / "templates").mkdir()
    notes = []
    out = mod._opa_steps({"nginx_templates_dir": str(tmp_path / "templates")}, str(stack), "x", notes)
    assert out == {"opa": False} and called == []
    assert not (stack / "opa").exists() and not (stack / mod.OPA_OVERRIDE).exists()
    assert "no override" in notes[0]


def test_with_the_override_the_entry_is_registered_and_the_policies_rendered(tmp_path, monkeypatch):
    mod = _hw()
    seen = {}
    monkeypatch.setattr(mod, "_load_provisioner", lambda: types.SimpleNamespace(
        register_operator_opa_entry=lambda name, fp, dns: seen.update(name=name, fp=fp, dns=dns) or 1))
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", "eu.theprotocol.cloud")
    stack = tmp_path / "cloud-op-amsterdam"
    stack.mkdir()
    fp = _attestation_cert(str(stack))
    tmpl = _templates(tmp_path, mod, policies=7)
    notes = []
    out = mod._opa_steps({"nginx_templates_dir": str(tmpl)}, str(stack), "amsterdam", notes)
    assert out == {"opa": True, "opa_policies": 8}
    assert seen == {"name": "amsterdam", "fp": fp, "dns": "cloud-op-amsterdam-opa"}, \
        "the entry is the certificate's own fingerprint, and its SAN the host OPA_URL dials"
    assert (stack / mod.OPA_OVERRIDE).exists(), "materialised from the LIVE templates, not from the bundle"
    pol = stack / "opa" / "policies"
    assert sorted(p.name for p in pol.iterdir()) == sorted([f"p{i}.rego" for i in range(7)] + ["system_authz.rego"])
    authz = (pol / "system_authz.rego").read_text(encoding="utf-8")
    assert "eu.theprotocol.cloud" in authz and "/operator/amsterdam/svid-writer" in authz and "{{" not in authz
    # OPA runs as uid 1000 behind a read-only bind; this tree's umask would write 750/640
    assert oct(pol.stat().st_mode)[-3:] == "755" and oct((stack / "opa").stat().st_mode)[-3:] == "755"
    assert {oct(p.stat().st_mode)[-3:] for p in pol.iterdir()} == {"644"}


def test_an_entry_that_did_not_register_refuses_before_up(tmp_path, monkeypatch):
    """An override without its entry is a writer waiting forever for a certificate nobody issued, and compose
    blocking on it to the job's ceiling. Refused instead."""
    mod = _hw()
    monkeypatch.setattr(mod, "_load_provisioner", lambda: types.SimpleNamespace(
        register_operator_opa_entry=lambda *a, **k: 0))
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", "eu.theprotocol.cloud")
    stack = tmp_path / "cloud-op-y"
    stack.mkdir()
    _attestation_cert(str(stack))
    tmpl = _templates(tmp_path, mod)
    with pytest.raises((mod.HostWorkRefused, mod.HostWorkFailed)) as e:
        mod._opa_steps({"nginx_templates_dir": str(tmpl)}, str(stack), "y", [])
    assert "wait" in str(e.value) and "Nothing was brought up" in str(e.value)


def test_too_few_policies_are_refused(tmp_path, monkeypatch):
    """An OPA with an empty or thin directory answers `undefined`: allow in shadow, deny in enforce. The floor is
    the frame kit's."""
    mod = _hw()
    monkeypatch.setattr(mod, "_load_provisioner", lambda: types.SimpleNamespace(
        register_operator_opa_entry=lambda *a, **k: 1))
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", "eu.theprotocol.cloud")
    stack = tmp_path / "cloud-op-z"
    stack.mkdir()
    _attestation_cert(str(stack))
    tmpl = _templates(tmp_path, mod, policies=mod.OPA_POLICY_FLOOR - 1)
    with pytest.raises((mod.HostWorkRefused, mod.HostWorkFailed)) as e:
        mod._opa_steps({"nginx_templates_dir": str(tmpl)}, str(stack), "z", [])
    assert "OPA policies" in str(e.value)


def test_no_trust_domain_is_refused_rather_than_defaulted(tmp_path, monkeypatch):
    """Every default in the provisioner names Frame A. A module bound to the wrong trust domain authorizes nobody
    (or somebody else's frame), so an unknown one refuses."""
    mod = _hw()
    monkeypatch.setattr(mod, "_load_provisioner", lambda: types.SimpleNamespace(
        register_operator_opa_entry=lambda *a, **k: 1))
    monkeypatch.delenv("SPIRE_TRUST_DOMAIN", raising=False)
    stack = tmp_path / "cloud-op-q"
    stack.mkdir()
    _attestation_cert(str(stack))
    tmpl = _templates(tmp_path, mod)
    with pytest.raises((mod.HostWorkRefused, mod.HostWorkFailed)) as e:
        mod._opa_steps({"nginx_templates_dir": str(tmpl)}, str(stack), "q", [])
    assert "trust domain" in str(e.value)


def test_a_spec_naming_another_trust_domain_is_refused(tmp_path, monkeypatch):
    mod = _hw()
    monkeypatch.setattr(mod, "_load_provisioner", lambda: types.SimpleNamespace(
        register_operator_opa_entry=lambda *a, **k: 1))
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", "asia.theprotocol.cloud")
    stack = tmp_path / "cloud-op-r"
    stack.mkdir()
    _attestation_cert(str(stack))
    tmpl = _templates(tmp_path, mod)
    with pytest.raises(mod.HostWorkRefused):
        mod._opa_steps({"nginx_templates_dir": str(tmpl), "compose": {"spire_trust_domain": "eu.theprotocol.cloud"}},
                       str(stack), "r", [])


def test_the_env_carries_the_opa_values_only_with_the_override(tmp_path, monkeypatch):
    """The values live in .env.operator, the registry's env_file, so a later recreate keeps them whichever compose
    files a roll passes. And the override's own interpolations must all be set, or compose substitutes blanks."""
    mod = _hw()
    monkeypatch.chdir(tmp_path)
    stack = tmp_path / "cloud-op-lisbon"
    stack.mkdir()
    (stack / "docker-compose.operator.yml").write_text("services:\n  registry:\n    image: x\n", encoding="utf-8")
    env_path = mod._write_operator_env({"env": {}, "operator_secrets": {}}, str(stack), "lisbon", [])
    assert "OPA_" not in pathlib.Path(env_path).read_text(encoding="utf-8"), "no override, no OPA values"

    (stack / mod.OPA_OVERRIDE).write_text(
        "services:\n  opa:\n    image: ${OPERATOR_OPA_IMAGE:?written by the step}\n"
        "    command: [\"--log-level\", \"${OPERATOR_OPA_LOG_LEVEL:?x}\", \"${OPERATOR_OPA_TLS_REFRESH:?y}\"]\n",
        encoding="utf-8")
    (stack / ".env.operator").unlink()
    notes = []
    env_path = mod._write_operator_env({"env": {}, "operator_secrets": {}}, str(stack), "lisbon", notes)
    kv = dict(ln.split("=", 1) for ln in pathlib.Path(env_path).read_text(encoding="utf-8").splitlines()
              if "=" in ln and not ln.startswith("#"))
    assert kv["OPA_ENABLED"] == "true" and kv["OPA_ENFORCE"] == "false", "shadow: OPA asked, Python decides"
    assert kv["OPA_URL"] == "https://cloud-op-lisbon-opa:8181"
    assert kv["OPERATOR_OPA_IMAGE"] == mod.OPA_IMAGE
    assert oct(pathlib.Path(env_path).stat().st_mode)[-3:] == "600"


def test_a_required_variable_is_one_the_env_must_set():
    """`${VAR:?message}` has no default by definition. Read only as `${VAR}`, the OPA override's three values would
    reach `up` unchecked and compose would refuse the project there, after the stack dir was written."""
    mod = _hw()
    text = ("services:\n  opa:\n    image: ${A_REQUIRED:?set it}\n    command: [\"${B_REQUIRED?also}\", \"${PLAIN}\"]\n"
            "    environment:\n      C: ${HAS_A_DEFAULT:-x}\n      D: ${ALSO_DEFAULTED-y}\n")
    assert mod._compose_interpolations(text) == {"A_REQUIRED", "B_REQUIRED", "PLAIN"}


def test_a_value_already_set_wins(tmp_path):
    """The step fills; it never overrides. A person who set OPA_ENFORCE, or a spec that carried it, keeps it."""
    mod = _hw()
    env = tmp_path / ".env.operator"
    env.write_text("OPA_ENFORCE=true\nOTHER=1\n", encoding="utf-8")
    wrote = mod.append_opa_env(str(env), "x", [])
    assert "OPA_ENFORCE" not in wrote and "OPA_ENABLED" in wrote
    assert env.read_text(encoding="utf-8").count("OPA_ENFORCE=") == 1
    assert mod.append_opa_env(str(env), "x", []) == [], "a second run writes nothing"


# ── the provisioner's half ───────────────────────────────────────────────────────────────────────────────────────
class _FakeSpire:
    def __init__(self, exit_code=0, stderr=b""):
        self.cmds, self.exit_code, self.stderr = [], exit_code, stderr

    def exec_run(self, cmd, demux=True):
        self.cmds.append(list(cmd))
        return self.exit_code, (b"", self.stderr)


def _with_fake_docker(monkeypatch, spire):
    client = types.SimpleNamespace(containers=types.SimpleNamespace(get=lambda name: spire))
    monkeypatch.setitem(sys.modules, "docker", types.SimpleNamespace(from_env=lambda: client))


def test_the_opa_entry_is_never_federated_and_carries_the_name_the_registry_dials(monkeypatch):
    """A federated OPA identity would put every peer trust domain's root in the bundle this OPA verifies its callers
    against. The frame federates; this entry must not, whatever SPIRE_FEDERATE_WITH says."""
    prov = _prov()
    spire = _FakeSpire()
    _with_fake_docker(monkeypatch, spire)
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", "eu.theprotocol.cloud")
    monkeypatch.setenv("SPIRE_CONTAINER", "eu-spire-server")
    monkeypatch.setenv("SPIRE_FEDERATE_WITH", "asia.theprotocol.cloud")
    assert prov.register_operator_opa_entry("amsterdam", "ab" * 20, "cloud-op-amsterdam-opa") == 1
    cmd = spire.cmds[0]
    assert cmd[cmd.index("-spiffeID") + 1] == "spiffe://eu.theprotocol.cloud/operator/amsterdam/opa"
    assert cmd[cmd.index("-parentID") + 1] == f"spiffe://eu.theprotocol.cloud/spire/agent/x509pop/{'ab' * 20}"
    assert cmd[cmd.index("-selector") + 1] == "docker:label:com.agentvault.service:svid-writer-opa-operator"
    assert cmd[cmd.index("-dns") + 1] == "cloud-op-amsterdam-opa"
    assert "-federatesWith" not in cmd


def test_the_data_entry_keeps_its_exact_shape(monkeypatch):
    """The shared helper must not move the data entry by one argument."""
    prov = _prov()
    spire = _FakeSpire()
    _with_fake_docker(monkeypatch, spire)
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", "eu.theprotocol.cloud")
    assert prov.register_operator_data_entry("lisbon", "cd" * 20, "cloud-op-lisbon-db") == 1
    assert spire.cmds[0] == [
        prov.SPIRE_BINARY, "entry", "create",
        "-parentID", f"spiffe://eu.theprotocol.cloud/spire/agent/x509pop/{'cd' * 20}",
        "-spiffeID", "spiffe://eu.theprotocol.cloud/operator/lisbon/data",
        "-selector", "docker:label:com.agentvault.service:svid-writer-data-operator",
        "-dns", "cloud-op-lisbon-db",
        "-x509SVIDTTL", "14400",
    ]


def test_an_entry_already_there_counts_and_a_failure_does_not(monkeypatch):
    prov = _prov()
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", "eu.theprotocol.cloud")
    _with_fake_docker(monkeypatch, _FakeSpire(exit_code=1, stderr=b"rpc error: code = AlreadyExists"))
    assert prov.register_operator_opa_entry("x", "ef" * 20, "cloud-op-x-opa") == 1
    _with_fake_docker(monkeypatch, _FakeSpire(exit_code=1, stderr=b"rpc error: code = InvalidArgument"))
    assert prov.register_operator_opa_entry("x", "ef" * 20, "cloud-op-x-opa") == 0
    with pytest.raises(ValueError):
        prov.register_operator_opa_entry("x", "", "cloud-op-x-opa")


# ── the real templates (the stack's), where this checkout can see them ─────────────────────────────────────────────
@pytest.mark.skipif(not (_TEMPLATES / "docker-compose.operator.opa.yml").exists(),
                    reason="the stack's operator templates are not beside this checkout")
def test_the_real_override_agrees_with_the_provisioner():
    """Three names have to meet across three files: the label the writer wears and the selector the entry
    registers, the container the override names and the host OPA_URL dials (the entry's SAN), and every variable the
    override interpolates without a default and the values the step writes."""
    mod = _hw()
    text = (_TEMPLATES / mod.OPA_OVERRIDE).read_text(encoding="utf-8")
    assert "com.agentvault.service=svid-writer-opa-operator" in text
    assert re.search(r"container_name: \$\{REGISTRY_NAME:-operator\}-opa\n", text), \
        "OPA_URL dials cloud-op-<slug>-opa and REGISTRY_NAME is cloud-op-<slug>"
    needed = mod._compose_interpolations(text)
    assert needed == {"OPERATOR_OPA_IMAGE", "OPERATOR_OPA_LOG_LEVEL", "OPERATOR_OPA_TLS_REFRESH"}, needed
    assert needed <= set(mod.opa_env_values("x")), "every value the override requires is one the step writes"
    assert "./opa/policies:/policies:ro" in text
    policies = list((_TEMPLATES / "opa" / "policies").glob("*.rego"))
    assert len(policies) >= mod.OPA_POLICY_FLOOR
    authz = (_TEMPLATES / "opa" / "system_authz.rego.tmpl").read_text(encoding="utf-8")
    assert "{{TRUST_DOMAIN}}" in authz and "/operator/{{OPERATOR}}/svid-writer" in authz
    assert set(re.findall(r"\{\{([A-Z_]+)\}\}", authz)) == {"TRUST_DOMAIN", "OPERATOR"}, \
        "render_opa_policies fills exactly these two"
