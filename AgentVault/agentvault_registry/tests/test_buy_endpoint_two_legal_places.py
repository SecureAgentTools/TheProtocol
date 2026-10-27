"""§BATCH4 — the buy/quote rail's endpoint comes from either legal place on a card.
A2A v1.0 cards carry the endpoint in `supportedInterfaces[0].url` (no top-level `url`); the shared row builder
`effective_pricing_for_did` read only the legacy `url`, so the buy rail answered "This card declares no A2A
endpoint to call" for SYBIL (measured 2026-09-05) while its stored card carried the endpoint. Source-pinned
beside the SQL: the ONE rule reads both, legacy first, exactly like `_well_known_url_for` in the pull-sync."""
import pathlib, re
SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
if not SRC.is_dir():
    SRC = pathlib.Path("/w/src/agentvault_registry")

def test_endpoint_url_reads_legacy_url_then_first_interface():
    s = (SRC / "routers/agent_cards.py").read_text()
    m = re.search(r"COALESCE\(NULLIF\(s\.card_data->>'url',''\), s\.card_data->'supportedInterfaces'->0->>'url'\) AS endpoint_url", s)
    assert m, "endpoint_url must read the legacy url and fall back to supportedInterfaces[0].url"
    assert "s.card_data->>'url'  AS endpoint_url" not in s, "the legacy-only derivation survived"

def test_pull_sync_reads_the_same_interface_field():
    s = (SRC / "background_tasks/agent_card_pullsync.py").read_text()
    assert "supportedInterfaces" in s, "the pull-sync's well-known resolver names the same field"
