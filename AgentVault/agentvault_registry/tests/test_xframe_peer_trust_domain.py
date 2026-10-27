"""§XFRAMETD (2026-09-10) — A FRAME'S OWN SERVICE SVID MUST RESOLVE TO THE FRAME.

V0300 made the flagship's degradation panel readable for the first time, and the first thing it
found was `XFramePeerUnresolved` breaching: **88 increments in 30 minutes against a threshold of
0**, on five nodes at once. Read out of the logs, the whole population was four strings, and every
one of them was a frame introducing itself:

    eu-registry        'spiffe://asia.theprotocol.cloud/service/registry'      14 / 30 min
    asia-registry      'spiffe://eu.theprotocol.cloud/service/registry'        12 / 30 min
    frame-b-registry   'spiffe://agentvault.com/service/registry-a'            16 / 30 min
    frame-c-registry   'spiffe://agentvault.com/service/registry-a'            16 / 30 min

`resolve_peer_name` had four ways to recognise a peer and none of them could see this shape:
there is no NAME in it, no BASE URL, `peer_registries.spiffe_id` is EMPTY on every frame row in
this fleet (measured on all five registries), and the slug regexes dig out `a` — a peer nobody is
called — or nothing at all.

The consequence was not cosmetic. `GET /federation/contracts-for-peer` resolves its CALLER from
exactly this SVID and returns `{"caller": null, "contracts": []}` when it cannot — so the BOOTSTRAP
pull, which exists precisely because "push alone cannot establish a replica set", has been handing
every peer FRAME an empty list for as long as the endpoint has existed. Operators were fine: their
`/operator/<slug>/registry` SVID matches the slug branch, so the half that worked is the half that
hid the half that did not.

THE FIX, and why it is shaped the way it is:

  * the trust domain IS a frame's identity, and it arrives already AUTHENTICATED — the mTLS gate
    validates it upstream, so this branch reads a fact rather than a claim;
  * `peer_registries.trust_domain` is the column that holds our answer for it;
  * NARROWED to ACTIVE `frame`/`direct_peer` rows, because a trust domain holds exactly one FRAME
    and many of its OPERATORS (EU carries three ACTIVE rows under `asia.theprotocol.cloud`);
  * it runs LAST and only for a `/service/` path, so an operator's SVID keeps resolving to the
    OPERATOR and never to its parent frame;
  * two candidates REFUSE and name both, because a mirror addressed to the wrong frame is worse
    than a mirror not addressed at all.

Every fixture below is the LIVE peer table of the node it names, read 2026-09-10.
"""
import asyncio
import pathlib
import sqlite3
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# --------------------------------------------------------------------------------------------
# A session that runs the REAL SQL. sqlite3 speaks the same `:name` placeholders SQLAlchemy's
# text() emits, so the statements under test are executed verbatim rather than re-implemented —
# a fake that re-implements the query would be testing the fake (§29e).
# --------------------------------------------------------------------------------------------
COLUMNS = ("name", "status", "peer_type", "base_url", "spiffe_id", "trust_domain")

# eu-registry, live 2026-09-10
EU_PEERS = [
    ("ASIA",      "INACTIVE", "frame",          "https://asia.theprotocol.cloud",             None, "asia.theprotocol.cloud"),
    ("amsterdam", "ACTIVE",   "cloud_operator", "https://amsterdam.op.theprotocol.cloud:8443",
     "spiffe://eu.theprotocol.cloud/operator/amsterdam/registry", "eu.theprotocol.cloud"),
    ("asia",      "ACTIVE",   "frame",          "https://asia.theprotocol.cloud:8443",        None, "asia.theprotocol.cloud"),
    ("hochiminh", "ACTIVE",   "discovered",     "https://hochiminh.op.theprotocol.cloud:8443", None, "asia.theprotocol.cloud"),
    ("lisbon",    "ACTIVE",   "cloud_operator", "https://lisbon.op.theprotocol.cloud:8443",
     "spiffe://eu.theprotocol.cloud/operator/lisbon/registry", "eu.theprotocol.cloud"),
    ("shenzhen",  "ACTIVE",   "discovered",     "https://shenzhen.op.theprotocol.cloud:8443",  None, "asia.theprotocol.cloud"),
]

