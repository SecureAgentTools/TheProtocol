"""2026-10-17 (his word: "no operator accepted without record ... record must exist first"): the trust sync names each of
this frame's own operators by its OWN SVID, never by the frame's bare trust domain.

SF-5B's trust sync sends one update per licence this frame issued, and since §TRUSTROW it names the peer as spiffe_id so
the event store can find the row the vote reads. It named every peer spiffe://<peer.trust_domain>, and an operator's
peer row carries the frame's OWN trust domain: every operator of the frame was sent the same bare id. The store finds a
row by that id first and overwrites the row's identity, so one row per frame took every same-domain operator's update
every two minutes, its name flipping (measured on the live stores: lisbon's row on EU and shenzhen's on ASIA carry the
bare domain, sbxalphaop's and sbxbetaop's on the sandbox; the EU store logged 59 updates in 30 minutes), and a store
that accepts no operator without its record refuses those operators.

What these tests pin, on rows shaped like EU's (its operator peers are typed cloud_operator and stamped at activation
with spiffe://<td>/operator/<name>/registry; its licences are the ones measured there):
  1. each own operator is sent spiffe://<td>/operator/<name>/svid-writer, the SVID its registry and its TEG present to
     the store (both mount the cert-writer's /certs) and the identity the provisioner's licence sync leaves on its row;
     no payload carries the bare domain, and no two payloads share an identity;
  2. an operator whose row carries no stamp, or a stamp of another domain, is sent NO identity (the store then finds its
     row by the licence id alone and leaves the row's identity alone): no identity rather than a wrong one;
  3. a peer in this frame's own domain is an operator whatever its type, so it is never sent the bare domain either;
  4. a peer frame keeps its domain identity, as §TRUSTROW decided;
  5. the pass itself (_sync_trust_to_eventstore) posts exactly that, taking this frame's domain from SPIRE_TRUST_DOMAIN.
RED on 8887e1da: every own operator's payload carries spiffe://eu.theprotocol.cloud.
Run: python -m pytest tests/test_trust_sync_operator_identity.py -q
"""
import asyncio
import inspect
from types import SimpleNamespace as Peer

from agentvault_registry.background_tasks import federation_sync as fs

EU = "eu.theprotocol.cloud"
ASIA = "asia.theprotocol.cloud"
BARE_EU = f"spiffe://{EU}"
LICENCES = [  # as measured in EU's federation_licenses (id, operator_name, status)
    ("73f0193f-64fb-454f-abac-004693f274e1", "ASIA", "active"),
    ("bc13aed3-b61c-4551-b3df-4e93b1f1958c", "Hansa Freight", "revoked"),
    ("fa43d7b6-a25b-48fc-a7a5-5afc52357a67", "amsterdam", "active"),
    ("d2197a61-7d0f-423a-8aa5-b01649057dd6", "lisbon", "active"),
]


def operator(name, discount=0.9, trust_domain=EU, stamp="registry", peer_type="cloud_operator"):
    sid = None if stamp is None else (stamp if stamp.startswith("spiffe://") else f"spiffe://{EU}/operator/{name}/{stamp}")
    return Peer(name=name, peer_type=peer_type, trust_domain=trust_domain, spiffe_id=sid, bayesian_discount=discount)


def eu_peers():
    return [
        operator("amsterdam", 0.9375),
        operator("lisbon", 0.9996),
        Peer(name="asia", peer_type="frame", trust_domain=ASIA, spiffe_id=None, bayesian_discount=0.97),
        Peer(name="shenzhen", peer_type="discovered", trust_domain=ASIA, spiffe_id=None, bayesian_discount=0.5),
    ]


def payloads_for(peers, own=EU):
    """trust_sync_payloads with this frame's own domain when the function takes one (the base takes none, so its
    control fails on what it sends, not on its signature)."""
    if "own_trust_domain" in inspect.signature(fs.trust_sync_payloads).parameters:
        return fs.trust_sync_payloads(peers, LICENCES, own_trust_domain=own)
    return fs.trust_sync_payloads(peers, LICENCES)


def by_name(payloads):
    return {p["operator_name"]: p for p in payloads}


