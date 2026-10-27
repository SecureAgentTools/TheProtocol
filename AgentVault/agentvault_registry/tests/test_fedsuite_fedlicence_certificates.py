"""§FEDLICENCE (2026-09-28): the federation-suite licence tests can FAIL, proven offline before any live run.

`api_tests/federation_suite/tests/test_fedlicence_certificates.py` measures the signed licence across a pair. Each of
its six tests is driven here through a fake rig (adminRequest answered from a small in-memory pair, the poll loop run
once) in a healthy world, where it must pass, and in a world with exactly one thing wrong, where it must fail or report
NOT MEASURED. The certificates and lists are signed here with throwaway Ed25519 keys through cryptography directly, so
nothing here trusts the product's own signer either.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from agentvault_registry.api_tests.federation_suite.rig import AssertionResult, FederationTestRig, PreconditionUnmet
from agentvault_registry.api_tests.federation_suite.tests import test_fedlicence_certificates as ft

A, B = ft.FRAMES
A_TD, B_TD = "alpha.example", "beta.example"


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _jwk(priv: Ed25519PrivateKey) -> dict:
    raw = priv.public_key().public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
    return {"kty": "OKP", "crv": "Ed25519", "x": _b64u(raw)}


def _jws(payload: dict, priv: Ed25519PrivateKey) -> str:
    si = _b64u(json.dumps({"alg": "EdDSA", "typ": "tp-licence+jws"}).encode()) + "." + \
        _b64u(json.dumps(payload, sort_keys=True).encode())
    return si + "." + _b64u(priv.sign(si.encode("ascii")))


def _sha(jws: str) -> str:
    return hashlib.sha256(jws.encode("ascii")).hexdigest()


class World:
    """Frame A holds the network's root; frame B holds a frame licence A issued. Each attribute is one fact a test
    reads, so a control changes exactly one of them."""

    def __init__(self):
        self.g = Ed25519PrivateKey.generate()
        self.root = _jws({"type": "genesis", "sub": {"trust_domain": A_TD}, "key": _jwk(self.g)}, self.g)
        self.b_cert = _jws({"type": "frame", "sub": {"trust_domain": B_TD}, "iss": {"trust_domain": A_TD}}, self.g)
        self.list_payload = {"kind": "tp-licence-list", "issuer": {"trust_domain": A_TD},
                             "licences": [{"hash": _sha(self.b_cert), "state": "active"}]}
        self.list_signer = self.g
        self.own = {
            A: {"trust_domain": A_TD, "name": "Alpha", "state": "genesis", "hash": _sha(self.root),
                "certificate": self.root, "reason": "the network's root"},
            B: {"trust_domain": B_TD, "name": "Beta", "state": "licensed", "hash": _sha(self.b_cert),
                "certificate": self.b_cert, "reason": f"signed by {A_TD}, active on its list"},
        }
        self.keys = {A: _jwk(self.g), B: None}
        self.issued = {A: 1, B: 0}
        self.issue_answer = {A: (422, "a frame licence names another trust domain; the genesis holds its own "),
                             B: (422, "only the network's genesis issues frame licences, and this registry is not it")}
        self.key_after_issue = {}                      # label -> the key a refused issue left behind (a write)
        self.leaves = list(ft.LICENCE_LEAVES) + ["identity.registry_name"]
        self.verdicts = {A: {"name": "beta", "trust_domain": B_TD, "peer_type": "frame", "licence_state": "licensed",
                             "licence_reason": "ok", "licence_checked_at": "2026-09-28T03:00:00+00:00"},
                         B: {"name": "alpha", "trust_domain": A_TD, "peer_type": "frame", "licence_state": "genesis",
                             "licence_reason": "the network's root", "licence_checked_at": "2026-09-28T03:00:00+00:00"}}
        self.envelope_overrides = {}
        self.routes_missing = False

    def answer(self, label, method, endpoint, params, body):
        if self.routes_missing and "licence" in endpoint:
            return 404, {"detail": "Not Found"}
        if endpoint == "/.well-known/federation-licence.json":
            return 200, copy.deepcopy(self.own[label])
        if endpoint == "/.well-known/federation-licences.json":
            jws = _jws(self.list_payload, self.list_signer)
            return 200, {"jws": jws, "payload": copy.deepcopy(self.list_payload),
                         "count": len(self.list_payload["licences"])}
        if endpoint.startswith("/api/v1/public/federation/licences/"):
            h = endpoint.rsplit("/", 1)[1]
            if len(h) != 64:
                return 422, {"detail": "string does not match pattern"}
            if label == A and h == _sha(self.b_cert):
                return 200, {"hash": h, "state": "active", "certificate": self.b_cert}
            return 404, {"detail": "no licence with that hash was issued by this registry"}
        if endpoint == "/api/v1/admin/federation/licence/status":
            return 200, {"local_trust_domain": self.own[label]["trust_domain"],
                         "genesis_trust_domain": A_TD, "root": ({"hash": _sha(self.root)} if label == A else None),
                         "self": {"key": self.keys[label]}, "peers": [copy.deepcopy(self.verdicts[label])]}
        if endpoint == "/api/v1/admin/federation/licence/issued":
            return 200, {"count": self.issued[label], "licences": []}
        if endpoint == "/api/v1/admin/federation/licence/issue" and method == "POST":
            code, detail = self.issue_answer[label]
            if label in self.key_after_issue:
                self.keys[label] = self.key_after_issue[label]
            if code == 200:
                self.issued[label] += 1
            return code, {"detail": detail}
        if endpoint == "/.well-known/registry-card.json":
            lic = {k: self.own[label][k] for k in ("state", "hash")}
            return 200, {"federation": {"licence": lic}, "signature": {"signed_canonical": list(self.leaves)}}
        if endpoint == "/api/v1/public/registry-card":
            row = self.verdicts[label]
            env = {k: row[k] for k in ("licence_state", "licence_reason", "licence_checked_at")}
            env.update(self.envelope_overrides)
            return 200, {"is_self": False, "name": params.get("peer"), **env}
        return 404, {"detail": "Not Found"}


class Rig(FederationTestRig):
    def __init__(self, world: World):
        super().__init__()
        self.world, self.calls = world, []

    def mcp(self, label):
        rig = self

        class _Client:
            async def call(self, tool, args=None, timeout=None):
                assert tool == "adminRequest"
                rig.calls.append((label, args["method"], args["endpoint"]))
                code, body = rig.world.answer(label, args["method"], args["endpoint"], args.get("params") or {},
                                              args.get("body"))
                return {"status_code": code, "response": body, "ok": code < 400}
        return _Client()

    async def assert_within(self, *, budget_sec, predicate, description, poll_interval_sec=1.0, capture_state=None):
        ok = await predicate()
        return AssertionResult(passed=bool(ok), description=description, budget_sec=budget_sec, elapsed_sec=0.0,
                               polling_attempts=1, last_state=capture_state() if capture_state else None)


async def _run(test, world):
    return await test(Rig(world))


ALL = [ft.test_genesis_list_verifies_under_its_root_key, ft.test_public_lookup_refuses_an_unknown_hash,
       ft.test_issue_refuses_a_frame_licence_it_cannot_grant, ft.test_card_signs_its_licence_leaves,
       ft.test_peer_envelope_carries_our_verdict, ft.test_peer_accepts_the_genesis_list]


@pytest.mark.parametrize("test", ALL, ids=lambda t: t.__name__)
async def test_every_licence_test_passes_on_a_healthy_pair(test):
    r = await _run(test, World())
    assert r.passed, r.last_state


@pytest.mark.parametrize("test", ALL, ids=lambda t: t.__name__)
async def test_control_an_image_without_the_routes_is_not_measured_never_red(test):
    w = World()
    w.routes_missing = True
    with pytest.raises(PreconditionUnmet):
        await _run(test, w)


async def test_control_a_list_signed_by_another_key_fails_pin_1():
    w = World()
    w.list_signer = Ed25519PrivateKey.generate()
    assert not (await _run(ft.test_genesis_list_verifies_under_its_root_key, w)).passed


async def test_control_a_list_naming_another_issuer_fails_pin_1():
    w = World()
    w.list_payload["issuer"]["trust_domain"] = "elsewhere.example"
    assert not (await _run(ft.test_genesis_list_verifies_under_its_root_key, w)).passed


async def test_control_no_genesis_is_not_measured():
    w = World()
    w.own[A]["state"] = "licensed"
    with pytest.raises(PreconditionUnmet):
        await _run(ft.test_genesis_list_verifies_under_its_root_key, w)


async def test_control_a_listed_hash_whose_certificate_differs_fails_pin_2():
    w = World()
    w.list_payload["licences"][0]["state"] = "revoked"       # the lookup still answers "active"
    assert not (await _run(ft.test_public_lookup_refuses_an_unknown_hash, w)).passed


async def test_control_a_refusal_that_writes_a_key_fails_pin_3():
    w = World()
    w.key_after_issue[B] = {"kty": "OKP", "crv": "Ed25519", "x": "AAAA"}
    assert not (await _run(ft.test_issue_refuses_a_frame_licence_it_cannot_grant, w)).passed


async def test_control_an_issue_that_succeeds_fails_pin_3():
    w = World()
    w.issue_answer[B] = (200, "")
    assert not (await _run(ft.test_issue_refuses_a_frame_licence_it_cannot_grant, w)).passed


async def test_pin_3_sends_exactly_one_probe_per_frame():
    rig = Rig(World())
    assert (await ft.test_issue_refuses_a_frame_licence_it_cannot_grant(rig)).passed
    posts = [c for c in rig.calls if c[1] == "POST"]
    assert sorted(c[0] for c in posts) == sorted([A, B])


async def test_control_a_card_that_does_not_sign_a_leaf_fails_pin_4():
    w = World()
    w.leaves.remove("federation.licence.hash")
    assert not (await _run(ft.test_card_signs_its_licence_leaves, w)).passed


async def test_control_an_envelope_carrying_the_cards_claim_fails_pin_5():
    w = World()
    w.verdicts[A]["licence_state"] = "revoked"
    w.envelope_overrides = {"licence_state": "licensed"}      # the peer's own claim, not our verdict
    assert not (await _run(ft.test_peer_envelope_carries_our_verdict, w)).passed


async def test_control_an_envelope_without_the_verdict_keys_fails_pin_5():
    w = World()

    def answer(label, method, endpoint, params, body, _orig=w.answer):
        code, out = _orig(label, method, endpoint, params, body)
        if endpoint == "/api/v1/public/registry-card":
            out = {k: v for k, v in out.items() if not k.startswith("licence_")}
        return code, out
    w.answer = answer
    assert not (await _run(ft.test_peer_envelope_carries_our_verdict, w)).passed


async def test_control_a_reader_with_no_usable_list_fails_pin_6():
    w = World()
    w.own[B].update(state="unverified", reason=f"no verified licence list from {A_TD}")
    assert not (await _run(ft.test_peer_accepts_the_genesis_list, w)).passed


async def test_control_an_unlicensed_reader_is_not_measured():
    w = World()
    w.own[B].update(state="unlicensed", certificate=None)
    with pytest.raises(PreconditionUnmet):
        await _run(ft.test_peer_accepts_the_genesis_list, w)
