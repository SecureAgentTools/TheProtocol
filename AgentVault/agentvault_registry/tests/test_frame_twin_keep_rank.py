"""§FRAMETWIN (2026-09-29) — of two peer-FRAME rows of one trust domain, the reconcile keeps the one that dials the
frame's declared federation lane, never the one the database happened to return first.

main.py's sovereign-mesh reconcile (inside `_run_topology_bfs`, pass 2) keeps the FIRST ACTIVE frame row it meets per
trust domain and parks the others as `duplicate_frame`. It met them in unordered SELECT order. Measured on production
(scratchpad/mcpsweep/frame_twin_census.py): every node held a frame's 443 card-name twin beside the row the invitation
or provisioner wrote, and the 2026-09-07 reconcile kept the right row on four nodes and the 443 twin on shenzhen
(#3 `EU` over #2 `eu`, the higher id) and hochiminh (#11 over #10). EU's card feed answers 401 behind the 443 twin, so
their EU corridor carried nothing until the rows were swapped by hand on 09-28. A parked row stays parked, so an order
that chose wrong once chose for good.
"""
import ast
import pathlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from agentvault_registry.core.peer_group import frame_row_keep_rank

MAIN = (pathlib.Path(__file__).resolve().parents[1]
        / "src" / "agentvault_registry" / "main.py")

LANE = "https://eu.theprotocol.cloud:8443"
CARD = {"identity": {"registry_name": "EU", "tier": "sovereign-mainframe", "federation_base_url": LANE}}
NOW = datetime(2026, 9, 29, 5, 0, tzinfo=timezone.utc)


def _row(rid, name, base_url, synced=None, card=CARD):
    return SimpleNamespace(id=rid, name=name, base_url=base_url, last_synced_at=synced, cached_registry_card=card,
                           status="ACTIVE", trust_domain="eu.theprotocol.cloud")


def _kept(rows):
    return sorted(rows, key=frame_row_keep_rank)[0]


def test_the_measured_shenzhen_pair_keeps_the_lane_row_in_either_order():
    lane, twin = _row(2, "eu", LANE), _row(3, "EU", "https://eu.theprotocol.cloud")
    assert _kept([lane, twin]) is lane
    assert _kept([twin, lane]) is lane, "the SELECT returned the twin first on shenzhen and the twin was kept"


def test_the_lane_beats_an_older_twin_that_synced():
    """The frame's own signed declaration outranks both other signals."""
    lane = _row(11, "eu", LANE)
    twin = _row(10, "EU", "https://eu.theprotocol.cloud", synced=NOW)
    assert _kept([twin, lane]) is lane


def test_spelling_does_not_hide_the_lane():
    lane = _row(7, "eu", "HTTPS://EU.theprotocol.cloud:8443/")
    twin = _row(5, "EU", "https://eu.theprotocol.cloud:443")      # the console, with its default port written out
    assert _kept([twin, lane]) is lane
    assert frame_row_keep_rank(twin)[0] == 1, "the 443 console must never read as the :8443 lane"


def test_without_a_declared_lane_a_row_that_synced_is_kept_the_newest_first():
    card = {"identity": {"tier": "sovereign-mainframe"}}
    never = _row(1, "a", "https://a.example:8443", card=card)
    old = _row(2, "b", "https://b.example:8443", synced=NOW - timedelta(days=3), card=card)
    new = _row(3, "c", "https://c.example:8443", synced=NOW, card=card)
    assert _kept([never, old, new]) is new
    assert sorted([never, old, new], key=frame_row_keep_rank) == [new, old, never]


def test_the_oldest_row_breaks_a_full_tie():
    card = {"identity": {"tier": "sovereign-mainframe"}}
    a, b = _row(9, "x", "https://x.example", card=card), _row(4, "X", "https://x.example:8443", card=card)
    assert _kept([a, b]) is b and _kept([b, a]) is b


def test_a_missing_or_junk_card_never_raises():
    for card in (None, "junk", {"identity": "junk"}, {"identity": {"federation_base_url": None}},
                 {"identity": {"federation_base_url": "https://[::1"}}):
        r = _row(1, "x", None, card=card)
        assert frame_row_keep_rank(r)[0] == 1
    assert frame_row_keep_rank(SimpleNamespace())[0] == 1


def _reconcile_dedup_loop():
    """The pass-2 loop of the topology reconcile: the `for` whose body parks a row as `duplicate_frame`."""
    tree = ast.parse(MAIN.read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.For):
            continue
        for sub in ast.walk(node):
            if (isinstance(sub, ast.Assign) and isinstance(sub.value, ast.Constant)
                    and sub.value.value == "duplicate_frame"
                    and any(isinstance(t, ast.Attribute) and t.attr == "deactivated_reason" for t in sub.targets)):
                return node
    raise AssertionError("the reconcile's duplicate_frame loop was not found in main.py")


def test_the_reconcile_meets_the_rows_in_this_order():
    loop = _reconcile_dedup_loop()
    it = loop.iter
    assert isinstance(it, ast.Call) and getattr(it.func, "id", None) == "sorted", (
        "the dedup keeps the FIRST row it meets per trust domain: iterating the SELECT's rows as returned "
        "draws the survivor by lottery")
    assert isinstance(it.args[0], ast.Name) and it.args[0].id == "rc_rows"
    key = {k.arg: k.value for k in it.keywords}.get("key")
    assert isinstance(key, ast.Name) and key.id == "_frame_row_keep_rank"
    imports = [n for n in ast.walk(ast.parse(MAIN.read_text())) if isinstance(n, ast.ImportFrom)
               and n.module == "agentvault_registry.core.peer_group"
               and any(a.name == "frame_row_keep_rank" and a.asname == "_frame_row_keep_rank" for a in n.names)]
    assert imports, "the key must be the shared rule in core/peer_group.py, not a local copy"
