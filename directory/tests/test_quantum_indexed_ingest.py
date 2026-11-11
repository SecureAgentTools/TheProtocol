"""V0660 (a) (session-code, 2026-11-08): a native card's quantum workload extension reaches the index at ingest.

EXTRACT_VERSION 5 re-reads every card once, so an extension the read did not take before is seen. It imports
`directory.ingest`, which imports the registry's readers, so it runs in the directory image (REQUIRES_REGISTRY).
RED on origin/master (ad4e9748): the extract version is 4 and nothing is taken from the extension.
"""
REQUIRES_REGISTRY = True

import asyncio

import directory.ingest as ing
from directory.schema import schema
from directory.store import Store

BASE = "https://eu.theprotocol.cloud"
URI = "https://theprotocol.cloud/extensions/v1/quantum/workload"


def test_a_native_cards_quantum_extension_is_indexed_and_answered(tmp_path):
    assert ing.EXTRACT_VERSION >= 5, "a field the read gained is seen only when every card is read again"
    store = Store(str(tmp_path / "d.db"))
    store.upsert_registry(name="EU", trust_domain="eu.td", tier="frame", public_url=BASE, did_namespace=None, verified=1,
                          reason=None, reachable=1, card_epoch=None, location=None, latitude=None, longitude=None,
                          parent_name=None, federation_status=None, hop=0, last_sync_at=0, last_error=None,
                          agents_indexed=0, card_json=None, currency="ECU")
    cd = {"name": "q1", "extensions": [{"uri": URI, "params": {
        "version": "1.0", "roles": ["provider"],
        "backends": [{"id": "sv", "kind": "simulator", "modality": "simulator", "qubits": {"physical": 24},
                      "formats": ["openqasm3"], "location": {"jurisdiction": "DE"}}],
        "evidence": {"verification_rungs": [1]}}}]}

    async def fake_fetch(client, url, **kw):
        if "/agent-cards/?" in url:
            return {"applied_filters": {"natives_only": True},
                    "items": [{"id": "c1", "updated_at": "2026-11-08T00:00:00", "agent_did": "did:x:1"}]}, None
        return {"card_data": cd, "updated_at": "2026-11-08T00:00:00", "is_active": True, "name": "q1",
                "agent_did": "did:x:1"}, None
    orig = ing.fetch_json
    ing.fetch_json = fake_fetch
    try:
        asyncio.run(ing.pull_cards(None, store, {"base": BASE, "name": "EU", "trust_domain": "eu.td", "verified": True},
                                   full=True))
    finally:
        ing.fetch_json = orig
    out = schema.execute_sync('{ agents(quantumOnly: true) { edges { name quantum { modalities maxQubits rungs } } } }',
                              context_value={"store": store})
    assert not out.errors, out.errors
    assert out.data["agents"]["edges"] == [{"name": "q1", "quantum": {"modalities": ["simulator"], "maxQubits": 24,
                                                                       "rungs": [1]}}]
