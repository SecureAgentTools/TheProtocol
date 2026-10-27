"""§TWOAGENT (2026-09-23) — the provider's frame hears each milestone the home releases.

Measured on production V0432 (EU ⇄ ASIA, `ctr_046d2b3a11c710882c88c1ad`): the provider's owner on ASIA got
contract.offered, contract.agreed, payment.received and contract.completed, and never contract.milestone_released. The
replica learns only the signed CORE (contract-level fields), so it could not know that a milestone was released, and it
spoke only on a STATUS change: the final release as a completion, a middle one not at all. V0433 fixed the HOME's
announcement (`announce_release`), which reaches only a party whose owner lives at the home.

Now the home carries the released milestones under a SECOND signature (the core's digest and signature are unchanged,
so an older verifier accepts the envelope exactly as before), the verifier drops a list whose own signature does not
verify, every builder that hands a peer an envelope goes through one helper, and the replica announces each newly
released milestone to the provider's owner, before the completion.

RED on the pre-change tree: every test except the four controls at the end.
"""
from __future__ import annotations

import ast
import asyncio
import base64
import importlib
import json
import pathlib
import types

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

xf = importlib.import_module("agentvault_registry.services.contract_xframe")
cset = importlib.import_module("agentvault_registry.services.contract_settlement")
signer = importlib.import_module("agentvault_registry.services.registry_card_signer_impl")
keystore = importlib.import_module("agentvault_registry.services.registry_card_keystore")
builder = importlib.import_module("agentvault_registry.services.registry_card_builder")
passport = importlib.import_module("agentvault_registry.services.exchange_passport")
cf = importlib.import_module("agentvault_registry.routers.contract_federation")

EXT = "released_milestones"
CID = "ctr_replmile"
CLIENT = "did:theprotocol:eu.theprotocol.cloud:client-0000"
PROVIDER = "did:theprotocol:asia.theprotocol.cloud:provider-0000"
SPIFFE = "spiffe://eu.theprotocol.cloud/service/eu-registry"
KID = SPIFFE + "#1"
_SK = Ed25519PrivateKey.generate()
_X = base64.urlsafe_b64encode(
    _SK.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).rstrip(b"=").decode()
JWK = {"kty": "OKP", "crv": "Ed25519", "x": _X, "kid": KID}


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Res:
    def __init__(self, row=None, rows=None, scalar=None, rowcount=1):
        self._row, self._rows, self._scalar, self.rowcount = row, rows, scalar, rowcount

    def mappings(self):
        return self

    def first(self):
        return self._row

    def all(self):
        return self._rows or ([] if self._row is None else [self._row])

    def scalar(self):
        return self._scalar


class _DB:
    """Answers by SQL fragment, first match wins; records every statement."""
    def __init__(self, answers):
        self.answers, self.sql = answers, []

    async def execute(self, clause, params=None):
        q = str(clause)
        self.sql.append(q)
        for frag, res in self.answers:
            if frag in q:
                return res
        return _Res()

    async def commit(self):
        pass


def _keys(monkeypatch):
    """The home's card key is a real Ed25519 key; its JWKS is what the replica frame fetches."""
    async def _key(db, spiffe_id):
        return types.SimpleNamespace(rotation_seq=1)

    async def _jwks(db, home, force=False):
        return [JWK]
    monkeypatch.setattr(builder, "_build_spiffe_id", lambda: SPIFFE)
    monkeypatch.setattr(keystore, "get_or_mint_signing_key", _key)
    monkeypatch.setattr(signer, "sign_with_keypair", lambda payload, key_row: base64.urlsafe_b64encode(
        _SK.sign(signer._canonical_bytes(payload))).rstrip(b"=").decode())
    monkeypatch.setattr(passport, "fetch_home_jwks", _jwks)
    monkeypatch.setattr(passport, "_invalidate_home_jwks", lambda home: None)


def _row(status="in_progress", seq=5):
    return {"id": CID, "status": status, "seq": seq, "client_did": CLIENT, "provider_did": PROVIDER,
            "currency": "ECU", "total_amount": "0.2", "title": "t"}


def _signed(monkeypatch, released):
    _keys(monkeypatch)
    return _run(xf.sign_snapshot(None, xf.snapshot_of(_row(), "eu", released=released)))


def _payload(status, seq, released=None):
    p = {"cid": CID, "home_registry": "eu", "client_did": CLIENT, "provider_did": PROVIDER, "status": status,
         "seq": seq, "title": "t", "currency": "ECU", "total_amount": "0.2"}
    if released is not None:
        p[EXT] = released
    return p


def _upsert(monkeypatch, *, prev, stored, payload):
    told = []
    monkeypatch.setattr(cset, "webhook", lambda ev, c, extra=None: told.append(
        (ev, (extra or {}).get("seq"), (extra or {}).get("completed"), (extra or {}).get("replica"),
         c.get("provider_did"))))
    db = _DB([("SELECT status FROM contract_replicas", _Res(scalar=prev)),
              ("SELECT payload FROM contract_replicas", _Res(scalar=stored)),
              ("INSERT INTO contract_replicas", _Res(rowcount=1))])
    env = {"payload": payload, "digest": "d", "signature": {"value": "s"}}
    assert _run(xf.upsert_replica(db, env, verified=True)) is True
    return told, db