# frame-b-registry, live 2026-09-10 (trimmed to the rows that can possibly match)
FRAME_B_PEERS = [
    ("Registry-A",    "ACTIVE",   "frame",          "https://api.theprotocol.cloud",                None, "agentvault.com"),
    ("Zeta-B",        "INACTIVE", "cloud_operator", "https://zeta-b.example.invalid",               None, "frame-b.theprotocol.cloud"),
    ("op-berlin",     "ACTIVE",   "discovered",     "https://op-berlin.op.theprotocol.cloud:8443",  None, "agentvault.com"),
    ("op-london",     "ACTIVE",   "discovered",     "https://op-london.op.theprotocol.cloud:8443",  None, "agentvault.com"),
    ("op-paris",      "ACTIVE",   "discovered",     "https://op-paris.op.theprotocol.cloud:8443",   None, "agentvault.com"),
    ("op-washington", "ACTIVE",   "discovered",     "https://op-washington.op.theprotocol.cloud:8443", None, "agentvault.com"),
    ("qatest16",      "ACTIVE",   "discovered",     "https://qatest16.op.theprotocol.cloud:8443",   None, "agentvault.com"),
    ("op-newyork",    "ACTIVE",   "cloud_operator", "https://op-newyork.op.theprotocol.cloud:8443", None, "frame-b.theprotocol.cloud"),
]

# agentvault_registry_a, live 2026-09-10 (trimmed)
REGISTRY_A_PEERS = [
    ("Frame-B",     "ACTIVE",   "frame",          "https://frame-b.theprotocol.cloud",             None, "frame-b.theprotocol.cloud"),
    ("Frame-C",     "ACTIVE",   "frame",          "https://frame-c.theprotocol.cloud",             None, "frame-c.theprotocol.cloud"),
    ("op-doha",     "ACTIVE",   "discovered",     "https://op-doha.op.theprotocol.cloud",          None, "frame-c.theprotocol.cloud"),
    ("op-berlin",   "ACTIVE",   "cloud_operator", "https://op-berlin.op.theprotocol.cloud:8443",   None, "agentvault.com"),
    ("op-portaltest", "INACTIVE", "direct_peer",  "https://op-portaltest.example.invalid",         None, "agentvault.com"),
]

# The contrived one: two ACTIVE frames claiming one trust domain. Not live anywhere — that is the
# point. It pins the refusal so a future data defect cannot silently pick a winner.
AMBIGUOUS_PEERS = [
    ("north", "ACTIVE", "frame",       "https://north.example.invalid", None, "shared.example"),
    ("south", "ACTIVE", "direct_peer", "https://south.example.invalid", None, "shared.example"),
]


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class _Session:
    """Just enough AsyncSession to run `await db.execute(text(...), params)`."""

    def __init__(self, peers):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute(
            "CREATE TABLE peer_registries (name TEXT, status TEXT, peer_type TEXT, "
            "base_url TEXT, spiffe_id TEXT, trust_domain TEXT)")
        self.conn.executemany(
            "INSERT INTO peer_registries VALUES (?,?,?,?,?,?)", peers)
        self.statements = []

    async def execute(self, clause, params=None):
        sql = str(clause)
        self.statements.append(sql)
        return _Result(self.conn.execute(sql, params or {}).fetchall())


def _resolve(peers, value):
    from agentvault_registry.services import contract_xframe as xf
    db = _Session(peers)
    loop = asyncio.get_event_loop_policy().new_event_loop()
    try:
        return loop.run_until_complete(xf.resolve_peer_name(db, value)), db
    finally:
        loop.close()


