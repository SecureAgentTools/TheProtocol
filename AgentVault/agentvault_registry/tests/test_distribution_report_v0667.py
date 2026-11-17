"""V0667 D7 (order gwo_0f317438b7dfc6dfacd3e9b7): the signed envelope of a release report, without a database: the canonical convention, the digest, the signature of the registry's card key, and the GOLDEN
envelope the SDK's offline verifier (theprotocol.registry.distribution_report) is tested against byte for byte (tests/fixtures/distribution_report_golden.json here, the same file in theprotocol-sdk/tests/fixtures).

The golden is made with a fixed key (a seed written in this file, never a secret: it signs only this fixture), so its signature is reproducible: this test rebuilds it with the registry's own digest and
signer and asks for the same bytes. If the convention (canonical JSON, the digest, the signed fields) ever changes, this fails, and the SDK's verifier with it.
"""
from __future__ import annotations

import base64
import hashlib
import json
import pathlib

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agentvault_registry import models
from agentvault_registry.services import distribution_report as dr
from agentvault_registry.services.registry_card_signer_impl import sign_with_keypair

GOLDEN = pathlib.Path(__file__).parent / "fixtures" / "distribution_report_golden.json"
SEED = bytes(range(32))                      # a fixed test seed: it signs this fixture only
SPIFFE = "spiffe://golden.test/registry/golden"

BODY = {
    "kind": dr.REPORT_KIND, "report_version": 1, "release": "V0666_golden", "generated_at": "2026-11-16T12:00:00+00:00",
    "registry": {"name": "golden", "spiffe_id": SPIFFE},
    "line": {"slug": "golden", "title": "The golden line", "base_release": "V0666", "organization_id": "org-golden", "organization_name": "Golden Org", "state": "active",
             "open_paths": ["views/"], "quorum_percent": 50, "pass_rule": "simple", "decider_team_id": None},
    "deciders_now": 2,
    "changes": [
        {"id": "cc_golden1", "kind": "code", "change_kind": None, "target": "theprotocol/AgentVault", "title": "A code change", "state": "merged", "created_at": "2026-11-15T10:00:00+00:00",
         "proposer": {"developer_id": 3, "agent_did": "did:a:3"},
         "ballot": {"rule": {"quorum_percent": 50, "pass_rule": "simple", "decider_team_id": None}, "ends": "2026-11-22T10:00:00+00:00",
                    "result": {"status": "PASSED", "sentence": "2 for, 0 against, of 2 deciders: passed"},
                    "votes": [{"developer_id": 1, "vote": True, "agent_did": "did:a:1", "cast_at": "2026-11-15T11:00:00+00:00"},
                              {"developer_id": 2, "vote": True, "agent_did": "did:a:2", "cast_at": "2026-11-15T12:00:00+00:00"}]},
         "checker": {"acceptance": {"ok": True, "reasons": []}},
         "reviews": [{"reviewer_developer_id": 2, "verdict": "approve", "commit": "a" * 40, "at": "2026-11-15T10:30:00+00:00"}], "content_hash": None,
         "outcome": {"commit": "a" * 40, "branch": "b", "paths": ["views/A.vue"], "sensitive": False, "passed_at": "2026-11-15T12:00:00+00:00", "merged": {"into": "V0666_golden"},
                     "veto": None, "go": None, "org_go": None}},
        {"id": "ct_golden2", "kind": "content", "change_kind": "console_text", "target": "landing.tagline", "title": "A tagline", "state": "applied", "created_at": "2026-11-16T09:00:00+00:00",
         "proposer": {"developer_id": 3, "agent_did": "did:a:3"},
         "ballot": {"rule": {"quorum_percent": 50, "pass_rule": "simple", "decider_team_id": None}, "ends": "2026-11-23T09:00:00+00:00",
                    "result": {"status": "PASSED", "sentence": "2 for, 0 against, of 2 deciders: passed"},
                    "votes": [{"developer_id": 1, "vote": True, "agent_did": "did:a:1", "cast_at": "2026-11-16T09:10:00+00:00"},
                              {"developer_id": 2, "vote": True, "agent_did": "did:a:2", "cast_at": "2026-11-16T09:20:00+00:00"}]},
         "checker": {"ok": True, "kind": "console_text", "target": "landing.tagline", "bytes": 24, "rules": ["schema", "secrets", "size"], "at": "2026-11-16T09:00:00+00:00"},
         "reviews": [], "content_hash": hashlib.sha256(b'{"text":"Quiet releases."}').hexdigest(),
         "outcome": {"applied_at": "2026-11-16T09:20:00+00:00", "before_hash": None, "after_hash": hashlib.sha256(b'{"value":"Quiet releases."}').hexdigest(), "apply_error": None, "undone": None}},
    ],
    "counts": {"changes": 2, "code": 1, "content": 1, "by_state": {"applied": 1, "merged": 1}},
    "protected_set": {"status": "not_measured", "reason": dr.PROTECTED_SET_REASON},
}


