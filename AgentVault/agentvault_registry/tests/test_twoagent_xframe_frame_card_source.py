"""§TWOAGENT (2026-09-23) — A FRAME-HOMED MIRROR'S CARD SOURCE MUST RESOLVE TO THE FRAME.

Two agents tried to sign a cross-frame contract (EU client, ASIA provider) through the §XHIRE door,
`POST /api/v1/contracts/v2/engage/{did}`, with `CONTRACTS_XFRAME_MODE=enforce` on both frames and the provider's
`engagement` block mirrored on EU. It answered 409 "This agent is homed on ASIA. Contracts with agents on another
registry are not wired here yet" — because `_foreign_contract_home` asks `resolve_peer_name` about the mirror's
`federation_metadata.source_registry`, which on EVERY ASIA-homed mirror EU holds is

    spiffe://asia.theprotocol.cloud/registry/asia

and no branch knew that shape: the name/base_url/spiffe_id lookups are exact (and a runner-built frame's peer row
carries no spiffe_id), the §XFRAMETD trust-domain branch reads only `/service/` paths, and the slug branch reads
`/operator/<slug>/` and `/service/registry-<x>`. Operators were fine, so the half that worked hid the half that did
not, again. Frame-to-frame contracts were dead in BOTH directions (ASIA's mirrors of EU say `/registry/eu`).

The branch resolves a `spiffe://<td>/registry/<name>` source only when BOTH the name and the trust domain match a
peer row, ACTIVE first — a SVID from another trust domain carrying the slug resolves to nothing.

RED on the pre-change tree: the first two tests (None there).
"""
import asyncio
import pathlib
import sqlite3
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# eu-registry peer table, live 2026-09-23 (the ghost `ASIA` row is deactivated, never deleted)
EU_PEERS = [
    ("ASIA",      "INACTIVE", "frame",          "https://asia.theprotocol.cloud",              None, "asia.theprotocol.cloud"),
    ("amsterdam", "ACTIVE",   "cloud_operator", "https://amsterdam.op.theprotocol.cloud:8443",
     "spiffe://eu.theprotocol.cloud/operator/amsterdam/registry", "eu.theprotocol.cloud"),
    ("asia",      "ACTIVE",   "frame",          "https://asia.theprotocol.cloud:8443",         None, "asia.theprotocol.cloud"),
    ("hochiminh", "ACTIVE",   "discovered",     "https://hochiminh.op.theprotocol.cloud:8443", None, "asia.theprotocol.cloud"),
    ("lisbon",    "ACTIVE",   "cloud_operator", "https://lisbon.op.theprotocol.cloud:8443",
     "spiffe://eu.theprotocol.cloud/operator/lisbon/registry", "eu.theprotocol.cloud"),
    ("shenzhen",  "ACTIVE",   "discovered",     "https://shenzhen.op.theprotocol.cloud:8443",  None, "asia.theprotocol.cloud"),
]
# sbx-alpha-registry, live 2026-09-23: the frame row is the DISPLAY name, the card source carries its slug
SBX_ALPHA_PEERS = [
    ("Sandbox Beta", "ACTIVE", "frame", "https://sandbox-b.theprotocol.cloud:8443", None, "sandbox-b.theprotocol.cloud"),
    ("sbxbetaop", "ACTIVE", "discovered", "https://sbxbetaop.op.theprotocol.cloud:8443", None, "sandbox-b.theprotocol.cloud"),
    ("Northwind Cooperative", "INACTIVE", "frame", "https://northwind.theprotocol.cloud:28443", None, "northwind.theprotocol.cloud"),
]
# asia-registry, the mirror image
ASIA_PEERS = [
    ("EU",   "INACTIVE", "frame", "https://eu.theprotocol.cloud",      None, "eu.theprotocol.cloud"),
    ("eu",   "ACTIVE",   "frame", "https://eu.theprotocol.cloud:8443", None, "eu.theprotocol.cloud"),
    ("shenzhen", "ACTIVE", "cloud_operator", "https://shenzhen.op.theprotocol.cloud:8443",
     "spiffe://asia.theprotocol.cloud/operator/shenzhen/registry", "asia.theprotocol.cloud"),
]


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class _Session:
    """Runs the resolver's REAL SQL on sqlite (the same `:name` placeholders text() emits)."""

    def __init__(self, peers):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("CREATE TABLE peer_registries (name TEXT, status TEXT, peer_type TEXT, "
                          "base_url TEXT, spiffe_id TEXT, trust_domain TEXT)")
        self.conn.executemany("INSERT INTO peer_registries VALUES (?,?,?,?,?,?)", peers)

    async def execute(self, clause, params=None):
        return _Result(self.conn.execute(str(clause), params or {}).fetchall())


def _resolve(peers, value):
    from agentvault_registry.services import contract_xframe as xf
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(xf.resolve_peer_name(_Session(peers), value))
    finally:
        loop.close()


def test_eu_resolves_an_asia_homed_mirrors_card_source_to_the_active_frame_row():
    assert _resolve(EU_PEERS, "spiffe://asia.theprotocol.cloud/registry/asia") == "asia"   # not the INACTIVE 'ASIA' ghost


def test_asia_resolves_an_eu_homed_mirrors_card_source():
    assert _resolve(ASIA_PEERS, "spiffe://eu.theprotocol.cloud/registry/eu") == "eu"


def test_case_does_not_matter():
    assert _resolve(EU_PEERS, "SPIFFE://ASIA.theprotocol.cloud/registry/ASIA") == "asia"


def test_a_foreign_trust_domain_carrying_the_slug_resolves_to_nothing():
    assert _resolve(EU_PEERS, "spiffe://evil.example/registry/asia") is None


def test_an_unknown_frame_name_resolves_to_nothing():
    assert _resolve(EU_PEERS, "spiffe://asia.theprotocol.cloud/registry/nope") is None


def test_the_operator_shape_still_resolves_to_the_operator():
    assert _resolve(EU_PEERS, "spiffe://eu.theprotocol.cloud/operator/amsterdam/registry") == "amsterdam"


def test_a_display_named_frame_row_matches_its_slug():
    assert _resolve(SBX_ALPHA_PEERS, "spiffe://sandbox-b.theprotocol.cloud/registry/sandbox-beta") == "Sandbox Beta"


def test_the_slug_form_still_binds_the_trust_domain():
    assert _resolve(SBX_ALPHA_PEERS, "spiffe://sandbox-a.theprotocol.cloud/registry/sandbox-beta") is None