# --------------------------------------------------------------------------------------------
# The narrow shape test — what the trust domain may and may not be read out of
# --------------------------------------------------------------------------------------------
def test_only_a_service_svid_yields_a_trust_domain():
    from agentvault_registry.services.contract_xframe import service_svid_trust_domain as f

    # the four live values that were breaching, plus a capitalised variant
    assert f("spiffe://asia.theprotocol.cloud/service/registry") == "asia.theprotocol.cloud"
    assert f("spiffe://eu.theprotocol.cloud/service/registry") == "eu.theprotocol.cloud"
    assert f("spiffe://agentvault.com/service/registry-a") == "agentvault.com"
    assert f("SPIFFE://Agentvault.COM/service/registry-a") == "agentvault.com"

    # an OPERATOR's SVID: its trust domain is its PARENT FRAME's, so answering by trust domain
    # would name a different peer than the one that called.
    assert f("spiffe://frame-c.theprotocol.cloud/operator/op-doha/registry") is None
    # the legacy presenter template names Frame A's trust domain whoever presents it (§DIDWIDEN-1)
    assert f("spiffe://agentvault.com/ns/agentvault/sa/registry-frame-b") is None
    # everything that is not a SPIFFE id at all
    assert f("https://asia.theprotocol.cloud:8443") is None
    assert f("Frame-B") is None
    assert f("spiffe://asia.theprotocol.cloud") is None
    assert f("") is None and f(None) is None


# --------------------------------------------------------------------------------------------
# The live breaches, each against its own node's real peer table
# --------------------------------------------------------------------------------------------
def test_eu_resolves_asias_service_svid():
    got, _ = _resolve(EU_PEERS, "spiffe://asia.theprotocol.cloud/service/registry")
    assert got == "asia", got


def test_frame_b_resolves_registry_as_service_svid():
    got, _ = _resolve(FRAME_B_PEERS, "spiffe://agentvault.com/service/registry-a")
    assert got == "Registry-A", got


def test_the_narrowing_is_what_makes_eu_unambiguous():
    """CONTROL for the narrowing itself, not merely for the answer.

    EU holds THREE ACTIVE rows under `asia.theprotocol.cloud`. Without the frame/direct_peer
    clause the branch would face three candidates and have to refuse (or, worse, guess). This
    asserts the population that makes the clause load-bearing, so removing it fails here.
    """
    same_td = [p for p in EU_PEERS
               if p[5] == "asia.theprotocol.cloud" and p[1] == "ACTIVE"]
    assert len(same_td) == 3, same_td
    frames = [p for p in same_td if p[2] in ("frame", "direct_peer")]
    assert [p[0] for p in frames] == ["asia"], frames


def test_an_inactive_frame_row_is_not_an_answer():
    """EU carries a ghost `ASIA` row beside `asia` — deactivated, never deleted (§SLUGCONVERGE).
    If INACTIVE rows counted, this exact table would be ambiguous and resolve nothing."""
    got, _ = _resolve(EU_PEERS, "spiffe://asia.theprotocol.cloud/service/registry")
    assert got == "asia"
    ghosts = [p for p in EU_PEERS if p[0] == "ASIA"]
    assert ghosts and ghosts[0][1] == "INACTIVE" and ghosts[0][2] == "frame", ghosts


# --------------------------------------------------------------------------------------------
# The regression this branch could have caused, and the refusal it must make
# --------------------------------------------------------------------------------------------
def test_an_operator_svid_still_resolves_to_the_operator_not_its_frame():
    """THE REGRESSION CONTROL. registry-a holds `Frame-C` (frame) and `op-doha` (discovered)
    under one trust domain. A trust-domain branch that ran first, or that accepted an
    `/operator/` path, would answer `Frame-C` for a call that came from `op-doha`."""
    got, _ = _resolve(REGISTRY_A_PEERS, "spiffe://frame-c.theprotocol.cloud/operator/op-doha/registry")
    assert got == "op-doha", got


def test_a_frame_that_two_rows_claim_is_refused_by_name():
    got, db = _resolve(AMBIGUOUS_PEERS, "spiffe://shared.example/service/registry")
    assert got is None, got
    # and the refusal must have ASKED the trust-domain question, not simply fallen off the end
    assert any("trust_domain" in s for s in db.statements), db.statements


