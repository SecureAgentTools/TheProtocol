"""§RELEASECHANNEL (2026-09-21): the CLI's reader of the signed release channel carries the registry's rules.

The vectors here are the registry's (AgentVault tests/test_release_channel.py): a document verifies only with the key
it was signed with and every alteration is refused; kit versions order final > rc > beta > alpha; an operator's
VERSION line is compared like with like (a kit version against release versions, a software version string against
registry_software_version); the local version is read from VERSION, else from the env's VERSION= line.
"""
import base64
import json
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tp_operator import release_channel as rc  # noqa: E402


def _keypair():
    key = Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return key, base64.b64encode(pub).decode()


def _signed(key, doc):
    body = {k: v for k, v in doc.items() if k != "signature"}
    pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    sig = key.sign(rc.canonical(body))
    body["signature"] = {"alg": "Ed25519", "kid": rc.kid_of(pub), "sig": base64.b64encode(sig).decode()}
    return body


def _rel(version, kind="stable", sw="xV0416"):
    return {"version": version, "kind": kind, "released_at": "2026-09-21T08:00:00Z", "registry_software_version": sw}


def _doc(*rels):
    return {"schema": rc.SCHEMA, "generated_at": "2026-09-21T08:00:00Z", "version": rels[0]["version"], "releases": list(rels)}


def test_verify_and_tamper():
    key, pub = _keypair()
    signed = _signed(key, _doc(_rel("1.0.0-beta.11")))
    assert rc.verify(signed, pub) == (True, "ok")
    assert rc.verify(signed)[0] is False                     # the baked key did not sign it
    tampered = json.loads(json.dumps(signed)); tampered["releases"][0]["kind"] = "security"
    assert rc.verify(tampered, pub)[0] is False
    assert rc.verify({k: v for k, v in signed.items() if k != "signature"}, pub)[1] == "unsigned"
    assert "kind" in rc.verify(_signed(key, _doc(_rel("1.0.0-beta.11", kind="nightly"))), pub)[1]


def test_version_rules():
    order = ["1.0.0-alpha.3", "1.0.0-beta.9", "1.0.0-beta.10", "1.0.0-rc.1", "1.0.0", "1.0.1"]
    parsed = [rc.parse_kit_version(v) for v in order]
    assert parsed == sorted(parsed) and None not in parsed
    assert rc.parse_software_version("MoreCompliantThenYourWholeComplianceFrameworkV0415") == 415
    assert rc.running_from_version_string("1.0.0-beta.10") == {"kit_version": "1.0.0-beta.10", "software_version": None}
    assert rc.running_from_version_string("MoreCompliantThenYourWholeComplianceFrameworkV0415")["kit_version"] is None
    doc = _doc(_rel("1.0.0-beta.12", "stable"), _rel("1.0.0-beta.11", "hotfix"), _rel("1.0.0-beta.10"))
    v = rc.assess(doc, rc.running_from_version_string("1.0.0-beta.10"))
    assert [r["version"] for r in v["newer"]] == ["1.0.0-beta.12", "1.0.0-beta.11"] and v["kind"] == "hotfix"
    v2 = rc.assess(doc, rc.running_from_version_string("MoreCompliantThenYourWholeComplianceFrameworkV0416"))
    assert v2["update_available"] is False and v2["comparable"] is True
    assert rc.find_release(doc, "1.0.0-beta.11")["kind"] == "hotfix" and rc.find_release(doc, "nope") is None


def test_local_version_from_file_then_env(tmp_path):
    pytest.importorskip("typer")
    from tp_operator.commands.update import _read_local_version
    assert _read_local_version(tmp_path) is None
    (tmp_path / ".env.operator").write_text("FOO=1\nVERSION=MoreCompliantThenYourWholeComplianceFrameworkV0415\n")
    assert _read_local_version(tmp_path) == "MoreCompliantThenYourWholeComplianceFrameworkV0415"
    (tmp_path / "VERSION").write_text("1.0.0-beta.11\n")
    assert _read_local_version(tmp_path) == "1.0.0-beta.11"
