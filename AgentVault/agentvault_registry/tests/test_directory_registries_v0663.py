"""V0663, the Directory read path, steps 1 and 3 (order gwo_0936844934f713153ede256c;
PLAN_2026-11-13_DIRECTORY_REGISTRY_CARDS.md): a registry asks the federated index which registries it knows, for peers and
not only for agents, and verifies every card itself.

The index is untrusted by construction (the plan's rule): it can omit a card, never vouch for one. So:
  - the card's signature is checked here, by the same reconstruction the federation sync performs (the card's own declared
    signed_canonical, the freshness anchor, expiry refused, the compliance digest recomputed), now one function
    (services/registry_card_verify) instead of a copy;
  - the key comes from the origin the card itself names in its SIGNED identity.public_url, never from the unsigned
    signature.jwks_url and never from the address the index lists: an index that pairs a card it made with a key it
    controls gets an unverified row, because the key is fetched from the real registry's own origin;
  - that fetch goes through the outbound guard (site registry_jwks), is size-bounded and cached per origin;
  - an index answer never creates a peer row: the read path only reads the database; each registry is marked self, peer
    (an ACTIVE row), known (a row in another state) or candidate (no row: what an admin may invite);
  - where the index's address and the card's disagree, both are shown and the row says so;
  - a broken index is reported as broken (502 with the reason), never as an empty list.
GET /api/v1/public/directory/registries serves it; the fan-out is not touched (step 2 waits for the network numbers).
Red on 7eb9724e3: neither module exists.
"""
from __future__ import annotations

import asyncio
import base64
import copy
import datetime as dt
import json
import socket

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from agentvault_registry.core import outbound_guard as og

try:     # red as one failure per test, not a collection error that stops the suite
    from agentvault_registry.services import registry_card_verify as rcv
    from agentvault_registry.services import directory_registries as dr
except ImportError:
    rcv = dr = None

PUBLIC = "93.184.216.34"
PUBLIC2 = "93.184.216.35"


def test_the_modules_exist():
    from agentvault_registry.services import directory_registries, registry_card_verify
    assert directory_registries.SITE == "registry_jwks" and callable(registry_card_verify.verify_registry_card)


# --- signing, as a registry signs its card --------------------------------------------------------------------------

def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


class Signer:
    def __init__(self, kid):
        self.kid, self.key = kid, Ed25519PrivateKey.generate()

    def jwk(self):
        raw = self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        return {"kty": "OKP", "crv": "Ed25519", "kid": self.kid, "x": _b64(raw)}

    def sign(self, card, *, expires_in=3600, paths=None):
        card = copy.deepcopy(card)
        paths = paths or ["registry_card_version", "identity.registry_name", "identity.trust_domain",
                          "identity.public_url", "identity.tier", "lifecycle.card_etag"]
        now = dt.datetime.now(dt.timezone.utc)
        sig = {"alg": "EdDSA", "kid": self.kid, "signed_canonical": paths, "signed_at": now.isoformat(),
               "expires_at": (now + dt.timedelta(seconds=expires_in)).isoformat()}
        payload = {}
        for p in paths:
            cur = card
            for part in p.split("."):
                cur = cur.get(part) if isinstance(cur, dict) else None
            payload[p] = cur
        payload["_signed_at"], payload["_expires_at"] = sig["signed_at"], sig["expires_at"]
        msg = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
        sig["value"] = _b64(self.key.sign(msg))
        sig["jwks_url"] = "/.well-known/registry-jwks.json"
        card["signature"] = sig
        return card


def _card(name, td, url, etag="e1"):
    return {"registry_card_version": "0.6",
            "identity": {"registry_name": name, "trust_domain": td, "public_url": url, "tier": "sovereign-mainframe"},
            "operator": {"location_label": "Brussels"}, "fees": {"settlement_currency": "ECU"},
            "lifecycle": {"card_etag": etag}}


EU = Signer("eu-k1")
ASIA = Signer("asia-k1")
FORGER = Signer("eu-k1")          # the same kid, another key: what an index would need to vouch for a card it made


# --- one verifier ----------------------------------------------------------------------------------------------------

def test_a_genuine_card_verifies():
    card = EU.sign(_card("eu-registry", "eu.theprotocol.cloud", "https://eu.example.org"))
    assert rcv.verify_registry_card(card, {"keys": [EU.jwk()]}) == (True, "ok")


