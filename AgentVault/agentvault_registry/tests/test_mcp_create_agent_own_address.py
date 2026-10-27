"""§TESTBED (2026-09-19): an MCP-made agent card names the frame that made it, never the network's apex.

tools_developer.create_agent hardcoded https://theprotocol.cloud/agents/<slug> and the apex's token URL, so a kit frame
advertised our apex and probed it for every such agent. Pinned on the source: the literal survives only as the fallback
for a node whose public address is unknown.
"""
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry" / "mcp" / "tools_developer.py"


def test_the_card_urls_are_built_from_this_frames_public_address():
    s = SRC.read_text()
    assert 'service_url = f"{_base}/agents/{human_readable_id}"' in s
    assert 'token_url = f"{_base}/api/v1/auth/agent/token"' in s
    assert 'public_base_url_static() or "https://theprotocol.cloud"' in s
    assert 'service_url = f"https://theprotocol.cloud/agents/' not in s
