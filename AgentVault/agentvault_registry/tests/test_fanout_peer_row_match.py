"""§HELLOFRAME D3 residue 2 (2026-09-18) — the registry-card fan-out ties an entry to an EXISTING peer row by
name CASE-INSENSITIVELY (the rule `fanout_peer_name_allowed` already applies) or by base_url, before it would
insert a `discovered` twin.

Measured on EU and ASIA on 2026-09-18: each frame held an INACTIVE `duplicate_frame` twin (`ASIA` beside `asia`,
`EU` beside `eu`). The invitation rail had written the row under the invitation's `name` (`asia`) with the
federation lane as base_url; the frame's own fan-out entry carried its card's `registry_name` (`ASIA`) with its
public console URL as base_url; so neither half of the old match (exact name, equal base_url) saw one peer.

Pinned two ways, per §DIRFEED-2: the compiled STATEMENT (a fixture cannot see an ordering or a function that is
missing), and the predicate's answer on a table shaped like the live rows (the twin shape, the control that a
genuinely different name still reaches the insert branch, and the base_url half unchanged)."""
import sqlalchemy as sa
from sqlalchemy import or_, select
from sqlalchemy.dialects import postgresql

from agentvault_registry import models
from agentvault_registry.background_tasks.federation_sync import fanout_peer_row_match


def _compiled(peer_name, base_url):
    stmt = select(models.PeerRegistry.id).where(or_(*fanout_peer_row_match(peer_name, base_url)))
    return stmt.compile(dialect=postgresql.dialect())


def test_the_statement_lowercases_the_name_and_keeps_the_base_url_half():
    c = _compiled("ASIA", "https://asia.example")
    sql = str(c)
    assert "lower(peer_registries.name)" in sql
    assert "peer_registries.base_url IN" in sql
    flat = []                                                             # the IN clause binds one LIST parameter
    for v in c.params.values():
        flat.extend(v if isinstance(v, (list, tuple)) else [v])
    assert "asia" in flat and "ASIA" not in flat                          # the row is compared to the lowercase form
    assert {"https://asia.example", "https://asia.example/"} <= set(flat)  # with and without the trailing slash


def test_without_a_base_url_only_the_name_half_is_asked():
    crit = fanout_peer_row_match("asia", "")
    assert len(crit) == 1
    sql = str(_compiled("asia", ""))
    assert "lower(peer_registries.name)" in sql and "base_url" not in sql
    assert len(fanout_peer_row_match("asia", None)) == 1


def _rows_like_the_live_twins():
    """An in-memory table with the three columns the predicate reads, shaped like EU's rows on 2026-09-18: the
    invitation-made row `asia` carries the FEDERATION lane as base_url; a second, unrelated peer beside it."""
    eng = sa.create_engine("sqlite://")
    with eng.begin() as c:
        c.exec_driver_sql(
            "CREATE TABLE peer_registries (id INTEGER PRIMARY KEY, name TEXT NOT NULL, base_url TEXT NOT NULL)")
        c.exec_driver_sql(
            "INSERT INTO peer_registries (id, name, base_url) VALUES (3, 'asia', 'https://asia.theprotocol.cloud:8443')")
        c.exec_driver_sql(
            "INSERT INTO peer_registries (id, name, base_url) VALUES (4, 'frame-b', 'https://frame-b.example:8443')")
    return eng


def _ids(eng, peer_name, base_url):
    stmt = (select(models.PeerRegistry.id)
            .where(or_(*fanout_peer_row_match(peer_name, base_url)))
            .order_by(models.PeerRegistry.id))
    with eng.connect() as c:
        return [r[0] for r in c.execute(stmt)]


def test_a_row_asia_and_an_entry_ASIA_are_one_peer():
    eng = _rows_like_the_live_twins()
    # the measured twin shape: the card's name in upper case, the card's public URL (no lane port) as base_url
    assert _ids(eng, "ASIA", "https://asia.theprotocol.cloud") == [3]
    assert _ids(eng, "Asia", "") == [3]
    assert _ids(eng, " asia ", "") == [3]                                  # whitespace is not a different peer
    assert _ids(eng, "asia", "") == [3]                                    # the exact name still matches


def test_a_genuinely_different_name_still_reaches_the_insert_branch():
    eng = _rows_like_the_live_twins()
    assert _ids(eng, "beacon", "https://beacon.example:8443") == []       # peer_row is None: the receiver inserts
    assert _ids(eng, "asia2", "") == []
    assert _ids(eng, "asi", "https://asia.example") == []                 # a prefix is not the name


def test_the_base_url_half_still_matches_with_or_without_the_trailing_slash():
    eng = _rows_like_the_live_twins()
    assert _ids(eng, "somebody-else", "https://asia.theprotocol.cloud:8443/") == [3]
    assert _ids(eng, "somebody-else", "https://frame-b.example:8443") == [4]
    assert _ids(eng, "somebody-else", "https://asia.theprotocol.cloud") == []  # a different port is a different URL