@pytest.mark.parametrize("mutate,reason", [
    (lambda c: c["identity"].__setitem__("registry_name", "someone-else"), "signature invalid"),
    (lambda c: c["signature"].pop("value"), "unsigned"),
    (lambda c: c["signature"].__setitem__("kid", "nobody"), "kid not in jwks"),
])
def test_a_changed_or_unsigned_card_does_not(mutate, reason):
    card = EU.sign(_card("eu-registry", "eu.theprotocol.cloud", "https://eu.example.org"))
    mutate(card)
    assert rcv.verify_registry_card(card, {"keys": [EU.jwk()]}) == (False, reason)


def test_an_expired_signature_does_not_verify_even_when_the_signature_holds():
    card = EU.sign(_card("eu-registry", "eu.theprotocol.cloud", "https://eu.example.org"), expires_in=-60)
    assert rcv.verify_registry_card(card, {"keys": [EU.jwk()]}) == (False, "signature expired")


def test_a_compliance_block_must_match_its_signed_digest():
    from agentvault_registry.services.regulatory_auth import compliance_digest
    base = _card("eu-registry", "eu.theprotocol.cloud", "https://eu.example.org")
    base["compliance"] = {"jurisdiction": "DE", "licences": []}
    base["compliance"]["digest"] = compliance_digest(base["compliance"])
    paths = ["identity.registry_name", "compliance.digest"]
    good = EU.sign(base, paths=paths)
    assert rcv.verify_registry_card(good, {"keys": [EU.jwk()]})[0] is True
    bad = copy.deepcopy(good)
    bad["compliance"]["jurisdiction"] = "XX"      # the block changed under a digest that did not
    assert rcv.verify_registry_card(bad, {"keys": [EU.jwk()]}) == (False, "compliance digest mismatch")


def test_no_key_set_is_its_own_reason():
    card = EU.sign(_card("eu-registry", "eu.theprotocol.cloud", "https://eu.example.org"))
    assert rcv.verify_registry_card(card, None) == (False, "no jwks")


# --- the key's origin -------------------------------------------------------------------------------------------------

def test_the_key_comes_from_the_origin_the_signed_card_names():
    card = EU.sign(_card("eu-registry", "eu.theprotocol.cloud", "https://eu.example.org"))
    card["signature"]["jwks_url"] = "https://evil.example.org/keys.json"     # unsigned: the index could change it
    assert dr.jwks_origin(card) == "https://eu.example.org"
    for url in ("http://eu.example.org", "eu.example.org", "https://eu.example.org/path?q=1#f", None):
        c = copy.deepcopy(card)
        c["identity"]["public_url"] = url
        assert dr.jwks_origin(c) in (None, "https://eu.example.org"), url
    c = copy.deepcopy(card)
    c["identity"]["public_url"] = "http://eu.example.org"
    assert dr.jwks_origin(c) is None, "a card that names no https origin has no key to fetch"


# --- the read path -----------------------------------------------------------------------------------------------------

class FakeRedis:
    def __init__(self):
        self.store = {}

    async def get(self, k):
        return self.store.get(k)

    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.store:
            return None
        self.store[k] = v
        return True

    async def delete(self, k):
        self.store.pop(k, None)


def _row(card, *, name=None, url=None, reachable=True, verified=True):
    ident = (card or {}).get("identity") or {}
    return {"name": name or ident.get("registry_name"), "trustDomain": ident.get("trust_domain"),
            "publicUrl": url or ident.get("public_url"), "tier": ident.get("tier"), "reachable": reachable,
            "verified": verified, "cardEpoch": "e1", "lastSyncAt": 1.0, "card": card}


def _run(rows, *, keys, peers=(), own_url="https://here.example.org", redis=None, asked=None):
    async def fetch_jwks(origin):
        if asked is not None:
            asked.append(origin)
        k = keys.get(origin)
        if k is None:
            raise dr.JwksUnavailable("http_404")
        return {"keys": k}
    return asyncio.run(dr.read_registries(rows, fetch_jwks=fetch_jwks, peers=list(peers), own_public_url=own_url,
                                          redis=redis or FakeRedis()))


EU_URL, ASIA_URL = "https://eu.example.org", "https://asia.example.org"


def test_each_card_is_verified_here_and_named_from_its_own_signed_body():
    eu = EU.sign(_card("eu-registry", "eu.theprotocol.cloud", EU_URL))
    asia = ASIA.sign(_card("asia-registry", "asia.theprotocol.cloud", ASIA_URL))
    out = _run([_row(eu), _row(asia)], keys={EU_URL: [EU.jwk()], ASIA_URL: [ASIA.jwk()]})
    by = {r["name"]: r for r in out["registries"]}
    assert by["eu-registry"]["verified"] is True and by["eu-registry"]["trust_domain"] == "eu.theprotocol.cloud"
    assert by["asia-registry"]["verified"] is True and by["asia-registry"]["currency"] == "ECU"
    assert out["counts"] == {"index": 2, "verified": 2, "unverified": 0, "read": 2}


