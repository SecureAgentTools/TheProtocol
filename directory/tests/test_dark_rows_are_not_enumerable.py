"""§DARKSYNC (2026-09-22): the federated index must not hand anyone the agents their homes just took dark.

A registry hides an unlisted agent from its own discovery (V0424) and stops publishing its card; this index then marks
the row unreachable on its next full pass. While `agents(includeGone: true)` existed, one public query walked exactly
that set — measured on the live indexes before this change: 43 rows on EU/ASIA, 8 on the sandbox, cards and all.

The rule these tests pin: the connection enumerates the LIVE set only, a gone row is still kept (never deleted, so a
source that publishes it again restores it), and a caller that already knows a DID can still resolve one — a direct
lookup is not enumeration, which is the same line the registries draw.
"""
import sqlite3
import tempfile

from directory.schema import schema
from directory.store import Store


def test_the_agents_connection_takes_no_include_gone_argument():
    sdl = schema.as_str()
    assert "includeGone" not in sdl, "a public query must not be able to ask for the rows a home stopped publishing"
    assert "agents(" in sdl and "agent(did:" in sdl.replace(" ", ""), "enumeration narrowed, direct resolution kept"


def test_a_query_asking_for_gone_rows_is_refused_rather_than_quietly_ignored():
    # the §DIRFEED lesson: a server that ignores an argument answers 200 and the caller never learns its filter was
    # dropped. An unknown argument is a validation error, which says so.
    r = schema.execute_sync('{ agents(first: 5, includeGone: true) { total } }', context_value={"store": None})
    # ⚠ assert the VALIDATION message, not str(error): a GraphQLError prints the offending source line, so
    # `"includeGone" in str(...)` also passes when the resolver merely blew up on a null store — which is what the
    # control run showed (this test passed against the code that still took the argument).
    assert r.errors, "asking for gone rows must be an error"
    msg = r.errors[0].message
    assert "Unknown argument" in msg and "includeGone" in msg, msg


def _store_with(rows):
    path = tempfile.mkdtemp() + "/d.db"
    st = Store(path)
    with sqlite3.connect(path) as c:
        for did, name, reachable in rows:
            c.execute("INSERT INTO agents (id, did, name, source, issuer, reachable, is_active, fetched_at) "
                      "VALUES (?,?,?,?,?,?,1,0)", (did, did, name, "EU", "eu.theprotocol.cloud", reachable))
        c.commit()
    return st


def test_the_live_page_excludes_a_gone_row_and_the_did_lookup_still_finds_it():
    st = _store_with([("did:theprotocol:live", "listed agent", 1), ("did:theprotocol:dark", "canary-eu-sender", 0)])
    page = st.list_agents(first=50)
    assert [r["did"] for r in page["rows"]] == ["did:theprotocol:live"] and page["total"] == 1
    assert st.list_agents(first=50, name_contains="canary")["rows"] == []
    assert (st.get_agent("did:theprotocol:dark") or {}).get("name") == "canary-eu-sender"   # kept, and resolvable by DID


def test_the_store_can_still_be_asked_for_gone_rows_by_a_non_public_reader():
    st = _store_with([("did:theprotocol:live", "listed agent", 1), ("did:theprotocol:dark", "canary-eu-sender", 0)])
    assert len(st.list_agents(first=50, include_gone=True)["rows"]) == 2