# ── the list travels under its own signature ─────────────────────────────────────────────────────────────────────

def test_the_home_signs_the_released_list_and_the_replica_keeps_it(monkeypatch):
    env = _signed(monkeypatch, [2, 1])
    assert env["payload"][EXT] == [1, 2] and env["signature_ext"]["covers"] == EXT
    assert _run(xf.verify_envelope(None, env)) is True
    assert env["payload"][EXT] == [1, 2]


def test_a_doctored_list_is_dropped_and_the_replica_still_verifies(monkeypatch):
    env = _signed(monkeypatch, [1])
    env["payload"][EXT] = [1, 2]
    assert _run(xf.verify_envelope(None, env)) is True
    assert EXT not in env["payload"]


def test_a_list_without_its_own_signature_is_dropped(monkeypatch):
    env = _signed(monkeypatch, [1])
    env.pop("signature_ext")
    assert _run(xf.verify_envelope(None, env)) is True
    assert EXT not in env["payload"]


def test_the_digest_a_reconciler_pulls_carries_the_list(monkeypatch):
    _keys(monkeypatch)

    async def _resolve(db, v):
        return "asia" if "asia" in (v or "").lower() else None
    monkeypatch.setattr(xf, "enabled", lambda: True)
    monkeypatch.setattr(xf, "resolve_peer_name", _resolve)
    monkeypatch.setattr(xf, "self_federation_name", lambda: "eu")
    row = {**_row(), "counterparty_home_registry": "asia"}
    db = _DB([("FROM contract_milestones", _Res(rows=[(1,), (2,)])),
              ("COALESCE(MAX(seq)", _Res(scalar=6)),
              ("FROM contracts WHERE id", _Res(row=row))])
    out = _run(cf.contract_digest(cid=CID, peer_spiffe="spiffe://asia.theprotocol.cloud/service/asia-registry", db=db))
    env = out["envelope"]
    assert env["payload"][EXT] == [1, 2]
    assert _run(xf.verify_envelope(None, env)) is True and env["payload"][EXT] == [1, 2]


def test_every_envelope_builder_goes_through_the_one_helper():
    """The push mirror, the digest a reconciler pulls and the bootstrap list: a builder that signs a snapshot itself
    would hand the peer an envelope without the list, and nothing would say so."""
    root = pathlib.Path(xf.__file__).resolve().parents[1]
    callers = set()
    for f in root.rglob("*.py"):
        for node in ast.walk(ast.parse(f.read_text())):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call):
                        fn = sub.func
                        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
                        if name in ("snapshot_of", "sign_snapshot"):
                            callers.add((f.name, node.name, name))
    assert callers == {("contract_xframe.py", "signed_envelope_for", "snapshot_of"),
                       ("contract_xframe.py", "signed_envelope_for", "sign_snapshot")}


# ── the replica tells the provider's owner ───────────────────────────────────────────────────────────────────────

def test_the_final_release_reaches_the_providers_owner_before_the_completion(monkeypatch):
    told, _ = _upsert(monkeypatch, prev="in_progress", stored=json.dumps({EXT: []}),
                      payload=_payload("completed", 9, [1]))
    assert told == [("contract.milestone_released", 1, True, True, PROVIDER),
                    ("contract.completed", None, None, True, PROVIDER)]


def test_a_middle_release_is_announced_alone(monkeypatch):
    told, _ = _upsert(monkeypatch, prev="in_progress", stored={EXT: [1]}, payload=_payload("in_progress", 12, [1, 2]))
    assert told == [("contract.milestone_released", 2, False, True, PROVIDER)]


# ── controls: green before and after ─────────────────────────────────────────────────────────────────────────────

def test_control_an_older_verifier_accepts_the_new_envelope(monkeypatch):
    """The core digest and the core signature ignore the list: a frame on an older image verifies as it always did."""
    _keys(monkeypatch)
    snap = xf.snapshot_of(_row(), "eu")
    snap[EXT] = [1]
    env = _run(xf.sign_snapshot(None, snap))
    core = {k: snap.get(k) for k in xf.DIGEST_FIELDS}
    assert env["digest"] == xf.digest_of({k: v for k, v in snap.items() if k != EXT})
    assert signer.verify_with_jwk(core, env["signature"]["value"], JWK) is True


def test_control_no_baseline_no_notice(monkeypatch):
    """A replica an older home wrote (or one whose list did not verify) has nothing to compare with: silence."""
    told, _ = _upsert(monkeypatch, prev="in_progress", stored=json.dumps({"cid": CID}),
                      payload=_payload("in_progress", 12, [1]))
    assert told == []


def test_control_first_sight_asks_for_no_baseline(monkeypatch):
    told, db = _upsert(monkeypatch, prev=None, stored=None, payload=_payload("offered", 1, []))
    assert told == [("contract.offered", None, None, True, PROVIDER)]
    assert not any("SELECT payload FROM contract_replicas" in q for q in db.sql)


def test_control_an_envelope_from_an_older_home_changes_nothing(monkeypatch):
    told, db = _upsert(monkeypatch, prev="in_progress", stored={EXT: [1]}, payload=_payload("completed", 9))
    assert told == [("contract.completed", None, None, True, PROVIDER)]
    assert not any("SELECT payload FROM contract_replicas" in q for q in db.sql)
