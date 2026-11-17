"""V0667 D7 (order gwo_0f317438b7dfc6dfacd3e9b7): the offline verifier of an organization's signed release report and of a signed change record.

The document is the registry's envelope (AgentVault services/distribution_report): the report, its sha256 digest, and an EdDSA signature of the registry's card key over
{registry_spiffe_id, kind, subject, digest}. It is checked with the registry's published keys (/.well-known/registry-jwks.json) and nothing else, no network. ONE changed byte anywhere in the
report fails it; nothing else in the envelope can be re-pointed without failing the signature. tests/fixtures/distribution_report_golden.json is byte-identical to AgentVault's
tests/fixtures/distribution_report_golden.json, made by the registry's own signer with a fixed test key: this file proves the SDK reads what the registry writes.
"""
import base64
import copy
import hashlib
import json
import pathlib

import pytest

pytest.importorskip("cryptography")

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from theprotocol.registry import verify_distribution_envelope
from theprotocol.registry import distribution_report as dr

GOLDEN = json.loads((pathlib.Path(__file__).parent / "fixtures" / "distribution_report_golden.json").read_text())
GOLDEN_SHA256 = hashlib.sha256((pathlib.Path(__file__).parent / "fixtures" / "distribution_report_golden.json").read_bytes()).hexdigest()


def _golden():
    return copy.deepcopy(GOLDEN["envelope"]), copy.deepcopy(GOLDEN["jwks"])


