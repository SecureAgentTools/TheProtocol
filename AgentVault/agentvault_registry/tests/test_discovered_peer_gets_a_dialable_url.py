"""§FRAMELIC (2026-09-07, findings row 157) — A PEER ROW STORES THE ADDRESS IT WILL BE DIALED AT.

The topology BFS carries two URLs per peer and says so at the point it splits them:

    # rawUrl preserves the :8443 federation port used by Frame-B and
    # some operator nginxes. publicUrl (port-stripped) is for display.

…and then the DB writeback inserted `base_url=public_url` — the DISPLAY value — into
`peer_registries.base_url`, which is the field `federation_sync` DIALS. So every cross-frame
operator a frame discovered was recorded at its :443 console, where the mTLS edge answers
`400 No required SSL certificate was sent`, and never synced: `last_synced_at` NULL for life,
and four `peer_url_misconfigured` drift events per pair.

MEASURED on the EU/ASIA pair: `hochiminh|discovered|ACTIVE|NEVER|https://hochiminh.op.theprotocol.cloud`
beside `hochiminh|cloud_operator|ACTIVE|07:18:24|https://hochiminh.op.theprotocol.cloud:8443` on
the frame that provisioned it — the same operator, recorded twice, and only the row with the port
ever syncs. The right value was in scope the entire time under a different key.

Row 154 made the CARD publish a dialable `federation_base_url`; this is the consumer half, and the
two together are why the fix took two passes: a value can be correct at the source and still never
reach the field that uses it.
"""
import ast
import pathlib

MAIN = (pathlib.Path(__file__).resolve().parents[1]
        / "src" / "agentvault_registry" / "main.py")
SRC = MAIN.read_text()


def _writeback_insert():
    """The PeerRegistry(...) construction inside the topology writeback."""
    tree = ast.parse(SRC)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = getattr(fn, "id", None) or getattr(fn, "attr", None)
        if name != "_PR":
            continue
        kw = {k.arg for k in node.keywords}
        if {"base_url", "peer_type", "hop_distance"} <= kw:
            return node
    raise AssertionError("the topology writeback's peer insert was not found")


def test_base_url_is_not_the_display_url():
    call = _writeback_insert()
    kw = {k.arg: k.value for k in call.keywords}
    assert "base_url" in kw
    val = kw["base_url"]
    assert isinstance(val, ast.Name), ast.dump(val)
    assert val.id != "public_url", (
        "base_url is the field federation_sync DIALS — storing the port-stripped display URL "
        "sends every discovered peer to the :443 console, which refuses a certless caller")
    assert val.id == "federation_url", f"unexpected source for base_url: {val.id}"


def test_the_dialable_url_is_carried_through_the_bfs():
    """It must be present on the registries entry, or the writeback has nothing to read."""
    assert SRC.count('"federationUrl"') >= 2, (
        "both the hop-1 and hop>=2 entries must carry the dialable url")
    assert 'reg.get("federationUrl")' in SRC, "the writeback must read it"


def test_it_falls_back_rather_than_writing_nothing():
    """CONTROL — a peer discovered without a raw url must still get a row, not an empty one."""
    line = next(l for l in SRC.splitlines() if "federation_url = reg.get" in l)
    assert "or public_url" in line, f"missing fallback: {line.strip()}"
