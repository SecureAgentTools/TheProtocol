"""§DEPS (2026-09-28, agentvault2-a4's review of the SPIRE 1.15.3 plan): `spire-server x509 mint -output json` changed shape.

Through 1.14 the CLI wrapped the one minted SVID in a one-element list; from 1.15.0 (spiffe/spire#6655, "Stop wrapping
objects in slices when printing") it prints the object itself. Measured on throwaway servers
(scratchpad/deps/spire_cli_compare.sh): 1.10.4 -> list, 1.15.3 -> dict, the same three keys. `agent_spire._mint_result`
is the ONE normaliser (the frame runner passes the CLI's stdout through untouched), so both shapes are pinned here, with
certificates made at test time (nothing secret is committed).
"""
from __future__ import annotations

import base64
import datetime as dt
import json

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from agentvault_registry.services import agent_spire

SID = "spiffe://probe.test/agent/did-theprotocol-probe"


def _mint_payload(hours=4):
    now = dt.datetime.now(dt.timezone.utc)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "probe CA")])
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(minutes=5))
          .not_valid_after(now + dt.timedelta(days=1)).add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
          .sign(ca_key, hashes.SHA256()))
    key = ec.generate_private_key(ec.SECP256R1())
    leaf = (x509.CertificateBuilder().subject_name(x509.Name([])).issuer_name(ca_name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - dt.timedelta(seconds=30))
            .not_valid_after(now + dt.timedelta(hours=hours))
            .add_extension(x509.SubjectAlternativeName([x509.UniformResourceIdentifier(SID)]), False)
            .sign(ca_key, hashes.SHA256()))
    b64 = lambda der: base64.b64encode(der).decode()
    return {
        "x509_svid": [b64(leaf.public_bytes(serialization.Encoding.DER))],
        "private_key": b64(key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                                             serialization.NoEncryption())),
        "root_cas": [b64(ca.public_bytes(serialization.Encoding.DER))],
    }


@pytest.mark.parametrize("shape", ["list_1_10", "object_1_15"])
def test_both_cli_shapes_give_the_same_credential(shape):
    item = _mint_payload()
    stdout = json.dumps([item] if shape == "list_1_10" else item)
    out = agent_spire._mint_result("did:theprotocol:probe", SID, 4 * 3600, stdout)
    assert out["spiffe_id"] == SID
    assert out["svid_pem"].count("BEGIN CERTIFICATE") == 1
    assert out["bundle_pem"].count("BEGIN CERTIFICATE") == 1
    leaf = x509.load_pem_x509_certificate(out["svid_pem"].encode())
    # the key the caller receives is the leaf's own (read as a key, never matched as text)
    key = serialization.load_pem_private_key(out["key_pem"].encode(), password=None)
    assert key.public_key().public_numbers() == leaf.public_key().public_numbers()
    san = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert SID in san.get_values_for_type(x509.UniformResourceIdentifier)
    assert out["expires_at"] and out["ttl_capped_by_ca"] is False


def test_a_shape_neither_version_prints_is_refused():
    with pytest.raises(RuntimeError, match="Unparseable x509 mint output"):
        agent_spire._mint_result("did:theprotocol:probe", SID, 3600, json.dumps({"svid": "nope"}))
    with pytest.raises(RuntimeError, match="Unparseable x509 mint output"):
        agent_spire._mint_result("did:theprotocol:probe", SID, 3600, "[]")