def test_a_card_the_index_made_and_signed_with_its_own_key_is_not_verified():
    """The index pairs a card claiming EU's address with a key it controls, and points jwks_url at itself."""
    forged = FORGER.sign(_card("eu-registry", "eu.theprotocol.cloud", EU_URL))
    forged["signature"]["jwks_url"] = "https://index.example.org/keys.json"
    asked = []
    out = _run([_row(forged)], keys={EU_URL: [EU.jwk()], "https://index.example.org": [FORGER.jwk()]}, asked=asked)
    r = out["registries"][0]
    assert r["verified"] is False and r["reason"] == "signature invalid"
    assert asked == [EU_URL], "the key is asked of the origin the card names, never of an address the index gave"


def test_where_the_index_and_the_card_disagree_on_the_address_both_are_shown():
    eu = EU.sign(_card("eu-registry", "eu.theprotocol.cloud", EU_URL))
    out = _run([_row(eu, url="https://elsewhere.example.org")], keys={EU_URL: [EU.jwk()]})
    r = out["registries"][0]
    assert r["verified"] is True and r["public_url"] == EU_URL
    assert r["index"]["public_url"] == "https://elsewhere.example.org" and r["address_agrees"] is False


def test_a_row_without_a_whole_card_is_listed_unverified_under_the_index_name():
    out = _run([_row(None, name="ghost-registry", url="https://ghost.example.org")], keys={})
    r = out["registries"][0]
    assert r["verified"] is False and r["reason"] == "the index holds no whole card"
    assert r["name"] is None and r["index"]["name"] == "ghost-registry", "an unverified name is the index's word only"


def test_an_unreachable_key_set_is_its_own_reason():
    eu = EU.sign(_card("eu-registry", "eu.theprotocol.cloud", EU_URL))
    r = _run([_row(eu)], keys={})["registries"][0]
    assert r["verified"] is False and r["reason"] == "jwks unavailable (http_404)"


def test_each_registry_is_marked_self_peer_known_or_candidate():
    here = EU.sign(_card("here", "here.theprotocol.cloud", "https://here.example.org"))
    eu = EU.sign(_card("eu-registry", "eu.theprotocol.cloud", EU_URL))
    asia = ASIA.sign(_card("asia-registry", "asia.theprotocol.cloud", ASIA_URL))
    other = ASIA.sign(_card("lisbon-registry", "lisbon.theprotocol.cloud", "https://lisbon.example.org"))
    peers = [{"name": "eu-registry", "base_url": "https://federation.eu.example.org:8443", "status": "ACTIVE"},
             {"name": "asia-old-name", "base_url": "https://asia.example.org:8443", "status": "INACTIVE"}]   # by host
    keys = {"https://here.example.org": [EU.jwk()], EU_URL: [EU.jwk()], ASIA_URL: [ASIA.jwk()],
            "https://lisbon.example.org": [ASIA.jwk()]}
    out = _run([_row(here), _row(eu), _row(asia), _row(other)], keys=keys, peers=peers)
    rel = {r["name"]: r["relation"] for r in out["registries"]}
    assert rel == {"here": "self", "eu-registry": "peer", "asia-registry": "known", "lisbon-registry": "candidate"}


def test_an_unverified_row_is_never_a_peer_by_its_name_alone():
    """A row the index names after a peer, with no card that verifies, must not borrow the peer's standing."""
    out = _run([_row(None, name="eu-registry", url=EU_URL)], keys={},
               peers=[{"name": "eu-registry", "base_url": EU_URL, "status": "ACTIVE"}])
    assert out["registries"][0]["relation"] == "unverified"


def test_an_operator_is_not_its_frames_peer_by_the_trust_domain_they_share():
    """Measured on the sandbox (2026-11-13): sandbox-b's operators all carry sandbox-b.theprotocol.cloud, the frame's
    trust domain. Sandbox Beta is an ACTIVE peer of sbx-alpha and b1opb's own row is INACTIVE: b1opb is known, not peer."""
    frame_url, op_url = "https://sandbox-b.example.org", "https://b1opb.op.example.org"
    frame = EU.sign(_card("Sandbox Beta", "sandbox-b.theprotocol.cloud", frame_url))
    op = EU.sign(_card("b1opb", "sandbox-b.theprotocol.cloud", op_url))
    peers = [{"name": "Sandbox Beta", "base_url": "https://sandbox-b.example.org:8443", "status": "ACTIVE",
              "trust_domain": "sandbox-b.theprotocol.cloud"},
             {"name": "b1opb", "base_url": "https://b1opb.op.example.org:8443", "status": "INACTIVE",
              "trust_domain": "sandbox-b.theprotocol.cloud"}]      # as the rows read on sbx-alpha
    out = _run([_row(frame), _row(op)], keys={frame_url: [EU.jwk()], op_url: [EU.jwk()]}, peers=peers)
    assert {r["name"]: r["relation"] for r in out["registries"]} == {"Sandbox Beta": "peer", "b1opb": "known"}


