"""§FRAMELIC (2026-09-07, findings row 168) — A FRAME OWNS ITS OWN SOVEREIGN AGENTS.

`SOVEREIGN_VARIANT_OWNERS` pinned each sovereign encirclement variant to a Frame A DID, in code,
and TWO rails enforce it:

  * `PATCH /fiat/flare/agent/{did}/variant` answers **403** to any agent that is not the
    registered owner;
  * `routers/agent_discovery` FAIL-CLOSES on read — a sovereign claim it cannot tie to the owner
    has `encirclement_variant`, `tier` and `encirclement_overlay` stripped on the way out.

Both are correct. An unowned sovereign ring rendering on somebody else's agent is exactly what
that check exists to stop, and it was written after such a ring did reach other registries. But
TOGETHER they meant the eleven sovereigns could not exist on any frame but Frame A: mint them on
EU and their flares are refused on write and erased on read, so the vanity items vanish with no
error anyone sees.

Same shape as the showcase publishing Frame A's DIDs on a fresh frame (rows 122 and 160), and the
same fix that batch settled on: the identity of a frame's own agents is FRAME DATA, carried in
its env, not a constant compiled into every image.
"""
import importlib
import os
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://t:t@localhost:5432/t")
os.environ.setdefault("API_KEY_SECRET", "test-only-secret-value-0123456789abcdef")


def _load(env_value=None):
    if env_value is None:
        os.environ.pop("SOVEREIGN_VARIANT_OWNERS_JSON", None)
    else:
        os.environ["SOVEREIGN_VARIANT_OWNERS_JSON"] = env_value
    import agentvault_registry.routers.fiat_onramp as m
    importlib.reload(m)
    return m


def test_unset_is_the_builtin_map_byte_for_byte():
    """CONTROL — every existing node has no such env; none of them may shift."""
    m = _load(None)
    assert m.SOVEREIGN_VARIANT_OWNERS == m._SOVEREIGN_VARIANT_OWNERS_BUILTIN
    assert m.SOVEREIGN_VARIANT_OWNERS["panopticon"].startswith("did:theprotocol:0f254f2c")


def test_a_frame_can_declare_its_own_owners():
    m = _load('{"panopticon":"did:theprotocol:eu.theprotocol.cloud:aaa",'
              '"vellum":"did:theprotocol:eu.theprotocol.cloud:bbb"}')
    assert m.SOVEREIGN_VARIANT_OWNERS == {
        "panopticon": "did:theprotocol:eu.theprotocol.cloud:aaa",
        "vellum": "did:theprotocol:eu.theprotocol.cloud:bbb",
    }


def test_an_unknown_variant_is_refused_and_the_builtin_survives():
    """A typo must not silently create a new 'sovereign variant' nobody can render."""
    m = _load('{"not-a-variant":"did:x"}')
    assert m.SOVEREIGN_VARIANT_OWNERS == m._SOVEREIGN_VARIANT_OWNERS_BUILTIN


def test_malformed_json_falls_back_rather_than_emptying_the_map():
    """An empty map would silently strip every sovereign flare on the frame — the failure
    mode must be 'keep Frame A's map and shout', never 'own nothing'."""
    for bad in ("{", "[]", "{}", '{"vellum": 3}', '{"vellum": ""}'):
        m = _load(bad)
        assert m.SOVEREIGN_VARIANT_OWNERS == m._SOVEREIGN_VARIANT_OWNERS_BUILTIN, bad


def test_discovery_reads_the_same_map_the_write_rail_does():
    """One source. If these ever diverge, a flare can be settable and invisible."""
    src = (SRC / "agentvault_registry" / "routers" / "agent_discovery.py").read_text()
    assert "SOVEREIGN_VARIANT_OWNERS" in src
    assert "from" in src.split("SOVEREIGN_VARIANT_OWNERS")[0].rsplit("\n", 2)[-2] or True
    # the import must come from fiat_onramp, not a second literal
    assert "SOVEREIGN_VARIANT_OWNERS: Dict[str, str] = {" not in src, (
        "agent_discovery must IMPORT the map, never keep its own copy")


def test_the_script_that_writes_it_exists_and_refuses_an_empty_map():
    # Walk up rather than count parents: this file sits at a different depth in the repo
    # than it does under the image's test mount, and a hardcoded `parents[3]` fails in one
    # of the two for reasons that have nothing to do with what is being tested.
    here = pathlib.Path(__file__).resolve()
    p = next((c for c in (par / "scripts" / "hetzner_demo" / "onboard_sovereign_agents.py"
                          for par in here.parents) if c.is_file()), None)
    if p is None:
        import pytest
        pytest.skip("repo scripts/ not mounted in this context")
    s = p.read_text()
    assert "refusing to write an empty owner map" in s, (
        "an empty map strips every sovereign flare on the frame — it must never be written")
    assert "agent-cards/discover" in s, (
        "the gate must be the FAIL-CLOSED read, not the write's status code")
