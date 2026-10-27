"""§BATCH9 (2026-09-06) — the AGORA ticker's default venue list.

His bug report: the JUICE landing page's AGORA strip rendered registry-a's market. Cause: the
default in `_venue_probe_urls()` treated ANY deployment with an EventStore-B/C URL configured as
this cluster, and the frame template renders the FX PEER's EventStore as "B". The cluster map now
applies to the three cluster mainframes by name only; everyone else resolves SELF + the venues its
own ACTIVE peers advertise on their cached cards, probed at the card's public url.

Controls both ways: a JUICE-shaped env must NOT reach the cluster map (RED before the fix); a
Registry-A-shaped env MUST (the production behaviour is unchanged); and the peer-derived resolver
includes exactly the venue-capable ACTIVE peers.
"""
import types

import pytest

from agentvault_registry.routers import exchange as ex


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("EXCHANGE_TICKER_SOURCES_JSON", "EVENT_STORE_B_URL", "EVENT_STORE_C_URL",
              "REGISTRY_NAME", "REGISTRY_FEDERATION_NAME", "EXCHANGE_ENABLED"):
        monkeypatch.delenv(k, raising=False)


def _values(urls):
    return " ".join(urls.values())


def test_a_peer_eventstore_does_not_make_a_cluster_mainframe(monkeypatch):
    monkeypatch.setenv("REGISTRY_NAME", "JUICE")
    monkeypatch.setenv("EVENT_STORE_B_URL", "https://brrr-es.example.test")   # the FX peer's ES, as the template renders it
    urls = ex._venue_probe_urls()
    assert "api.theprotocol.cloud" not in _values(urls), urls
    assert "frame-b" not in urls and "frame-c" not in urls
    assert list(urls) == ["juice"] and urls["juice"].startswith("http://localhost")


def test_the_cluster_mainframes_still_get_the_map(monkeypatch):
    monkeypatch.setenv("REGISTRY_NAME", "Registry-A")
    urls = ex._venue_probe_urls()
    assert set(urls) == {"registry-a", "frame-b", "frame-c"}
    assert urls["registry-a"].startswith("http://localhost")            # self points home (§HETZNERLOCK-15)
    assert "frame-c.theprotocol.cloud" in urls["frame-c"]


def test_explicit_env_still_wins(monkeypatch):
    monkeypatch.setenv("REGISTRY_NAME", "JUICE")
    monkeypatch.setenv("EXCHANGE_TICKER_SOURCES_JSON", '{"JUICE": "http://localhost:8000", "BRRR": "https://brrr.example.test"}')
    assert ex._venue_probe_urls() == {"JUICE": "http://localhost:8000", "BRRR": "https://brrr.example.test"}


class _Rows:
    def __init__(self, rows): self._rows = rows
    def scalars(self): return self
    def all(self): return self._rows


class _Db:
    def __init__(self, rows):
        self.rows = rows
        self.stmts = []
    async def execute(self, stmt):
        self.stmts.append(stmt)
        return _Rows(self.rows)


def _peer(name, status, base_url, card):
    return types.SimpleNamespace(name=name, status=status, base_url=base_url, cached_registry_card=card)


def _card(enabled, public_url=None):
    c = {"fees": {"exchange": {"enabled": enabled}}, "identity": {}}
    if public_url:
        c["identity"]["public_url"] = public_url
    return c


async def test_federated_resolver_is_self_plus_venue_capable_active_peers(monkeypatch):
    monkeypatch.setenv("REGISTRY_NAME", "JUICE")
    db = _Db([
        _peer("BRRR", "ACTIVE", "https://brrr.example.test:8443", _card(True, "https://brrr.example.test")),
        _peer("brrrop-a", "ACTIVE", "https://brrrop-a.op.example.test", _card(False)),          # passport-only, not a venue
        _peer("juiceop-a", "ACTIVE", "https://juiceop-a.op.example.test:8443", None),         # no card yet
        _peer("ghost", "ACTIVE", "https://ghost.example.test", '{"fees": {"exchange": {"enabled": true}}}'),  # card stored as text
    ])
    urls = await ex._venue_probe_urls_federated(db)
    assert list(urls)[0] == "juice" and urls["juice"].startswith("http://localhost")
    assert urls["BRRR"] == "https://brrr.example.test"
    assert urls["ghost"] == "https://ghost.example.test"                 # text card parsed; port-less base_url kept
    assert "brrrop-a" not in urls and "juiceop-a" not in urls
    compiled = str(db.stmts[0].compile(compile_kwargs={"literal_binds": True}))
    assert "'ACTIVE'" in compiled                                          # only ACTIVE rows are asked


async def test_federated_resolver_strips_the_gateway_port_when_the_card_has_no_public_url(monkeypatch):
    monkeypatch.setenv("REGISTRY_NAME", "JUICE")
    db = _Db([_peer("BRRR", "ACTIVE", "https://brrr.example.test:8443/", _card(True))])
    urls = await ex._venue_probe_urls_federated(db)
    assert urls["BRRR"] == "https://brrr.example.test"


async def test_federated_resolver_defers_to_env_and_to_the_cluster_map(monkeypatch):
    monkeypatch.setenv("REGISTRY_NAME", "Registry-A")
    db = _Db([_peer("BRRR", "ACTIVE", "https://brrr.example.test:8443", _card(True))])
    urls = await ex._venue_probe_urls_federated(db)
    assert db.stmts == [] and set(urls) == {"registry-a", "frame-b", "frame-c"}
    monkeypatch.setenv("REGISTRY_NAME", "JUICE")
    monkeypatch.setenv("EXCHANGE_TICKER_SOURCES_JSON", '{"only": "http://localhost:8000"}')
    urls = await ex._venue_probe_urls_federated(db)
    assert db.stmts == [] and urls == {"only": "http://localhost:8000"}


async def test_an_empty_network_is_self_only_and_never_the_cluster(monkeypatch):
    monkeypatch.setenv("REGISTRY_NAME", "BRRR")
    monkeypatch.setenv("EVENT_STORE_B_URL", "https://juice-es.example.test")
    urls = await ex._venue_probe_urls_federated(_Db([]))
    assert list(urls) == ["brrr"] and "theprotocol.cloud" not in _values(urls)