def test_the_key_set_is_fetched_once_per_origin_and_kept():
    eu = EU.sign(_card("eu-registry", "eu.theprotocol.cloud", EU_URL))
    eu2 = EU.sign(_card("eu-registry-2", "eu2.theprotocol.cloud", EU_URL))    # two cards, one origin
    r, asked = FakeRedis(), []
    _run([_row(eu), _row(eu2)], keys={EU_URL: [EU.jwk()]}, redis=r, asked=asked)
    _run([_row(eu)], keys={EU_URL: [EU.jwk()]}, redis=r, asked=asked)
    assert asked == [EU_URL]


def test_a_large_index_answer_is_read_up_to_the_cap_and_says_so(monkeypatch):
    monkeypatch.setattr(dr, "MAX_REGISTRIES", 3)
    cards = [EU.sign(_card(f"r{i}", f"r{i}.theprotocol.cloud", EU_URL)) for i in range(5)]
    out = _run([_row(c) for c in cards], keys={EU_URL: [EU.jwk()]})
    assert len(out["registries"]) == 3 and out["counts"]["index"] == 5 and out["counts"]["read"] == 3
    assert out["truncated"] is True


# --- the key fetch, through the guard ----------------------------------------------------------------------------------

class _Dns:
    def __init__(self):
        self.answers = {}

    def __call__(self, host, port, *a, **k):
        addrs = self.answers.get(host)
        if not addrs:
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (x, port)) for x in addrs]


@pytest.fixture
def dns(monkeypatch):
    d = _Dns()
    monkeypatch.setattr(socket, "getaddrinfo", d)
    return d


def _refused(site, reason):
    c = og.OUTBOUND_REFUSED_TOTAL
    return c.labels(site=site, reason=reason)._value.get() if c is not None else 0.0


def test_the_key_fetch_goes_through_the_guard(dns):
    dns.answers["inside.example.org"] = ["10.9.8.7"]
    seen = []

    def handler(req):
        seen.append(str(req.url))
        return httpx.Response(200, json={"keys": []})
    before = _refused("registry_jwks", "private")
    with pytest.raises(dr.JwksUnavailable) as e:
        asyncio.run(dr.fetch_jwks("https://inside.example.org", inner=httpx.MockTransport(handler)))
    assert e.value.reason.startswith("refused") and seen == []
    assert _refused("registry_jwks", "private") == before + 1


def test_the_key_fetch_reads_the_well_known_path_and_bounds_it(dns, monkeypatch):
    dns.answers["eu.example.org"] = [PUBLIC]
    seen = []

    def handler(req):
        seen.append((req.url.host, req.headers.get("host"), req.url.path))
        return httpx.Response(200, json={"keys": [EU.jwk()]})
    got = asyncio.run(dr.fetch_jwks(EU_URL, inner=httpx.MockTransport(handler)))
    assert got["keys"][0]["kid"] == "eu-k1"
    assert seen == [(PUBLIC, "eu.example.org", "/.well-known/registry-jwks.json")]
    monkeypatch.setattr(dr, "JWKS_MAX_BYTES", 100)
    big = httpx.MockTransport(lambda req: httpx.Response(200, content=b"{" + b" " * 500 + b"}"))
    with pytest.raises(dr.JwksUnavailable) as e:
        asyncio.run(dr.fetch_jwks(EU_URL, inner=big))
    assert e.value.reason == "too_large"


@pytest.mark.parametrize("body", [b"not json", b"[1,2]", b'{"keys": "x"}'])
def test_a_key_set_that_is_not_one_is_refused(dns, body):
    dns.answers["eu.example.org"] = [PUBLIC]
    with pytest.raises(dr.JwksUnavailable) as e:
        asyncio.run(dr.fetch_jwks(EU_URL, inner=httpx.MockTransport(lambda req: httpx.Response(200, content=body))))
    assert e.value.reason == "not_a_key_set"


# --- the database is only read -------------------------------------------------------------------------------------------

