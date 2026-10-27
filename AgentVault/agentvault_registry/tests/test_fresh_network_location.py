"""§DIDWIDEN follow-up (2026-09-06): the fresh-network entry takes a frame's location from the registry card's
OPERATOR block (the only place a card carries one), never from an identity.location that no card has."""
import asyncio


from agentvault_registry.routers import public_fresh_network as pfn


def _facts(monkeypatch, card):
    async def fake_get_json(client, url):
        return card if url.endswith("/.well-known/registry-card.json") else None
    monkeypatch.setattr(pfn, "_get_json", fake_get_json)
    return asyncio.run(pfn._frame_facts(object(), {"name": "EU", "slug": "eu", "registry_url": "https://eu.example", "es_url": "", "ws_path": "/ws/events"}))


def test_location_comes_from_the_operator_block(monkeypatch):
    card = {"identity": {"registry_name": "EU", "software_version": "V0228"},
            "operator": {"location_label": "Brussels, Belgium", "latitude": 50.8503, "longitude": 4.3517}}
    out = _facts(monkeypatch, card)
    assert out["reachable"] is True
    assert out["location"] == "Brussels, Belgium"
    assert (out["latitude"], out["longitude"]) == (50.8503, 4.3517)


def test_a_card_without_a_location_reads_none_not_a_crash(monkeypatch):
    out = _facts(monkeypatch, {"identity": {"registry_name": "X"}})
    assert out["location"] is None and out["latitude"] is None and out["longitude"] is None


def test_an_unreachable_frame_stays_honest(monkeypatch):
    out = _facts(monkeypatch, None)
    assert out["reachable"] is False and out["location"] is None


def test_the_strip_passes_through_and_defaults_to_main(monkeypatch):
    """§AGORASIM-2: the landing page files a frame under a folded ledger strip by this field."""
    async def fake_get_json(client, url):
        return None
    monkeypatch.setattr(pfn, "_get_json", fake_get_json)
    base = {"name": "Sandbox Alpha", "slug": "sbx-alpha", "registry_url": "", "es_url": "", "ws_path": "/ws/events-sbxalpha"}
    run = lambda e: asyncio.run(pfn._frame_facts(object(), e))  # noqa: E731
    assert run({**base, "strip": "sandbox"})["strip"] == "sandbox"
    assert run({**base, "strip": " Sandbox "})["strip"] == "sandbox"
    assert run(base)["strip"] == "main"
    assert run({**base, "strip": "prod"})["strip"] == "main"