def _canonical(doc) -> bytes:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _signed(report, *, kind="distribution.release.report", subject="V0666_x", spiffe="spiffe://t.test/registry/t", seq=1):
    """An envelope signed here with a fresh key, by the documented convention (not the registry's code)."""
    priv = Ed25519PrivateKey.generate()
    raw = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    jwk = {"kty": "OKP", "crv": "Ed25519", "x": base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii"), "alg": "EdDSA", "kid": f"{spiffe}#{seq}", "use": "sig"}
    env = {"envelope_version": 1, "registry_spiffe_id": spiffe, "kind": kind, "subject": subject, "digest": hashlib.sha256(_canonical(report)).hexdigest(), "report": report}
    sig = priv.sign(_canonical({p: env[p] for p in dr.SIGNED_PATHS}))
    env["signature"] = {"alg": "EdDSA", "kid": f"{spiffe}#{seq}", "jwks_url": "/.well-known/registry-jwks.json", "signed_canonical": list(dr.SIGNED_PATHS),
                        "value": base64.urlsafe_b64encode(sig).rstrip(b"=").decode("ascii")}
    return env, {"keys": [jwk]}


def test_the_registrys_own_golden_envelope_verifies():
    env, jwks = _golden()
    r = verify_distribution_envelope(env, jwks)
    assert r.ok is True and r.reason is None
    assert (r.kind, r.subject) == ("distribution.release.report", "V0666_golden") and r.changes == 2


def test_the_golden_file_is_the_one_the_registry_pins():
    assert GOLDEN_SHA256 == hashlib.sha256(json.dumps(GOLDEN, indent=2, sort_keys=True).encode() + b"\n").hexdigest()


def test_one_changed_byte_anywhere_in_the_report_fails_the_digest():
    env, jwks = _golden()
    # every string and number of the report, one character or one unit changed, one at a time
    def leaves(node, path=()):
        if isinstance(node, dict):
            for k, v in node.items():
                yield from leaves(v, path + (k,))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                yield from leaves(v, path + (i,))
        elif isinstance(node, (str, int, float, bool)) or node is None:
            yield path, node
    n = 0
    for path, value in leaves(env["report"]):
        bad = copy.deepcopy(env)
        cur = bad["report"]
        for p in path[:-1]:
            cur = cur[p]
        cur[path[-1]] = (not value) if isinstance(value, bool) else (value + 1) if isinstance(value, (int, float)) else "x" if value is None else (value[:-1] + chr(ord(value[-1]) ^ 1)) if value else "x"
        r = verify_distribution_envelope(bad, jwks)
        assert r.ok is False and r.reason == ("kind" if path == ("kind",) else "digest"), (path, r)       # the report's own kind is checked against the envelope's first
        n += 1
    assert n > 60, "the whole report was walked"


def test_a_report_that_is_missing_or_added_to_fails_too():
    env, jwks = _golden()
    for mutate in (lambda e: e["report"].pop("protected_set"), lambda e: e["report"].update(extra=1), lambda e: e["report"]["changes"].pop(), lambda e: e["report"]["changes"].append({})):
        bad = copy.deepcopy(env)
        mutate(bad)
        assert verify_distribution_envelope(bad, jwks).reason == "digest"


def test_the_digest_and_the_signed_fields_cannot_be_re_pointed():
    env, jwks = _golden()
    for field, value in (("subject", "V0666_other"), ("kind", "distribution.change.record"), ("registry_spiffe_id", "spiffe://golden.test/registry/other")):
        bad = copy.deepcopy(env)
        bad[field] = value
        assert verify_distribution_envelope(bad, jwks).reason in ("signature", "kind"), field
    bad = copy.deepcopy(env)
    other = copy.deepcopy(env["report"])
    other["release"] = "V0666_other"
    bad["report"], bad["digest"] = other, hashlib.sha256(_canonical(other)).hexdigest()       # a re-made digest over an altered report: the signature no longer matches
    assert verify_distribution_envelope(bad, jwks).reason == "signature"
    bad = copy.deepcopy(env)
    bad["signature"]["value"] = bad["signature"]["value"][:-3] + ("AAA" if not bad["signature"]["value"].endswith("AAA") else "BBB")
    assert verify_distribution_envelope(bad, jwks).reason == "signature"


def test_the_signed_field_list_is_the_verifiers_own_not_the_documents():
    """A document that names a shorter list of signed fields (so that only the digest is signed) is refused: the list is fixed here."""
    env, jwks = _golden()
    bad = copy.deepcopy(env)
    bad["signature"]["signed_canonical"] = ["digest"]
    assert verify_distribution_envelope(bad, jwks).ok is False


def test_the_key_is_chosen_by_kid_and_an_unknown_kid_or_a_wrong_key_fails():
    env, jwks = _golden()
    assert verify_distribution_envelope(env, {"keys": []}).reason == "no_key"
    other = copy.deepcopy(jwks)
    other["keys"][0]["x"] = base64.urlsafe_b64encode(bytes(32)).rstrip(b"=").decode()
    assert verify_distribution_envelope(env, other).reason == "signature"
    bad = copy.deepcopy(env)
    bad["signature"]["kid"] = "spiffe://golden.test/registry/golden#2"
    assert verify_distribution_envelope(bad, jwks).reason == "no_key"


def test_a_record_of_one_change_is_checked_the_same_way_and_names_its_change():
    report = {"kind": "distribution.change.record", "record_version": 1, "release": "V0666_x", "change": {"id": "ct_1", "kind": "content"}}
    env, jwks = _signed(report, kind="distribution.change.record", subject="ct_1")
    r = verify_distribution_envelope(env, jwks)
    assert r.ok and r.kind == "distribution.change.record" and r.subject == "ct_1" and r.changes == 1


def test_a_report_whose_counts_disagree_with_its_changes_is_refused_though_it_is_signed():
    report = {"kind": "distribution.release.report", "release": "V0666_x", "changes": [{"id": "cc_1"}], "counts": {"changes": 2}}
    env, jwks = _signed(report)
    r = verify_distribution_envelope(env, jwks)
    assert r.ok is False and r.reason == "counts"
    report["counts"] = {"changes": 1}
    assert verify_distribution_envelope(*_signed(report)).ok is True


def test_the_kind_must_be_one_of_the_two_and_agree_inside_and_outside():
    report = {"kind": "distribution.release.report", "release": "V0666_x", "changes": [], "counts": {"changes": 0}}
    assert verify_distribution_envelope(*_signed(report, kind="something.else")).reason == "kind"
    assert verify_distribution_envelope(*_signed(report, kind="distribution.change.record")).reason == "kind"


def test_malformed_input_is_a_refusal_never_an_exception():
    env, jwks = _golden()
    for bad in (None, [], "x", {}, {"report": 1}, {**env, "signature": None}, {**env, "signature": {"kid": 1}}, {**env, "digest": 5}):
        assert verify_distribution_envelope(bad, jwks).ok is False
    for bad_jwks in (None, [], {}, {"keys": "x"}, {"keys": [None, 5]}):
        assert verify_distribution_envelope(env, bad_jwks).ok is False
    assert verify_distribution_envelope(env, jwks).ok is True


def test_it_checks_files_and_the_command_line_says_valid_or_not(tmp_path, capsys):
    env, jwks = _golden()
    doc, keys = tmp_path / "report.json", tmp_path / "jwks.json"
    doc.write_text(json.dumps(env)); keys.write_text(json.dumps(jwks))
    assert dr.verify_files(str(doc), str(keys)).ok is True
    assert dr.main([str(doc), str(keys)]) == 0 and "VALID" in capsys.readouterr().out
    env["report"]["release"] = "changed"
    doc.write_text(json.dumps(env))
    assert dr.main([str(doc), str(keys)]) == 1 and "NOT VALID" in capsys.readouterr().out