def test_reading_peers_only_selects():
    from sqlalchemy.dialects import postgresql
    sql = str(dr.peers_stmt().compile(dialect=postgresql.dialect())).lower()
    assert sql.lstrip().startswith("select") and "peer_registries" in sql
    for verb in ("insert", "update", "delete"):
        assert verb not in sql


# --- the route ---------------------------------------------------------------------------------------------------------

def _app(monkeypatch, *, index=None, error=None, configured=True):
    from fastapi import FastAPI
    from agentvault_registry import database
    from agentvault_registry.routers import public_directory as route

    async def index_rows():
        if error:
            raise dr.IndexUnavailable(error)
        return index or []

    async def peers(_db):
        return []

    async def redis():
        return FakeRedis()

    async def fetch_jwks(origin, inner=None):
        return {"keys": [EU.jwk()]}
    monkeypatch.setattr(dr, "index_registries", index_rows)
    monkeypatch.setattr(dr, "load_peers", peers)
    monkeypatch.setattr(dr, "redis_handle", redis)
    monkeypatch.setattr(dr, "fetch_jwks", fetch_jwks)
    monkeypatch.setenv("DIRECTORY_MTLS_URL", "https://directory.example.org:8443" if configured else "")
    app = FastAPI()
    app.include_router(route.router)

    class _Db:
        async def rollback(self):
            pass

    async def get_db():
        yield _Db()
    app.dependency_overrides[database.get_db] = get_db
    return app


def _get(app, path):
    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://reg.test") as c:
            return await c.get(path)
    return asyncio.run(go())


def test_the_route_serves_the_verified_list(monkeypatch):
    eu = EU.sign(_card("eu-registry", "eu.theprotocol.cloud", EU_URL))
    resp = _get(_app(monkeypatch, index=[_row(eu)]), "/api/v1/public/directory/registries")
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is True and body["registries"][0]["verified"] is True
    assert body["registries"][0]["relation"] == "candidate"


def test_a_broken_index_is_reported_as_broken_never_as_an_empty_list(monkeypatch):
    resp = _get(_app(monkeypatch, error="the federated index is unreachable"), "/api/v1/public/directory/registries")
    assert resp.status_code == 502 and "unreachable" in resp.json()["error"]
    assert "registries" not in resp.json()


def test_no_index_configured_says_so(monkeypatch):
    resp = _get(_app(monkeypatch, configured=False), "/api/v1/public/directory/registries")
    assert resp.status_code == 200 and resp.json() == {"configured": False, "registries": []}


# --- an index older than the read path, and one that refuses the query --------------------------------------------------

def test_an_index_that_serves_no_cards_yet_still_lists_its_registries_each_unverified(monkeypatch):
    """The registry may ship before the Directory that serves `card`: its rows are listed, each unverified, and why."""
    asked = []

    async def ask(query):
        asked.append(query)
        if query == dr.INDEX_QUERY:      # (cardEpoch is in both queries; only the first asks for card)
            return {"errors": [{"message": "Cannot query field 'card' on type 'Registry'."}]}
        return {"data": {"registries": [{"name": "eu-registry", "publicUrl": EU_URL, "reachable": True}]}}
    monkeypatch.setattr(dr, "_ask_index", ask)
    rows = asyncio.run(dr.index_registries())
    assert asked == [dr.INDEX_QUERY, dr.INDEX_QUERY_NO_CARD]
    out = _run(rows, keys={EU_URL: [EU.jwk()]})
    r = out["registries"][0]
    assert r["verified"] is False and r["reason"] == "the index serves no cards (an older Directory)"
    assert r["index"]["name"] == "eu-registry"


def test_an_index_that_refuses_the_query_is_unavailable_with_its_reason(monkeypatch):
    async def ask(query):
        return {"errors": [{"message": "the reader gate refused this caller"}]}
    monkeypatch.setattr(dr, "_ask_index", ask)
    with pytest.raises(dr.IndexUnavailable) as e:
        asyncio.run(dr.index_registries())
    assert "reader gate refused" in str(e.value)


def test_the_route_keeps_its_answer_for_a_while(monkeypatch):
    eu = EU.sign(_card("eu-registry", "eu.theprotocol.cloud", EU_URL))
    app = _app(monkeypatch, index=[_row(eu)])
    shared, calls = FakeRedis(), []

    async def redis():
        return shared

    async def rows():
        calls.append(1)
        return [_row(eu)]
    monkeypatch.setattr(dr, "redis_handle", redis)
    monkeypatch.setattr(dr, "index_registries", rows)
    a = _get(app, "/api/v1/public/directory/registries").json()
    b = _get(app, "/api/v1/public/directory/registries").json()
    assert a == b and len(calls) == 1 and a["index_serves_cards"] is True
