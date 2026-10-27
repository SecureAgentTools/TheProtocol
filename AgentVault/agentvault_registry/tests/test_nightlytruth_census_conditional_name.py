"""§NIGHTLYTRUTH (2026-09-14) — a conditional event name is two census rows, never one prose row.

`background_tasks/federation_sync.py` emits `event_type="PeerTrustActionApplied" if refused else
"PeerTrustActionObserved"`. The emission census unparsed that keyword, saw a leading quote, stripped the
quotes and filed `PeerTrustActionApplied' if refused else 'PeerTrustActionObserved` as ONE event — which
its own control (`emission_census_is_reading_real_code`) then reported as "a row that looks like prose"
on every nightly run, a red about the instrument. The extraction now reads the AST: a string constant is
one name, a conditional with two string branches is two, anything else (an f-string, a variable) is none.
The last test runs the REAL census over the tree and asserts the control's own property.
"""
from __future__ import annotations

import ast

from agentvault_registry.api_tests.federation_suite.tests import test_event_emission_contract as t


def _call(src: str) -> ast.Call:
    tree = ast.parse(src)
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call)][0]


def test_a_constant_keyword_is_one_name():
    assert t._event_names_of(_call("emitter.emit(event_type='TokensTransferred', data={})")) == [("TokensTransferred", "keyword")]


def test_a_conditional_keyword_is_two_names():
    call = _call("await emitter.emit_event(event_type='PeerTrustActionApplied' if refused else 'PeerTrustActionObserved', event_data={})")
    assert t._event_names_of(call) == [("PeerTrustActionApplied", "keyword-conditional"), ("PeerTrustActionObserved", "keyword-conditional")]


def test_a_non_literal_keyword_is_no_name():
    assert t._event_names_of(_call("emitter.emit(event_type=f'{prefix}Changed', data={})")) == []
    assert t._event_names_of(_call("emitter.emit(event_type=name, data={})")) == []


def test_a_positional_literal_still_counts():
    assert t._event_names_of(_call("_emit('GuildBidPlaced', agg, {})")) == [("GuildBidPlaced", "positional")]
    assert t._event_names_of(_call("_emit(some_var, agg, {})")) == []


def test_the_real_census_carries_both_branches_and_no_prose_row():
    rows = t._census()
    assert len(rows) >= 300, "the census is looking in the wrong tree"
    events = {r["event"] for r in rows}
    assert "PeerTrustActionApplied" in events and "PeerTrustActionObserved" in events
    prose = [r for r in rows if not r["event"] or " " in r["event"]]
    assert prose == [], prose
    cond = [r for r in rows if r["how"] == "keyword-conditional"]
    # Selected by FILE, not by position: V0397 added a second conditional emit (admin_broadcast.py's direct notice),
    # and "the first two rows are federation_sync's" was a claim about the tree's population, not about the census.
    fed = {r["event"] for r in cond if r["file"].endswith("federation_sync.py")}
    assert {"PeerTrustActionApplied", "PeerTrustActionObserved"} <= fed
    notice = {r["event"] for r in cond if r["file"].endswith("admin_broadcast.py")}
    assert {"AdminDirectNoticeSent", "AdminBroadcastSent"} <= notice