def _key_row():
    priv = Ed25519PrivateKey.from_private_bytes(SEED)
    pem = priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    raw = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    jwk = {"kty": "OKP", "crv": "Ed25519", "x": base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii"), "alg": "EdDSA"}
    return models.RegistrySigningKey(registry_spiffe_id=SPIFFE, rotation_seq=1, public_jwk=jwk, private_pem_encrypted="plain:" + pem, algorithm="EdDSA"), jwk


def golden_document():
    row, jwk = _key_row()
    env = {"envelope_version": dr.ENVELOPE_VERSION, "registry_spiffe_id": SPIFFE, "kind": dr.REPORT_KIND, "subject": "V0666_golden", "digest": dr.digest_of(BODY), "report": BODY}
    env["signature"] = {"alg": "EdDSA", "kid": f"{SPIFFE}#1", "jwks_url": "/.well-known/registry-jwks.json", "signed_canonical": list(dr.SIGNED_PATHS),
                        "value": sign_with_keypair({p: env[p] for p in dr.SIGNED_PATHS}, row)}
    return {"envelope": env, "jwks": {"keys": [{**jwk, "kid": f"{SPIFFE}#1", "use": "sig"}]}}


def test_the_canonical_form_is_the_registry_cards_own_and_the_digest_is_its_sha256():
    from agentvault_registry.services.registry_card_signer_impl import _canonical_bytes
    doc = {"b": [1, {"z": None, "a": "é"}], "a": True}
    assert dr.canonical(doc) == _canonical_bytes(doc) == b'{"a":true,"b":[1,{"a":"\\u00e9","z":null}]}'      # json.dumps' default: non-ASCII is escaped, the same in every implementation
    assert dr.digest_of(doc) == hashlib.sha256(dr.canonical(doc)).hexdigest()
    assert dr.digest_of({"a": 1, "b": 2}) == dr.digest_of({"b": 2, "a": 1}), "key order never changes the digest"


def test_the_signed_fields_are_the_four_that_pin_what_the_report_is_of():
    assert dr.SIGNED_PATHS == ["registry_spiffe_id", "kind", "subject", "digest"]
    assert {dr.REPORT_KIND, dr.RECORD_KIND} == {"distribution.release.report", "distribution.change.record"}


def test_the_golden_envelope_is_reproduced_byte_for_byte_by_the_registrys_own_digest_and_signer():
    assert json.loads(GOLDEN.read_text()) == golden_document(), "the golden envelope drifted from the registry's convention: regenerate it, and the SDK's copy with it"


def test_the_golden_envelope_verifies_by_the_registrys_own_check_and_one_changed_byte_fails():
    from agentvault_registry.services.registry_card_signer_impl import verify_with_jwk
    doc = golden_document()
    env, jwk = doc["envelope"], doc["jwks"]["keys"][0]
    payload = {p: env[p] for p in env["signature"]["signed_canonical"]}
    assert dr.digest_of(env["report"]) == env["digest"] and verify_with_jwk(payload, env["signature"]["value"], jwk)
    tampered = {**env["report"], "release": "V0666_golden2"}
    assert dr.digest_of(tampered) != env["digest"]
    assert not verify_with_jwk({**payload, "digest": dr.digest_of(tampered)}, env["signature"]["value"], jwk)


# ── the protected-set section (D6): rendered from the verdict's OWN fields, never from a fixed list of kinds (session-lead, room seq 5536) ─────────────────────────────────────────────────────

def test_with_no_build_the_section_says_not_measured_and_why():
    ps = dr.protected_set_section(None)
    assert ps == {"status": "not_measured", "reason": dr.PROTECTED_SET_REASON}
    assert dr.protected_set_section({"verdict": "maybe"}) == ps, "a verdict that is neither intact nor refused is not a verdict"
    assert dr.protected_set_section("intact") == ps


def test_an_intact_verdict_is_carried_whole():
    v = {"verdict": "intact", "refusals": [], "areas": {"federation": {"files": 41, "changed": 0, "added": 0, "removed": 0}}, "removed": {"modules": ["games"], "files": 12, "switches": []}}
    ps = dr.protected_set_section(v)
    assert ps["status"] == "intact" and ps["details"] == v and ps["details"] is not v


def test_a_refused_verdict_keeps_each_refusal_as_its_own_fields_whatever_they_are():
    """The check gains kinds (a patched protected module, a migration on an existing table) and fields (a line number): the report states each refusal as given, naming nothing it was not told."""
    v = {"verdict": "refused", "refusals": [
        {"area": "money", "path": "teg/ledger.py", "kind": "changed"},
        {"area": "identity", "path": "auth/token.py", "kind": "patched_by_assignment", "line": 88, "detail": "module attribute assigned"},
        {"area": "federation", "path": "fed/trust.py", "kind": "added"},
        {"area": "build", "path": "Dockerfile", "kind": "kind_not_yet_invented", "new_field": [1, 2]}],
        "not_seen": ["dynamic imports the scan cannot read"]}
    ps = dr.protected_set_section(v)
    assert ps["status"] == "refused" and ps["details"]["refusals"] == v["refusals"] and ps["details"]["not_seen"] == v["not_seen"]
    assert dr.canonical(ps)                                            # and it is canonical JSON like the rest, so it digests and signs


def test_the_section_is_what_the_report_carries_and_the_digest_covers_it():
    refused = dr.protected_set_section({"verdict": "refused", "refusals": [{"area": "money", "path": "a.py", "kind": "changed"}]})
    other = dr.protected_set_section({"verdict": "intact", "refusals": []})
    assert dr.digest_of({"protected_set": refused}) != dr.digest_of({"protected_set": other})