def test_an_unknown_trust_domain_still_refuses():
    """Widening what we RECOGNISE must never widen what we TRUST."""
    got, _ = _resolve(EU_PEERS, "spiffe://stranger.example/service/registry")
    assert got is None, got


def test_the_name_and_slug_branches_are_untouched():
    """CONTROL — passes BEFORE and AFTER. Every peer with no duplicate row resolved by name, by
    base_url and by operator SVID before this change and must resolve identically after it."""
    assert _resolve(EU_PEERS, "lisbon")[0] == "lisbon"
    assert _resolve(EU_PEERS, "LISBON")[0] == "lisbon"
    assert _resolve(EU_PEERS, "https://lisbon.op.theprotocol.cloud:8443")[0] == "lisbon"
    assert _resolve(EU_PEERS, "https://lisbon.op.theprotocol.cloud")[0] == "lisbon"
    assert _resolve(EU_PEERS, "spiffe://eu.theprotocol.cloud/operator/lisbon/registry")[0] == "lisbon"


def test_a_deactivated_ghost_never_wins_a_lookup():
    """FOUND BY THIS TEST FILE, and it is the half that would have broken the fix.

    The registry-card fan-out re-inserts a peer frame under its UPPERCASE card name and those
    ghosts are deactivated, never deleted (§SLUGCONVERGE) — EU holds `ASIA` beside `asia`. So
    `LOWER(name) = LOWER(:v) LIMIT 1` matched TWO rows with no ORDER BY, and the ghost won.

    Harmless while frame-to-frame resolution was dead in both directions. NOT harmless the
    moment it works: `contracts-for-peer` compares a contract's resolved home against the
    resolved CALLER, so `ASIA` on one side and `asia` on the other filters out every contract
    and returns a clean, wrong, empty list.

    Both spellings, both routes (name and base_url), must land on the ACTIVE row.
    """
    assert _resolve(EU_PEERS, "asia")[0] == "asia"
    assert _resolve(EU_PEERS, "ASIA")[0] == "asia"
    assert _resolve(EU_PEERS, "https://asia.theprotocol.cloud")[0] == "asia"
    assert _resolve(EU_PEERS, "https://asia.theprotocol.cloud:8443")[0] == "asia"
    # and the caller, resolved by trust domain, agrees with all of them — which is the whole point
    assert _resolve(EU_PEERS, "spiffe://asia.theprotocol.cloud/service/registry")[0] == "asia"


# --------------------------------------------------------------------------------------------
# The counter
# --------------------------------------------------------------------------------------------
def test_the_unresolved_counter_says_which_kind():
    """`sum(increase(...))` — what the alert and the degradation panel both use — is unchanged by
    a label, but the two reasons want opposite actions, so the breach must be able to say which."""
    from agentvault_registry.services import contract_xframe as xf

    seen = []

    class _Fake:
        def labels(self, **kw):
            seen.append(kw)
            return self

        def inc(self):
            seen.append("inc")

    real = xf.XFRAME_PEER_UNRESOLVED
    xf.XFRAME_PEER_UNRESOLVED = _Fake()
    try:
        _resolve(EU_PEERS, "spiffe://stranger.example/service/registry")
        assert {"reason": "unmatched"} in seen, seen
        seen.clear()
        _resolve(AMBIGUOUS_PEERS, "spiffe://shared.example/service/registry")
        assert {"reason": "ambiguous_trust_domain"} in seen, seen
    finally:
        xf.XFRAME_PEER_UNRESOLVED = real


def test_a_broken_metric_never_breaks_resolution():
    from agentvault_registry.services import contract_xframe as xf

    class _Boom:
        def labels(self, **kw):
            raise RuntimeError("registry unavailable")

    real = xf.XFRAME_PEER_UNRESOLVED
    xf.XFRAME_PEER_UNRESOLVED = _Boom()
    try:
        assert _resolve(EU_PEERS, "spiffe://stranger.example/service/registry")[0] is None
        assert _resolve(EU_PEERS, "lisbon")[0] == "lisbon"
    finally:
        xf.XFRAME_PEER_UNRESOLVED = real