def test_red_each_own_operator_is_named_by_its_own_svid():
    payloads, skipped = payloads_for(eu_peers())
    got = by_name(payloads)
    assert skipped == ["shenzhen"]
    assert got["amsterdam"]["id"] == "fa43d7b6-a25b-48fc-a7a5-5afc52357a67"
    assert got["lisbon"]["id"] == "d2197a61-7d0f-423a-8aa5-b01649057dd6"
    assert got["amsterdam"].get("spiffe_id") == f"spiffe://{EU}/operator/amsterdam/svid-writer", got["amsterdam"]
    assert got["lisbon"].get("spiffe_id") == f"spiffe://{EU}/operator/lisbon/svid-writer", got["lisbon"]
    assert all(p.get("spiffe_id") != BARE_EU for p in payloads), payloads


def test_red_no_two_payloads_share_an_identity():
    """The collapse condition itself: two payloads with one id are two operators the store cannot tell apart."""
    payloads, _ = payloads_for(eu_peers())
    ids = [p["spiffe_id"] for p in payloads if "spiffe_id" in p]
    assert len(ids) == len(set(ids)), ids


def test_red_an_operator_without_a_stamp_is_sent_no_identity():
    payloads, _ = payloads_for([operator("lisbon", 0.9, stamp=None)])
    assert len(payloads) == 1
    assert "spiffe_id" not in payloads[0], payloads[0]


def test_red_a_stamp_of_another_domain_is_not_sent():
    foreign = "spiffe://agentvault.com/operator/lisbon/registry"
    for peer in (operator("lisbon", 0.9, stamp=foreign),                        # the peer's own domain says otherwise
                 operator("lisbon", 0.9, stamp=foreign, trust_domain=None)):    # this frame's domain says otherwise
        payloads, _ = payloads_for([peer])
        assert len(payloads) == 1
        assert "spiffe_id" not in payloads[0], (peer, payloads[0])


def test_red_a_peer_in_our_own_domain_is_an_operator_whatever_its_type():
    for peer_type in ("direct_peer", "discovered", None):
        payloads, _ = payloads_for([operator("lisbon", 0.9, stamp=None, peer_type=peer_type)])
        assert len(payloads) == 1
        assert payloads[0].get("spiffe_id") != BARE_EU, (peer_type, payloads[0])
        assert "spiffe_id" not in payloads[0], (peer_type, payloads[0])


def test_a_stamp_is_read_whatever_workload_it_names_and_the_svid_writer_is_sent():
    payloads, _ = payloads_for([operator("lisbon", 0.9, stamp="svid-writer"), operator("amsterdam", 0.9, stamp="teg")])
    assert {p["spiffe_id"] for p in payloads} == {f"spiffe://{EU}/operator/lisbon/svid-writer",
                                                   f"spiffe://{EU}/operator/amsterdam/svid-writer"}


def test_a_peer_frame_keeps_its_domain_identity():
    payloads, _ = payloads_for(eu_peers())
    assert by_name(payloads)["ASIA"]["spiffe_id"] == f"spiffe://{ASIA}"
    # and with no own domain configured, a frame is still a frame
    payloads, _ = payloads_for([Peer(name="asia", peer_type="frame", trust_domain=ASIA, spiffe_id=None,
                                     bayesian_discount=0.97)], own="")
    assert payloads[0]["spiffe_id"] == f"spiffe://{ASIA}"


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _Db:
    async def execute(self, stmt):
        return _Rows(LICENCES)

    async def commit(self):
        pass


class _Client:
    posted = []

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None):
        _Client.posted.append((url, json))
        return Peer(status_code=200)


def test_red_the_pass_posts_each_operator_under_its_own_identity(monkeypatch):
    monkeypatch.setenv("EVENT_STORE_API_KEY", "trust-sync-test-key-not-a-secret")
    monkeypatch.setenv("EVENT_STORE_URL", "https://nginx-event-store:8443")
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", EU)
    monkeypatch.setattr(fs.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(fs, "get_httpx_verify", lambda: True)
    _Client.posted = []
    asyncio.run(fs.FederationSyncWorker._sync_trust_to_eventstore(None, _Db(), eu_peers()))
    sent = {body["operator_name"]: body for url, body in _Client.posted}
    assert all(url == "https://nginx-event-store:8443/api/v1/events/operators/sync" for url, _ in _Client.posted)
    assert set(sent) == {"amsterdam", "lisbon", "ASIA"}, sent
    assert sent["lisbon"].get("spiffe_id") == f"spiffe://{EU}/operator/lisbon/svid-writer", sent["lisbon"]
    assert sent["amsterdam"].get("spiffe_id") == f"spiffe://{EU}/operator/amsterdam/svid-writer", sent["amsterdam"]
    assert sent["ASIA"]["spiffe_id"] == f"spiffe://{ASIA}"
    assert all(b.get("spiffe_id") != BARE_EU for b in sent.values())
